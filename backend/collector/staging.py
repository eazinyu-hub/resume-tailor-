import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from functools import wraps
from threading import RLock

from .adapters.greenhouse import clean_greenhouse_description
from .models import CollectedJob, calculate_content_hash


DEFAULT_DATA_DIRECTORY = Path(r"D:\AI\resume-tailor-data")
MAX_STAGING_FILE_BYTES = 20 * 1024 * 1024
MAX_STAGING_RECORDS = 500
_STAGING_LOCK = RLock()


def _synchronized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _STAGING_LOCK:
            return function(*args, **kwargs)
    return wrapped


class StagingReadError(RuntimeError):
    pass


@dataclass(frozen=True)
class StagingAppendSummary:
    path: Path
    added_count: int
    skipped_count: int
    updated_count: int
    messages: tuple[str, ...]


def get_staging_path(data_directory: Path | None = None) -> Path:
    configured_directory = data_directory
    if configured_directory is None:
        configured_directory = Path(
            os.environ.get("DATA_DIR", str(DEFAULT_DATA_DIRECTORY))
        )
    return configured_directory / "collector-staging" / "pending-jobs.jsonl"


def append_to_staging(
    jobs: Iterable[CollectedJob],
    *,
    data_directory: Path | None = None,
) -> Path:
    """Append only new or updated records and keep the legacy path return."""

    return stage_unique_jobs(jobs, data_directory=data_directory).path


def _same_source_job(record: dict[str, Any], job: CollectedJob) -> bool:
    if not job.source_job_id:
        return record.get("content_hash") == job.content_hash
    return (
        record.get("source_id") == job.source_id
        and str(record.get("source_job_id") or "") == job.source_job_id
    )


def _write_collection_event(
    staging_path: Path,
    event: dict[str, Any],
) -> None:
    event_path = staging_path.with_name("collection-events.jsonl")
    with event_path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(event, ensure_ascii=False) + "\n")


@_synchronized
def stage_unique_jobs(
    jobs: Iterable[CollectedJob],
    *,
    data_directory: Path | None = None,
    review_metadata: dict[str, Any] | None = None,
) -> StagingAppendSummary:
    """Stage jobs once, while preserving changed source jobs as new versions."""

    staging_path = get_staging_path(data_directory)
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    existing_records = read_staging(data_directory=data_directory)
    added_count = 0
    skipped_count = 0
    updated_count = 0
    messages: list[str] = []
    with staging_path.open("a", encoding="utf-8", newline="\n") as output:
        for job in jobs:
            matching_records = [
                record
                for record in existing_records
                if _same_source_job(record, job)
            ]
            exact_match = next(
                (
                    record
                    for record in reversed(matching_records)
                    if record.get("content_hash") == job.content_hash
                ),
                None,
            )
            event_time = datetime.now(timezone.utc).isoformat()
            if exact_match is not None:
                skipped_count += 1
                messages.append(f"已跳过重复岗位：{job.title}")
                _write_collection_event(
                    staging_path,
                    {
                        "event": "duplicate_skipped",
                        "reason": "same_source_job_and_content",
                        "source_id": job.source_id,
                        "source_job_id": job.source_job_id,
                        "content_hash": job.content_hash,
                        "occurred_at": event_time,
                    },
                )
                continue

            if len(existing_records) >= MAX_STAGING_RECORDS:
                raise StagingReadError("采集暂存记录超过写入上限")
            record = job.to_staging_record()
            if review_metadata is not None:
                record["batch_screening"] = review_metadata
            if matching_records:
                previous = matching_records[-1]
                record.update(
                    {
                        "collection_status": "updated_source",
                        "previous_content_hash": previous.get("content_hash"),
                        "collection_notice": (
                            "同一来源岗位已有旧版本，请核对本次更新内容。"
                        ),
                    }
                )
                updated_count += 1
                messages.append(f"发现岗位新版本：{job.title}")
                event_name = "updated_source_staged"
            else:
                record["collection_status"] = "new"
                added_count += 1
                messages.append(f"已暂存新岗位：{job.title}")
                event_name = "new_job_staged"

            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            existing_records.append(record)
            _write_collection_event(
                staging_path,
                {
                    "event": event_name,
                    "source_id": job.source_id,
                    "source_job_id": job.source_job_id,
                    "content_hash": job.content_hash,
                    "previous_content_hash": record.get(
                        "previous_content_hash"
                    ),
                    "occurred_at": event_time,
                },
            )

    return StagingAppendSummary(
        path=staging_path,
        added_count=added_count,
        skipped_count=skipped_count,
        updated_count=updated_count,
        messages=tuple(messages),
    )


