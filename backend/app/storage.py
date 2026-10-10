import hashlib
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


JOB_METADATA_COLUMN_DEFINITIONS = {
    "company": "TEXT",
    "source_url": "TEXT",
    "published_at": "TEXT",
    "city": "TEXT",
    "salary": "TEXT",
    "content_hash": "TEXT",
    "duplicate_of": "INTEGER REFERENCES jobs(id)",
    "sample_status": (
        "TEXT NOT NULL DEFAULT 'active' "
        "CHECK (sample_status IN ('active', 'duplicate', 'invalid'))"
    ),
    "updated_at": "TEXT",
}

ROLE_FAMILIES = (
    "ai_tool_automation",
    "vibe_coding_fullstack",
    "agent_application",
    "ai_product_operations",
    "internal_intelligence",
    "indie_ai_developer",
)

ANALYSIS_STATUSES = ("pending", "generated", "confirmed", "failed")
JD_SAMPLE_SCHEMA_VERSION = 1


def _quoted_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


JOB_ANALYSES_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS job_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    role_family TEXT CHECK (
        role_family IS NULL OR role_family IN ({_quoted_values(ROLE_FAMILIES)})
    ),
    content_json TEXT NOT NULL DEFAULT '{{}}',
    analysis_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        analysis_status IN ({_quoted_values(ANALYSIS_STATUSES)})
    ),
    analyzer_version TEXT,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    supersedes_analysis_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id),
    FOREIGN KEY (supersedes_analysis_id) REFERENCES job_analyses(id)
)
"""

JOB_ANALYSES_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_job_analyses_job_id ON job_analyses(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_job_analyses_role_family ON job_analyses(role_family)",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_job_analyses_current
    ON job_analyses(job_id) WHERE is_current = 1
    """,
)


def read_schema_version(database_path: Path) -> int:
    """Read SQLite's user_version without creating a missing database file."""
    resolved_path = database_path.resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {resolved_path}")

    database_uri = f"{resolved_path.as_uri()}?mode=ro"
    with closing(sqlite3.connect(database_uri, uri=True)) as connection:
        row = connection.execute("PRAGMA user_version").fetchone()
    if row is None:
        raise RuntimeError(f"Unable to read schema version: {resolved_path}")
    return int(row[0])


def create_database_backup(database_path: Path, backup_directory: Path) -> Path:
    """Create and integrity-check a consistent SQLite backup."""
    resolved_database = database_path.resolve()
    if not resolved_database.is_file():
        raise FileNotFoundError(f"Database does not exist: {resolved_database}")

    resolved_backup_directory = backup_directory.resolve()
    resolved_backup_directory.mkdir(parents=True, exist_ok=True)
    schema_version = read_schema_version(resolved_database)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = resolved_backup_directory / (
        f"{resolved_database.stem}-before-schema-v{schema_version}-{timestamp}.sqlite3"
    )

    try:
        with closing(sqlite3.connect(resolved_database)) as source:
            with closing(sqlite3.connect(backup_path)) as destination:
                source.backup(destination)
                integrity_result = destination.execute("PRAGMA integrity_check").fetchone()
                if integrity_result != ("ok",):
                    raise RuntimeError(
                        f"Backup integrity check failed: {integrity_result!r}"
                    )
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise

    return backup_path


