"""One bounded background run; private history, cooldowns and no formal DB writes.

V1 is for one local API worker. Source readers and admission are injected so the
same orchestration can later be called by a scheduler without changing the UI.
"""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .batch_sources import fetch_source_page, list_batch_sources
from .staging import read_staging, stage_unique_jobs


ACTIVE = {"queued", "running"}
MAX_HISTORY = 20
MAX_STATE_BYTES = 12 * 1024 * 1024


class BatchBusyError(RuntimeError):
    def __init__(self, message, *, retry_at=None):
        super().__init__(message)
        self.retry_at = retry_at


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def body_fingerprint(text):
    return hashlib.sha256(re.sub(r"\s+", "", text).lower().encode("utf-8")).hexdigest()


def read_formal_fingerprints(database_path: Path) -> set[str]:
    """Never create or migrate the formal database from the collector."""
    with closing(sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        return {body_fingerprint(row[0]) for row in connection.execute("SELECT description FROM jobs")}


class BatchCollector:
    def __init__(self, data_directory: Path, assess, directions: dict, *, fetch=fetch_source_page, catalog=list_batch_sources):
        self.data_directory = data_directory
        self.path = data_directory / "collector-runs" / "state.json"
        self.assess, self.directions = assess, directions
        self.fetch, self.catalog = fetch, catalog
        self.lock = RLock()
        self._state = None

    def _load(self):
        if self._state is not None:
            return self._state
        state = {"schema_version": 1, "settings": self.defaults(), "runs": []}
        if self.path.exists():
            if self.path.stat().st_size > MAX_STATE_BYTES:
                raise ValueError("采集任务记录超过读取上限，请先检查私有记录")
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("schema_version") != 1 or not isinstance(state.get("runs"), list):
                raise ValueError("采集任务记录损坏；没有覆盖原文件")
        self._state = state
        interrupted = False
        for run in state["runs"]:
            if run["status"] in ACTIVE:
                run.update(status="interrupted", finished_at=now_iso(), error="后端重启使上次任务中断；已写入的暂存数据保留，不会自动重跑。")
                for source in run["sources"]:
                    if source["status"] in ACTIVE:
                        source["status"] = "interrupted"
                interrupted = True
        if interrupted:
            self._save()
        return state

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(self._state, ensure_ascii=False, indent=2)
        if len(raw.encode("utf-8")) > MAX_STATE_BYTES:
            raise ValueError("采集任务记录达到保存上限")
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(raw, encoding="utf-8", newline="\n")
        temporary.replace(self.path)

    def defaults(self):
        return {"source_keys": [s["key"] for s in self.catalog() if s.get("default_selected")],
                "directions": ["tools", "vibe"], "per_source_limit": 30,
                "staging_limit": 10, "include_uncertain": False}

    def _validate(self, options):
        if set(options) != set(self.defaults()):
            raise ValueError("采集配置字段不完整或包含未知字段")
        for key, available, maximum in (("source_keys", {s["key"] for s in self.catalog()}, 5),
                                        ("directions", set(self.directions), 3)):
            values = options[key]
            if (not isinstance(values, list) or not 1 <= len(values) <= maximum
                or any(not isinstance(v, str) or v not in available for v in values)
                or len(values) != len(set(values))):
                raise ValueError("请选择有效且不重复的来源 / 岗位方向")
        for key, maximum in (("per_source_limit", 100), ("staging_limit", 20)):
            if type(options[key]) is not int or not 1 <= options[key] <= maximum:
                raise ValueError(f"{key} 超出允许范围 1～{maximum}")
        if type(options["include_uncertain"]) is not bool:
            raise ValueError("待核实开关必须是布尔值")

    def state(self):
        with self.lock:
            state = self._load()
            return deepcopy({"sources": self.catalog(), "directions": self.directions,
                "settings": state["settings"], "latest": state["runs"][-1] if state["runs"] else None,
                "history": [{k: r.get(k) for k in ("id", "status", "started_at", "finished_at", "counts")}
                            for r in reversed(state["runs"])],
                "note": "只读取已审核来源；现有来源覆盖仍有限，不保证有低门槛结果。BOSS 保持手动导入。"})

    def get_run(self, run_id):
        with self.lock:
            for run in self._load()["runs"]:
                if run["id"] == run_id:
                    return deepcopy(run)
        raise KeyError("采集任务不存在")

    def create(self, options, profile, *, trigger="manual"):
        if trigger not in {"manual", "scheduled"}:
            raise ValueError("无效的采集触发方式")
        self._validate(options)
        if not isinstance(profile, dict) or profile.get("schema_version") != 1:
            raise ValueError("个人可投性资料未配置，已停止采集；请先完善个人资料")
        with self.lock:
            state = self._load()
            if any(run["status"] in ACTIVE for run in state["runs"]):
                raise BatchBusyError("已有采集任务在运行，请等待完成")
            now = datetime.now(timezone.utc)
            for run in state["runs"]:
                for source in run["sources"]:
                    until = source.get("next_allowed_at")
                    if source["key"] in options["source_keys"] and until and datetime.fromisoformat(until) > now:
                        raise BatchBusyError(f"{source['company']} 尚在冷却期，{until} 后可再次采集", retry_at=until)
            counts = {key: 0 for key in ("scanned", "accepted", "needs_review", "excluded", "added", "updated", "duplicates", "limited", "errors")}
            sources = {s["key"]: s for s in self.catalog()}
            run = {"id": uuid4().hex, "status": "queued", "trigger": trigger, "started_at": now_iso(), "finished_at": None,
                   "settings": deepcopy(options), "counts": counts, "sources": [], "items": [], "error": None}
            for key in options["source_keys"]:
                run["sources"].append({"key": key, "company": sources[key]["company"], "status": "queued",
                    "scanned": 0, "total": None, "truncated": False, "error": None, "next_allowed_at": None})
            state["runs"].append(run)
            state["runs"] = state["runs"][-MAX_HISTORY:]
            if trigger == "manual":
                state["settings"] = deepcopy(options)
            try:
                self._save()
            except Exception:
                state["runs"].remove(run)
                raise
            return deepcopy(run)

    def execute(self, run_id, profile, formal_fingerprints: set[str]):
        with self.lock:
            run = next(r for r in self._load()["runs"] if r["id"] == run_id)
            if run["status"] != "queued":
                return
            run["status"] = "running"
            self._save()
        try:
            known = set(formal_fingerprints)
            known.update(body_fingerprint(r.get("description", "")) for r in read_staging(data_directory=self.data_directory))
            settings = run["settings"]
            for source in run["sources"]:
                with self.lock:
                    source.update(status="running", next_allowed_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
                    self._save()
                try:
                    page = self.fetch(source["key"], settings["per_source_limit"])
                except Exception as error:
                    # Do not expose exception URLs, tokens or a traceback in UI.
                    message = str(error) if isinstance(error, (ValueError, PermissionError, RuntimeError)) else "读取来源失败，请检查网络后再试"
                    with self.lock:
                        source.update(status="failed", error=message[:300])
                        if re.search(r"403|429|限流|暂停", message):
                            source["next_allowed_at"] = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
                        run["counts"]["errors"] += 1
                        self._save()
                    continue
                with self.lock:
                    source.update(scanned=page.scanned, total=page.total, truncated=page.truncated)
                    run["counts"]["scanned"] += page.scanned
                    run["counts"]["errors"] += len(page.errors)
                    for error in page.errors:
                        run["items"].append({"title": f"第 {error['index']} 条数据", "company": source["company"],
                            "source_url": None, "decision": "invalid", "action": "invalid", "reasons": [error["reason"]]})
                for job in page.jobs:
                    assessment = self.assess(job, profile, settings["directions"])
                    decision = assessment["decision"]
                    action = "excluded" if decision == "excluded" else "review_only"
                    reasons = list(assessment["reasons"])
                    fingerprint = body_fingerprint(job.description)
                    with self.lock:
                        run["counts"][decision] += 1
                    if decision == "accepted" or decision == "needs_review" and settings["include_uncertain"]:
                        if fingerprint in known:
                            action = "duplicate"
                            run["counts"]["duplicates"] += 1
                            reasons.append("正式库或历史暂存已有相同正文，未重复写入")
                        elif run["counts"]["added"] + run["counts"]["updated"] >= settings["staging_limit"]:
                            action = "limit_reached"
                            run["counts"]["limited"] += 1
                            reasons.append("达到本次暂存上限，未写入")
                        else:
                            summary = stage_unique_jobs([job], data_directory=self.data_directory,
                                review_metadata={"run_id": run_id, **assessment})
                            run["counts"]["added"] += summary.added_count
                            run["counts"]["updated"] += summary.updated_count
                            run["counts"]["duplicates"] += summary.skipped_count
                            action = "staged" if summary.added_count else "updated" if summary.updated_count else "duplicate"
                            known.add(fingerprint)
                    with self.lock:
                        run["items"].append({"title": job.title, "company": job.company, "source_url": job.source_url,
                            "decision": decision, "action": action, "reasons": reasons})
                        self._save()
                with self.lock:
                    source["status"] = "partial_failure" if page.errors else "completed"
                    self._save()
            with self.lock:
                failed = all(s["status"] == "failed" for s in run["sources"])
                run["status"] = "failed" if failed else "partial_failure" if run["counts"]["errors"] else "completed"
        except Exception:
            with self.lock:
                run.update(status="failed", error="任务执行或保存失败，已停止；已有暂存记录保留。请检查 D 盘权限、空间及采集日志。")
                run["counts"]["errors"] += 1
        finally:
            with self.lock:
                for source in run["sources"]:
                    if source["status"] in ACTIVE:
                        source["status"] = "interrupted"
                run["finished_at"] = now_iso()
                self._save()
