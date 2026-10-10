import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.storage import JD_SAMPLE_SCHEMA_VERSION


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_TEMP_ROOT = REPOSITORY_ROOT / "work" / "test-app-startup"


class AppStartupTests(unittest.TestCase):
    def test_startup_migrates_legacy_database_once(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary_directory:
            data_directory = Path(temporary_directory)
            database_path = data_directory / "runtime" / "app.sqlite3"
            database_path.parent.mkdir(parents=True)

            with closing(sqlite3.connect(database_path)) as connection:
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
                connection.execute(
                    "INSERT INTO jobs (title, description) VALUES (?, ?)",
                    ("测试岗位", "使用 AI 工具完成开发、调试和验证。"),
                )
                connection.execute(
                    "INSERT INTO resume_drafts (job_id, content_json) VALUES (?, ?)",
                    (1, '{"sections": {}}'),
                )
                connection.commit()

            environment = os.environ.copy()
            environment["DATA_DIR"] = str(data_directory)

            subprocess.run(
                [sys.executable, "-c", "import app.main"],
                cwd=BACKEND_ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            detail_result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json; from app.main import get_job; "
                        "print(json.dumps(get_job(1), ensure_ascii=False))"
                    ),
                ],
                cwd=BACKEND_ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            job_detail = json.loads(detail_result.stdout)

            with closing(sqlite3.connect(database_path)) as connection:
                schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
                jobs = connection.execute(
                    "SELECT title, description FROM jobs"
                ).fetchall()
                drafts = connection.execute(
                    "SELECT job_id, content_json FROM resume_drafts"
                ).fetchall()
                analysis_table = connection.execute(
                    """
                    SELECT COUNT(*) FROM sqlite_master
                    WHERE type = 'table' AND name = 'job_analyses'
                    """
                ).fetchone()[0]

            backup_directory = (
                data_directory / "backups" / "database-migrations"
            )
            self.assertEqual(schema_version, JD_SAMPLE_SCHEMA_VERSION)
            self.assertEqual(jobs, [("测试岗位", "使用 AI 工具完成开发、调试和验证。")])
            self.assertEqual(drafts, [(1, '{"sections": {}}')])
            self.assertEqual(analysis_table, 1)
            self.assertEqual(len(list(backup_directory.glob("*.sqlite3"))), 1)
            self.assertEqual(job_detail["title"], "测试岗位")
            self.assertEqual(
                job_detail["sample_card"]["raw"]["description_raw"],
                "使用 AI 工具完成开发、调试和验证。",
            )
            self.assertEqual(
                job_detail["sample_card"]["raw"]["sample_status"],
                "active",
            )
            self.assertIsNotNone(
                job_detail["sample_card"]["raw"]["content_hash"]
            )
            self.assertIsNone(job_detail["sample_card"]["analysis"])

    def test_manual_moka_staging_keeps_review_boundary_and_skips_duplicate(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary_directory:
            data_directory = Path(temporary_directory)
            environment = os.environ.copy()
            environment["DATA_DIR"] = str(data_directory)
            script = """
import json
from collector.models import CollectedJob
import app.main as main

main.fetch_public_job = lambda **_: CollectedJob(
    title="AI 工具开发工程师",
    company="测试企业",
    description="使用 Codex 和 Python 开发内部自动化工具。",
    source_id="moka_recruitment_api",
    source_job_id="11111111-1111-1111-1111-111111111111",
)
first = main.stage_deeproute_moka_job(
    "11111111-1111-1111-1111-111111111111"
)
second = main.stage_deeproute_moka_job(
    "11111111-1111-1111-1111-111111111111"
)
print(json.dumps({"first": first, "second": second}, ensure_ascii=False))
"""
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=BACKEND_ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            result = json.loads(completed.stdout)
            staging_path = (
                data_directory / "collector-staging" / "pending-jobs.jsonl"
            )
            records = [
                json.loads(line)
                for line in staging_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result["first"]["status"], "staged")
        self.assertEqual(result["second"]["status"], "already_collected")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["review_status"], "pending")


if __name__ == "__main__":
    unittest.main()