def add_job_metadata_columns(database_path: Path) -> tuple[str, ...]:
    """Add missing V1 metadata columns to a legacy jobs table."""
    resolved_database = database_path.resolve()
    if not resolved_database.is_file():
        raise FileNotFoundError(f"Database does not exist: {resolved_database}")

    added_columns: list[str] = []
    with closing(sqlite3.connect(resolved_database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
        ).fetchone()
        if table_exists is None:
            raise RuntimeError("Cannot add job metadata: jobs table does not exist")

        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)")
            }
            for column_name, definition in JOB_METADATA_COLUMN_DEFINITIONS.items():
                if column_name in existing_columns:
                    continue
                connection.execute(
                    f'ALTER TABLE jobs ADD COLUMN "{column_name}" {definition}'
                )
                added_columns.append(column_name)

            integrity_result = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity_result != ("ok",):
                raise RuntimeError(
                    f"Database integrity check failed after adding metadata: {integrity_result!r}"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return tuple(added_columns)


def create_job_analyses_schema(database_path: Path) -> bool:
    """Create the versioned JD analysis table and its indexes if missing."""
    resolved_database = database_path.resolve()
    if not resolved_database.is_file():
        raise FileNotFoundError(f"Database does not exist: {resolved_database}")

    with closing(sqlite3.connect(resolved_database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        jobs_table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
        ).fetchone()
        if jobs_table_exists is None:
            raise RuntimeError("Cannot create job analyses: jobs table does not exist")

        analysis_table_existed = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'job_analyses'"
        ).fetchone() is not None
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(JOB_ANALYSES_TABLE_SQL)
            for index_sql in JOB_ANALYSES_INDEX_SQL:
                connection.execute(index_sql)

            integrity_result = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity_result != ("ok",):
                raise RuntimeError(
                    f"Database integrity check failed after creating analyses: {integrity_result!r}"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return not analysis_table_existed


def normalize_job_description(description: str) -> str:
    """Normalize whitespace for fingerprinting without changing stored JD text."""
    normalized_newlines = description.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", normalized_newlines).strip()


def compute_job_content_hash(description: str) -> str:
    normalized_description = normalize_job_description(description)
    return hashlib.sha256(normalized_description.encode("utf-8")).hexdigest()


def _normalize_duplicate_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _character_bigrams(text: str) -> set[str]:
    normalized = _normalize_duplicate_text(text)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def _text_similarity(left: str, right: str) -> float:
    left_tokens = _character_bigrams(left)
    right_tokens = _character_bigrams(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def find_job_duplicate_candidates(
    database_path: Path,
    jobs: list[dict[str, str]],
    near_duplicate_threshold: float = 0.75,
) -> list[dict[str, object]]:
    """Classify incoming jobs against stored samples without writing data."""
    with closing(sqlite3.connect(database_path.resolve())) as connection:
        connection.row_factory = sqlite3.Row
        existing_jobs = [dict(row) for row in connection.execute("SELECT id, title, description, company FROM jobs")]

    candidates: list[dict[str, object]] = []
    for position, job in enumerate(jobs, start=1):
        title = job.get("title", "").strip()
        description = job.get("description", "").strip()
        company = job.get("company", "").strip()
        normalized_title = _normalize_duplicate_text(title)
        normalized_description = _normalize_duplicate_text(description)
        best: dict[str, object] | None = None
        for existing in existing_jobs:
            existing_title = str(existing["title"])
            existing_description = str(existing["description"])
            similarity = _text_similarity(description, existing_description)
            category: str | None = None
            if normalized_description and normalized_description == _normalize_duplicate_text(existing_description):
                category = "exact" if normalized_title == _normalize_duplicate_text(existing_title) else "same_body"
                similarity = 1.0
            elif company and company == (existing.get("company") or "").strip() and (normalized_title == _normalize_duplicate_text(existing_title) or similarity >= 0.5):
                category = "same_company"
            elif similarity >= near_duplicate_threshold:
                category = "near"
            if category is None:
                continue
            priority = {"exact": 4, "same_body": 3, "same_company": 2, "near": 1}[category]
            if best is None or priority > int(best["priority"]) or (priority == int(best["priority"]) and similarity > float(best["similarity"])):
                best = {"priority": priority, "category": category, "similarity": similarity, "existing_id": existing["id"], "existing_title": existing_title}
        if best is not None:
            candidates.append({"position": position, "category": best["category"], "similarity": round(float(best["similarity"]) * 100), "existing_id": best["existing_id"], "existing_title": best["existing_title"]})
    return candidates


def backfill_job_content_hashes(database_path: Path) -> dict[str, int]:
    """Fingerprint legacy JDs and mark exact duplicates without deleting rows."""
    resolved_database = database_path.resolve()
    if not resolved_database.is_file():
        raise FileNotFoundError(f"Database does not exist: {resolved_database}")

    with closing(sqlite3.connect(resolved_database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        existing_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)")
        }
        required_columns = {"content_hash", "duplicate_of", "sample_status"}
        missing_columns = required_columns - existing_columns
        if missing_columns:
            missing_text = ", ".join(sorted(missing_columns))
            raise RuntimeError(f"Cannot fingerprint jobs; missing columns: {missing_text}")

        rows = connection.execute(
            "SELECT id, description, sample_status FROM jobs ORDER BY id"
        ).fetchall()
        seen_hashes: dict[str, int] = {}
        summary = {"processed": 0, "active": 0, "duplicates": 0, "invalid": 0}

        try:
            connection.execute("BEGIN IMMEDIATE")
            for job_id, description, current_status in rows:
                original_description = str(description)
                normalized_description = normalize_job_description(original_description)
                content_hash = compute_job_content_hash(original_description)

                if current_status == "invalid" or not normalized_description:
                    sample_status = "invalid"
                    duplicate_of = None
                    summary["invalid"] += 1
                elif content_hash in seen_hashes:
                    sample_status = "duplicate"
                    duplicate_of = seen_hashes[content_hash]
                    summary["duplicates"] += 1
                else:
                    seen_hashes[content_hash] = int(job_id)
                    sample_status = "active"
                    duplicate_of = None
                    summary["active"] += 1

                connection.execute(
                    """
                    UPDATE jobs
                    SET content_hash = ?, duplicate_of = ?, sample_status = ?
                    WHERE id = ?
                    """,
                    (content_hash, duplicate_of, sample_status, job_id),
                )
                summary["processed"] += 1

            integrity_result = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity_result != ("ok",):
                raise RuntimeError(
                    f"Database integrity check failed after fingerprinting: {integrity_result!r}"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return summary


def save_batch_job_samples(
    database_path: Path,
    jobs: list[dict[str, str]],
    source: str = "manual",
) -> dict[str, object]:
    """Save one parsed JD batch atomically and skip exact-content duplicates."""
    resolved_database = database_path.resolve()
    if not resolved_database.is_file():
        raise FileNotFoundError(f"Database does not exist: {resolved_database}")

    results: list[dict[str, object]] = []
    saved_count = 0
    duplicate_count = 0
    with closing(sqlite3.connect(resolved_database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            for position, job in enumerate(jobs, start=1):
                title = job["title"].strip()
                description = job["description"].strip()
                content_hash = compute_job_content_hash(description)
                existing = connection.execute(
                    """
                    SELECT id FROM jobs
                    WHERE content_hash = ?
                    ORDER BY CASE sample_status WHEN 'active' THEN 0 ELSE 1 END, id
                    LIMIT 1
                    """,
                    (content_hash,),
                ).fetchone()
                if existing is not None:
                    duplicate_count += 1
                    results.append({
                        "position": position,
                        "title": title,
                        "status": "duplicate",
                        "duplicate_of": int(existing[0]),
                    })
                    continue

                cursor = connection.execute(
                    """
                    INSERT INTO jobs (
                        title, description, source, content_hash,
                        sample_status, updated_at
                    ) VALUES (?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
                    """,
                    (title, description, source, content_hash),
                )
                job_id = int(cursor.lastrowid)
                connection.execute(
                    """
                    INSERT INTO job_analyses (job_id, analysis_status, content_json)
                    VALUES (?, 'pending', '{}')
                    """,
                    (job_id,),
                )
                saved_count += 1
                results.append({
                    "position": position,
                    "title": title,
                    "status": "saved",
                    "id": job_id,
                })
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return {
        "received": len(jobs),
        "saved": saved_count,
        "duplicates": duplicate_count,
        "items": results,
    }


def save_csv_job_samples(database_path: Path, jobs: list[dict[str, str]]) -> dict[str, object]:
    """Save mapped CSV rows atomically and retain their available source metadata."""
    resolved_database = database_path.resolve()
    if not resolved_database.is_file():
        raise FileNotFoundError(f"Database does not exist: {resolved_database}")

    results: list[dict[str, object]] = []
    saved_count = 0
    duplicate_count = 0
    with closing(sqlite3.connect(resolved_database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            for position, job in enumerate(jobs, start=1):
                title = job["title"].strip()
                description = job["description"].strip()
                content_hash = compute_job_content_hash(description)
                existing = connection.execute(
                    """
                    SELECT id FROM jobs
                    WHERE content_hash = ?
                    ORDER BY CASE sample_status WHEN 'active' THEN 0 ELSE 1 END, id
                    LIMIT 1
                    """,
                    (content_hash,),
                ).fetchone()
                if existing is not None:
                    duplicate_count += 1
                    results.append({"position": position, "title": title, "status": "duplicate", "duplicate_of": int(existing[0])})
                    continue

                cursor = connection.execute(
                    """
                    INSERT INTO jobs (
                        title, description, source, company, source_url,
                        published_at, city, salary, content_hash,
                        sample_status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
                    """,
                    (
                        title,
                        description,
                        job.get("source") or "csv",
                        job.get("company") or None,
                        job.get("source_url") or None,
                        job.get("published_at") or None,
                        job.get("city") or None,
                        job.get("salary") or None,
                        content_hash,
                    ),
                )
                job_id = int(cursor.lastrowid)
                connection.execute(
                    """
                    INSERT INTO job_analyses (job_id, analysis_status, content_json)
                    VALUES (?, 'pending', '{}')
                    """,
                    (job_id,),
                )
                saved_count += 1
                results.append({"position": position, "title": title, "status": "saved", "id": job_id})
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return {"received": len(jobs), "saved": saved_count, "duplicates": duplicate_count, "items": results}


def _read_legacy_data_snapshot(database_path: Path) -> dict[str, list[tuple[object, ...]]]:
    with closing(sqlite3.connect(database_path)) as connection:
        jobs = connection.execute(
            "SELECT id, title, description, source, created_at FROM jobs ORDER BY id"
        ).fetchall()
        drafts_table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'resume_drafts'"
        ).fetchone() is not None
        drafts = (
            connection.execute(
                "SELECT job_id, content_json, updated_at FROM resume_drafts ORDER BY job_id"
            ).fetchall()
            if drafts_table_exists
            else []
        )
    return {"jobs": jobs, "resume_drafts": drafts}


def migrate_jd_sample_schema(
    database_path: Path,
    backup_directory: Path,
) -> dict[str, object]:
    """Back up and migrate one database to the complete V1 JD sample schema."""
    resolved_database = database_path.resolve()
    previous_version = read_schema_version(resolved_database)
    if previous_version > JD_SAMPLE_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema v{previous_version} is newer than supported "
            f"v{JD_SAMPLE_SCHEMA_VERSION}"
        )
    if previous_version == JD_SAMPLE_SCHEMA_VERSION:
        return {
            "status": "already_current",
            "previous_version": previous_version,
            "current_version": previous_version,
            "backup_path": None,
        }

    snapshot_before = _read_legacy_data_snapshot(resolved_database)
    backup_path = create_database_backup(resolved_database, backup_directory)
    added_columns = add_job_metadata_columns(resolved_database)
    analysis_table_created = create_job_analyses_schema(resolved_database)
    fingerprint_summary = backfill_job_content_hashes(resolved_database)

    snapshot_after = _read_legacy_data_snapshot(resolved_database)
    if snapshot_after != snapshot_before:
        raise RuntimeError(
            "Legacy jobs or resume drafts changed during migration; restore the backup"
        )

    with closing(sqlite3.connect(resolved_database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity_result = connection.execute("PRAGMA integrity_check").fetchone()
        if foreign_key_errors:
            raise RuntimeError(
                f"Foreign key check failed after migration: {foreign_key_errors!r}"
            )
        if integrity_result != ("ok",):
            raise RuntimeError(
                f"Database integrity check failed after migration: {integrity_result!r}"
            )
        connection.execute(f"PRAGMA user_version = {JD_SAMPLE_SCHEMA_VERSION}")
        connection.commit()

    return {
        "status": "migrated",
        "previous_version": previous_version,
        "current_version": JD_SAMPLE_SCHEMA_VERSION,
        "backup_path": str(backup_path),
        "added_columns": list(added_columns),
        "analysis_table_created": analysis_table_created,
        "fingerprints": fingerprint_summary,
        "jobs_preserved": len(snapshot_after["jobs"]),
        "resume_drafts_preserved": len(snapshot_after["resume_drafts"]),
    }