@_synchronized
def read_staging(
    *,
    data_directory: Path | None = None,
) -> list[dict[str, Any]]:
    """Read review records without changing or importing them."""

    staging_path = get_staging_path(data_directory)
    if not staging_path.exists():
        return []
    if staging_path.stat().st_size > MAX_STAGING_FILE_BYTES:
        raise StagingReadError("采集暂存文件超过读取上限")

    records: list[dict[str, Any]] = []
    with staging_path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            if len(records) >= MAX_STAGING_RECORDS:
                raise StagingReadError("采集暂存记录超过读取上限")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise StagingReadError(
                    f"采集暂存文件第 {line_number} 行不是有效 JSON"
                ) from error
            if not isinstance(record, dict):
                raise StagingReadError(
                    f"采集暂存文件第 {line_number} 行不是岗位对象"
                )
            records.append(record)
    return records


@_synchronized
def repair_greenhouse_staging_html(
    *,
    data_directory: Path | None = None,
) -> dict[str, object]:
    """Repair escaped Greenhouse HTML with a recoverable local backup."""

    staging_path = get_staging_path(data_directory)
    if not staging_path.exists():
        return {"changed": 0, "backup_path": None}
    records = read_staging(data_directory=data_directory)
    changed = 0
    for record in records:
        if record.get("source_id") != "greenhouse_job_board_api":
            continue
        description = record.get("description")
        if not isinstance(description, str):
            continue
        cleaned = clean_greenhouse_description(description)
        if cleaned == description:
            continue
        record["description"] = cleaned
        record["content_hash"] = calculate_content_hash(
            str(record.get("title", "")),
            str(record.get("company")) if record.get("company") else None,
            cleaned,
        )
        changed += 1
    if not changed:
        return {"changed": 0, "backup_path": None}

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = staging_path.with_name(
        f"pending-jobs.before-html-cleanup-{timestamp}.jsonl"
    )
    backup_path.write_bytes(staging_path.read_bytes())
    temporary_path = staging_path.with_suffix(".jsonl.tmp")
    temporary_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False) + "\n" for record in records
        ),
        encoding="utf-8",
        newline="\n",
    )
    temporary_path.replace(staging_path)
    return {"changed": changed, "backup_path": str(backup_path)}


@_synchronized
def resolve_staging_record(
    content_hash: str,
    *,
    decision: str,
    details: dict[str, object] | None = None,
    data_directory: Path | None = None,
) -> dict[str, Any]:
    """Resolve one pending record without physically deleting its audit trail."""

    if decision not in {"imported", "duplicate", "discarded"}:
        raise ValueError(f"不支持的暂存处理结果：{decision}")
    staging_path = get_staging_path(data_directory)
    records = read_staging(data_directory=data_directory)
    target = next(
        (
            record
            for record in records
            if record.get("content_hash") == content_hash
            and record.get("review_status") == "pending"
        ),
        None,
    )
    if target is None:
        raise KeyError("待确认采集记录不存在或已经处理")

    resolved_at = datetime.now(timezone.utc).isoformat()
    target["review_status"] = decision
    target["reviewed_at"] = resolved_at
    target["resolution"] = details or {}

    temporary_path = staging_path.with_suffix(".jsonl.tmp")
    temporary_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False) + "\n" for record in records
        ),
        encoding="utf-8",
        newline="\n",
    )
    temporary_path.replace(staging_path)

    event_path = staging_path.with_name("review-events.jsonl")
    with event_path.open("a", encoding="utf-8", newline="\n") as event_file:
        event_file.write(
            json.dumps(
                {
                    "content_hash": content_hash,
                    "decision": decision,
                    "resolved_at": resolved_at,
                    "details": details or {},
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return target
