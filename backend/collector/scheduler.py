"""Opt-in, single-worker interval scheduler for the existing batch pipeline."""

import json
import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, RLock, Thread

from .batch import BatchBusyError


INTERVALS = {60: "每 1 小时", 360: "每 6 小时", 720: "每 12 小时", 1440: "每 24 小时"}
log = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("定时时间必须带时区")
    return parsed


class CollectionScheduler:
    def __init__(self, collector, load_profile, load_fingerprints, *, clock=utc_now, tick_seconds=15):
        self.collector = collector
        self.path = collector.data_directory / "collector-runs" / "schedule.json"
        self.load_profile = load_profile
        self.load_fingerprints = load_fingerprints
        self.clock = clock
        self.tick_seconds = tick_seconds
        self.lock, self.tick_lock = RLock(), Lock()
        self.stop_event = Event()
        self.thread = None
        self.runtime_error = None
        self._state = None

    def _load(self):
        if self._state is not None:
            return self._state
        state = {"schema_version": 1, "enabled": False, "interval_minutes": 360,
                 "options": None, "next_run_at": None, "updated_at": None, "last_event": None,
                 "last_run_id": None, "last_result": None}
        if self.path.exists():
            if self.path.stat().st_size > 64 * 1024:
                raise ValueError("定时配置超过读取上限")
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(stored, dict) or stored.get("schema_version") != 1
                or type(stored.get("enabled")) is not bool
                or type(stored.get("interval_minutes")) is not int
                or stored["interval_minutes"] not in INTERVALS
                or stored.get("options") is not None and not isinstance(stored["options"], dict)):
                raise ValueError("定时配置损坏，未覆盖原文件")
            state.update(stored)
            if state["next_run_at"] is not None:
                parse_time(state["next_run_at"])
            if state["enabled"] and (not state["options"] or not state["next_run_at"]):
                raise ValueError("已启用的定时配置不完整")
        self._state = state
        return state

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        temporary.replace(self.path)

    def _event(self, kind, message):
        self._state["last_event"] = {"kind": kind, "message": message, "at": self.clock().isoformat()}

    def state(self):
        with self.lock:
            return {**deepcopy(self._load()), "interval_choices": INTERVALS,
                    "runner_running": bool(self.thread and self.thread.is_alive() and not self.stop_event.is_set()),
                    "runtime_error": self.runtime_error}

    def configure(self, interval_minutes, options):
        """Explicit enable/update: snapshot options; first run is one interval later."""
        if self.runtime_error:
            raise ValueError("定时执行器不可用，请检查错误并重启后端后再启用")
        if type(interval_minutes) is not int or interval_minutes not in INTERVALS:
            raise ValueError("定时频率仅支持每 1、6、12 或 24 小时")
        self.collector._validate(options)
        profile = self.load_profile()
        if not isinstance(profile, dict) or profile.get("schema_version") != 1:
            raise ValueError("个人条件未配置，不能启用定时采集")
        with self.lock:
            state = self._load()
            previous = deepcopy(state)
            state.update(enabled=True, interval_minutes=interval_minutes, options=deepcopy(options),
                         next_run_at=(self.clock() + timedelta(minutes=interval_minutes)).isoformat(),
                         updated_at=self.clock().isoformat())
            self._event("configured", "已保存当前采集配置；到下次运行时间才执行，不会立即采集。")
            try:
                self._save()
            except Exception:
                self._state = previous
                raise
            return self.state()

    def pause(self):
        with self.lock:
            state = self._load()
            previous = deepcopy(state)
            state.update(enabled=False, next_run_at=None, updated_at=self.clock().isoformat())
            self._event("paused", "已暂停后续定时任务；已经开始的采集仍会完成。")
            try:
                self._save()
            except Exception:
                self._state = previous
                raise
            return self.state()

    def recover(self):
        """At process startup, skip missed intervals instead of replaying a backlog."""
        with self.lock:
            self.collector.state()  # Recover abandoned batch tasks first.
            state = self._load()
            if state["enabled"] and parse_time(state["next_run_at"]) <= self.clock():
                state["next_run_at"] = (self.clock() + timedelta(minutes=state["interval_minutes"])).isoformat()
                self._event("missed_skipped", "停服期间错过的任务未补跑，已安排下一个周期。")
                self._save()

    def tick(self):
        if not self.tick_lock.acquire(blocking=False):
            return
        try:
            with self.lock:
                state = self._load()
                now = self.clock()
                if self.stop_event.is_set() or not state["enabled"] or parse_time(state["next_run_at"]) > now:
                    return
                options = deepcopy(state["options"])
                # Persist the next deadline before creating work, preventing
                # restart from replaying the same due interval.
                state["next_run_at"] = (now + timedelta(minutes=state["interval_minutes"])).isoformat()
                self._save()
                try:
                    profile = self.load_profile()
                    fingerprints = self.load_fingerprints()
                    run = self.collector.create(options, profile, trigger="scheduled")
                except BatchBusyError as error:
                    retry = parse_time(error.retry_at) if error.retry_at else now + timedelta(minutes=1)
                    state["next_run_at"] = max(retry, now + timedelta(minutes=1)).isoformat()
                    self._event("deferred", "已有采集任务或来源仍在冷却，已自动延后；未发送采集请求。")
                    self._save()
                    return
                except Exception:
                    state.update(enabled=False, next_run_at=None)
                    self._event("blocked", "个人资料、来源配置或任务存储不可用，定时已暂停；请检查后重新启用。")
                    self._save()
                    log.exception("Scheduled collection preparation failed")
                    return
                state["last_run_id"] = run["id"]
                self._event("started", "已自动启动采集；详情见下方任务记录。")
                self._save()
            # Do not hold the scheduler lock during networking: pause remains
            # responsive, while the one already claimed bounded run can finish.
            self.collector.execute(run["id"], profile, fingerprints)
            result = self.collector.get_run(run["id"])
            with self.lock:
                self._state["last_result"] = {"run_id": run["id"], "status": result["status"],
                    "counts": result["counts"], "finished_at": result["finished_at"]}
                if self._state["enabled"]:
                    self._event("finished", "本轮定时采集已结束；新增岗位仍需人工确认，失败信息见任务记录。")
                self._save()
        finally:
            self.tick_lock.release()

    def _loop(self):
        while not self.stop_event.wait(self.tick_seconds):
            try:
                self.tick()
            except Exception:
                log.exception("Collection scheduler stopped after an unexpected error")
                with self.lock:
                    self.runtime_error = "定时执行器遇到存储或执行异常，已停止；请检查后重启后端。"
                self.stop_event.set()

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            try:
                self.recover()
            except Exception:
                self.runtime_error = "定时配置或任务记录无法读取，自动采集未启动；其他功能仍可使用。"
                log.exception("Collection scheduler startup failed")
                return
            self.runtime_error = None
            self.stop_event.clear()
            self.thread = Thread(target=self._loop, name="collection-scheduler", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
