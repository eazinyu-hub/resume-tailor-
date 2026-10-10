import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.storage import (
    JOB_METADATA_COLUMN_DEFINITIONS,
    JD_SAMPLE_SCHEMA_VERSION,
    add_job_metadata_columns,
    backfill_job_content_hashes,
    compute_job_content_hash,
    create_database_backup,
    create_job_analyses_schema,
    find_job_duplicate_candidates,
    migrate_jd_sample_schema,
    normalize_job_description,
    read_schema_version,
    save_batch_job_samples,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = REPOSITORY_ROOT / "work" / "test-storage"


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temporary_directory = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.test_root = Path(self.temporary_directory.name)
        self.database_path = self.test_root / "source.sqlite3"
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    source TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE resume_drafts (
                    job_id INTEGER PRIMARY KEY,
                    content_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                )
                """
            )
            connection.executemany(
                "INSERT INTO jobs (title, description, source) VALUES (?, ?, ?)",
                [
                    ("岗位一", "第一份原始 JD", "手动导入"),
                    ("岗位二", "第二份原始 JD", "手动导入"),
                ],
            )
            connection.execute(
                "INSERT INTO resume_drafts (job_id, content_json) VALUES (?, ?)",
                (1, '{"jobTitle": "岗位一"}'),
            )
            connection.execute("PRAGMA user_version = 3")
            connection.commit()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_reads_schema_version_without_modifying_database(self) -> None:
        modified_at = self.database_path.stat().st_mtime_ns

        self.assertEqual(read_schema_version(self.database_path), 3)
        self.assertEqual(self.database_path.stat().st_mtime_ns, modified_at)

    def test_missing_database_is_not_created(self) -> None:
        missing_path = self.test_root / "missing.sqlite3"

        with self.assertRaises(FileNotFoundError):
            read_schema_version(missing_path)

        self.assertFalse(missing_path.exists())

    def test_creates_complete_backup_without_changing_source(self) -> None:
        source_modified_at = self.database_path.stat().st_mtime_ns
        backup_directory = self.test_root / "backups"

        backup_path = create_database_backup(self.database_path, backup_directory)

        self.assertTrue(backup_path.is_file())
        self.assertEqual(backup_path.parent, backup_directory.resolve())
        self.assertIn("before-schema-v3", backup_path.name)
        self.assertEqual(self.database_path.stat().st_mtime_ns, source_modified_at)
        self.assertEqual(read_schema_version(backup_path), 3)
        with closing(sqlite3.connect(backup_path)) as connection:
            job_count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            integrity_result = connection.execute("PRAGMA integrity_check").fetchone()
        self.assertEqual(job_count, 2)
        self.assertEqual(integrity_result, ("ok",))

    def test_adds_job_metadata_without_changing_existing_data(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            jobs_before = connection.execute(
                "SELECT id, title, description, source, created_at FROM jobs ORDER BY id"
            ).fetchall()
            drafts_before = connection.execute(
                "SELECT job_id, content_json, updated_at FROM resume_drafts ORDER BY job_id"
            ).fetchall()

        added_columns = add_job_metadata_columns(self.database_path)

        self.assertEqual(added_columns, tuple(JOB_METADATA_COLUMN_DEFINITIONS))
        self.assertEqual(read_schema_version(self.database_path), 3)
        with closing(sqlite3.connect(self.database_path)) as connection:
            column_names = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)")
            }
            jobs_after = connection.execute(
                "SELECT id, title, description, source, created_at FROM jobs ORDER BY id"
            ).fetchall()
            metadata = connection.execute(
                "SELECT content_hash, duplicate_of, sample_status FROM jobs ORDER BY id"
            ).fetchall()
            drafts_after = connection.execute(
                "SELECT job_id, content_json, updated_at FROM resume_drafts ORDER BY job_id"
            ).fetchall()
            integrity_result = connection.execute("PRAGMA integrity_check").fetchone()

        self.assertTrue(set(JOB_METADATA_COLUMN_DEFINITIONS).issubset(column_names))
        self.assertEqual(jobs_after, jobs_before)
        self.assertEqual(drafts_after, drafts_before)
        self.assertEqual(metadata, [(None, None, "active"), (None, None, "active")])
        self.assertEqual(integrity_result, ("ok",))

    def test_adding_job_metadata_is_idempotent(self) -> None:
        first_result = add_job_metadata_columns(self.database_path)
        second_result = add_job_metadata_columns(self.database_path)

        self.assertEqual(first_result, tuple(JOB_METADATA_COLUMN_DEFINITIONS))
        self.assertEqual(second_result, ())

    def test_creates_job_analyses_schema_without_changing_existing_data(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            jobs_before = connection.execute("SELECT * FROM jobs ORDER BY id").fetchall()
            drafts_before = connection.execute(
                "SELECT * FROM resume_drafts ORDER BY job_id"
            ).fetchall()

        created = create_job_analyses_schema(self.database_path)

        self.assertTrue(created)
        self.assertEqual(read_schema_version(self.database_path), 3)
        with closing(sqlite3.connect(self.database_path)) as connection:
            jobs_after = connection.execute("SELECT * FROM jobs ORDER BY id").fetchall()
            drafts_after = connection.execute(
                "SELECT * FROM resume_drafts ORDER BY job_id"
            ).fetchall()
            analysis_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(job_analyses)")
            }
            analysis_indexes = {
                str(row[1]) for row in connection.execute("PRAGMA index_list(job_analyses)")
            }
            integrity_result = connection.execute("PRAGMA integrity_check").fetchone()

        self.assertEqual(jobs_after, jobs_before)
        self.assertEqual(drafts_after, drafts_before)
        self.assertEqual(
            analysis_columns,
            {
                "id",
                "job_id",
                "role_family",
                "content_json",
                "analysis_status",
                "analyzer_version",
                "is_current",
                "supersedes_analysis_id",
                "created_at",
                "updated_at",
                "confirmed_at",
            },
        )
        self.assertTrue(
            {
                "idx_job_analyses_job_id",
                "idx_job_analyses_role_family",
                "ux_job_analyses_current",
            }.issubset(analysis_indexes)
        )
        self.assertEqual(integrity_result, ("ok",))

    def test_creating_job_analyses_schema_is_idempotent(self) -> None:
        self.assertTrue(create_job_analyses_schema(self.database_path))
        self.assertFalse(create_job_analyses_schema(self.database_path))

    def test_job_analyses_constraints_protect_versions_and_relations(self) -> None:
        create_job_analyses_schema(self.database_path)

        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO job_analyses (job_id, role_family, content_json)
                VALUES (?, ?, ?)
                """,
                (1, "vibe_coding_fullstack", "{}"),
            )
            connection.commit()

            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO job_analyses (job_id, content_json) VALUES (?, ?)",
                    (1, "{}"),
                )
                connection.commit()
            connection.rollback()

            connection.execute(
                """
                INSERT INTO job_analyses (job_id, content_json, is_current)
                VALUES (?, ?, 0)
                """,
                (1, "{}"),
            )
            connection.commit()

            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO job_analyses (job_id, content_json) VALUES (?, ?)",
                    (999, "{}"),
                )
                connection.commit()
            connection.rollback()

            version_count = connection.execute(
                "SELECT COUNT(*) FROM job_analyses WHERE job_id = 1"
            ).fetchone()[0]
        self.assertEqual(version_count, 2)

    def test_normalizes_job_description_only_for_fingerprinting(self) -> None:
        first_description = "第一份原始 JD"
        differently_spaced = "  第一份原始   JD\r\n"

        self.assertEqual(
            normalize_job_description(differently_spaced),
            first_description,
        )
        self.assertEqual(
            compute_job_content_hash(differently_spaced),
            compute_job_content_hash(first_description),
        )

    def test_backfills_hashes_and_marks_exact_duplicates_without_deleting(self) -> None:
        add_job_metadata_columns(self.database_path)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "INSERT INTO jobs (title, description, source) VALUES (?, ?, ?)",
                ("岗位一的重复发布", "  第一份原始   JD\r\n", "手动导入"),
            )
            connection.execute(
                "INSERT INTO jobs (title, description, source) VALUES (?, ?, ?)",
                ("无有效正文", " \r\n\t ", "手动导入"),
            )
            connection.commit()
            original_rows = connection.execute(
                "SELECT id, title, description, source, created_at FROM jobs ORDER BY id"
            ).fetchall()
            original_drafts = connection.execute(
                "SELECT * FROM resume_drafts ORDER BY job_id"
            ).fetchall()

        first_summary = backfill_job_content_hashes(self.database_path)

        with closing(sqlite3.connect(self.database_path)) as connection:
            migrated_rows = connection.execute(
                """
                SELECT id, title, description, source, created_at,
                       content_hash, duplicate_of, sample_status
                FROM jobs ORDER BY id
                """
            ).fetchall()
            migrated_drafts = connection.execute(
                "SELECT * FROM resume_drafts ORDER BY job_id"
            ).fetchall()
            integrity_result = connection.execute("PRAGMA integrity_check").fetchone()

        self.assertEqual(
            first_summary,
            {"processed": 4, "active": 2, "duplicates": 1, "invalid": 1},
        )
        self.assertEqual([row[:5] for row in migrated_rows], original_rows)
        self.assertEqual(migrated_drafts, original_drafts)
        self.assertTrue(all(len(row[5]) == 64 for row in migrated_rows))
        self.assertEqual(migrated_rows[0][6:], (None, "active"))
        self.assertEqual(migrated_rows[1][6:], (None, "active"))
        self.assertEqual(migrated_rows[2][6:], (1, "duplicate"))
        self.assertEqual(migrated_rows[3][6:], (None, "invalid"))
        self.assertEqual(migrated_rows[0][5], migrated_rows[2][5])
        self.assertEqual(integrity_result, ("ok",))

        second_summary = backfill_job_content_hashes(self.database_path)
        with closing(sqlite3.connect(self.database_path)) as connection:
            second_rows = connection.execute(
                """
                SELECT content_hash, duplicate_of, sample_status
                FROM jobs ORDER BY id
                """
            ).fetchall()
        self.assertEqual(second_summary, first_summary)
        self.assertEqual(second_rows, [row[5:] for row in migrated_rows])

    def test_migrates_complete_schema_after_backup_and_preserves_legacy_data(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("PRAGMA user_version = 0")
            connection.execute(
                "INSERT INTO jobs (title, description, source) VALUES (?, ?, ?)",
                ("岗位一重复", "第一份原始   JD", "手动导入"),
            )
            connection.commit()
            jobs_before = connection.execute(
                "SELECT id, title, description, source, created_at FROM jobs ORDER BY id"
            ).fetchall()
            drafts_before = connection.execute(
                "SELECT job_id, content_json, updated_at FROM resume_drafts ORDER BY job_id"
            ).fetchall()

        backup_directory = self.test_root / "migration-backups"
        report = migrate_jd_sample_schema(self.database_path, backup_directory)

        self.assertEqual(report["status"], "migrated")
        self.assertEqual(report["previous_version"], 0)
        self.assertEqual(report["current_version"], JD_SAMPLE_SCHEMA_VERSION)
        self.assertEqual(report["jobs_preserved"], 3)
        self.assertEqual(report["resume_drafts_preserved"], 1)
        self.assertEqual(report["fingerprints"]["duplicates"], 1)
        backup_path = Path(str(report["backup_path"]))
        self.assertTrue(backup_path.is_file())
        self.assertEqual(read_schema_version(backup_path), 0)
        self.assertEqual(read_schema_version(self.database_path), JD_SAMPLE_SCHEMA_VERSION)

        with closing(sqlite3.connect(self.database_path)) as connection:
            jobs_after = connection.execute(
                "SELECT id, title, description, source, created_at FROM jobs ORDER BY id"
            ).fetchall()
            drafts_after = connection.execute(
                "SELECT job_id, content_json, updated_at FROM resume_drafts ORDER BY job_id"
            ).fetchall()
            duplicate_row = connection.execute(
                "SELECT duplicate_of, sample_status FROM jobs WHERE id = 3"
            ).fetchone()
            analyses_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'job_analyses'"
            ).fetchone()

        self.assertEqual(jobs_after, jobs_before)
        self.assertEqual(drafts_after, drafts_before)
        self.assertEqual(duplicate_row, (1, "duplicate"))
        self.assertIsNotNone(analyses_table)

        backups_before_second_run = list(backup_directory.glob("*.sqlite3"))
        second_report = migrate_jd_sample_schema(self.database_path, backup_directory)
        backups_after_second_run = list(backup_directory.glob("*.sqlite3"))
        self.assertEqual(second_report["status"], "already_current")
        self.assertEqual(backups_after_second_run, backups_before_second_run)

    def test_saves_batch_atomically_and_skips_exact_duplicates(self) -> None:
        add_job_metadata_columns(self.database_path)
        create_job_analyses_schema(self.database_path)
        with closing(sqlite3.connect(self.database_path)) as connection:
            cursor = connection.execute(
                "INSERT INTO jobs (title, description) VALUES (?, ?)",
                ("已有岗位", "开发内部工具。"),
            )
            existing_id = int(cursor.lastrowid)
            jobs_before = connection.execute(
                "SELECT title, description, sample_status FROM jobs ORDER BY id"
            ).fetchall()
            connection.commit()
        backfill_job_content_hashes(self.database_path)

        result = save_batch_job_samples(self.database_path, [
            {"title": "重复岗位", "description": "开发内部工具。"},
            {"title": "Agent开发", "description": "开发智能体工作流。"},
        ])

        self.assertEqual(result["received"], 2)
        self.assertEqual(result["saved"], 1)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["items"][0]["duplicate_of"], existing_id)
        with closing(sqlite3.connect(self.database_path)) as connection:
            jobs = connection.execute(
                "SELECT title, description, sample_status FROM jobs ORDER BY id"
            ).fetchall()
            analyses = connection.execute(
                "SELECT job_id, analysis_status, content_json FROM job_analyses"
            ).fetchall()
        self.assertEqual(jobs, [
            *jobs_before,
            ("Agent开发", "开发智能体工作流。", "active"),
        ])
        self.assertEqual(analyses, [(existing_id + 1, "pending", "{}")])

    def test_rolls_back_entire_batch_when_one_item_fails(self) -> None:
        add_job_metadata_columns(self.database_path)
        create_job_analyses_schema(self.database_path)

        with self.assertRaises(KeyError):
            save_batch_job_samples(self.database_path, [
                {"title": "有效岗位", "description": "有效正文。"},
                {"title": "损坏岗位"},
            ])

        with closing(sqlite3.connect(self.database_path)) as connection:
            job_count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            analysis_count = connection.execute(
                "SELECT COUNT(*) FROM job_analyses"
            ).fetchone()[0]
        self.assertEqual(job_count, 2)
        self.assertEqual(analysis_count, 0)

    def test_classifies_four_duplicate_candidate_types(self) -> None:
        add_job_metadata_columns(self.database_path)
        base_description = "负责AI工具开发、调试、部署与验证，持续优化内部业务流程。"
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "INSERT INTO jobs (title, description, company) VALUES (?, ?, ?)",
                ("AI工具开发", base_description, "示例公司"),
            )
            connection.commit()

        candidates = find_job_duplicate_candidates(self.database_path, [
            {"title": "AI工具开发", "description": base_description, "company": "示例公司"},
            {"title": "AI开发工程师", "description": base_description, "company": "示例公司"},
            {"title": "AI工具开发", "description": base_description.replace("持续优化", "协同优化"), "company": "示例公司"},
            {"title": "AI应用开发", "description": base_description.replace("持续优化", "不断优化"), "company": "另一家公司"},
        ])

        self.assertEqual([item["category"] for item in candidates], ["exact", "same_body", "same_company", "near"])


if __name__ == "__main__":
    unittest.main()
