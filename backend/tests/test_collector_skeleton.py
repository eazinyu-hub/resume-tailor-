import json
import tempfile
import unittest
from pathlib import Path

from collector.fetchers import (
    FetcherNotEnabled,
    FirecrawlFetcher,
    PlainHttpFetcher,
)
from collector.mock_source import collect_mock_job
from collector.models import CollectedJob
from collector.policy import get_source_policy, require_automated_collection
from collector.staging import (
    StagingReadError,
    append_to_staging,
    read_staging,
    repair_greenhouse_staging_html,
    resolve_staging_record,
    stage_unique_jobs,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = REPOSITORY_ROOT / "work" / "test-collector"


class CollectorSkeletonTests(unittest.TestCase):
    def test_boss_is_manual_only_and_rejected_for_automation(self) -> None:
        policy = get_source_policy("boss_zhipin")

        self.assertEqual(policy.status, "manual_only")
        with self.assertRaises(PermissionError):
            require_automated_collection("boss_zhipin")

    def test_mock_job_is_written_to_isolated_jsonl_staging(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary_directory:
            staging_path = append_to_staging(
                [collect_mock_job()],
                data_directory=Path(temporary_directory),
            )

            self.assertEqual(
                staging_path.name,
                "pending-jobs.jsonl",
            )
            record = json.loads(staging_path.read_text(encoding="utf-8"))
            self.assertEqual(record["source_id"], "mock_local")
            self.assertEqual(record["review_status"], "pending")
            self.assertEqual(len(record["content_hash"]), 64)

    def test_network_fetchers_are_explicitly_disabled(self) -> None:
        for fetcher in (PlainHttpFetcher(), FirecrawlFetcher()):
            with self.assertRaises(FetcherNotEnabled):
                fetcher.fetch("https://example.com/jobs/1")

    def test_reads_staging_without_importing_or_changing_records(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary_directory:
            data_directory = Path(temporary_directory)
            append_to_staging([collect_mock_job()], data_directory=data_directory)

            records = read_staging(data_directory=data_directory)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["review_status"], "pending")
            self.assertEqual(records[0]["title"], "AI 工具开发（模拟岗位）")

    def test_skips_same_source_job_and_content_on_repeated_collection(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary_directory:
            data_directory = Path(temporary_directory)
            first = stage_unique_jobs(
                [collect_mock_job()], data_directory=data_directory
            )
            repeated = stage_unique_jobs(
                [collect_mock_job()], data_directory=data_directory
            )

            self.assertEqual(first.added_count, 1)
            self.assertEqual(repeated.skipped_count, 1)
            self.assertEqual(len(read_staging(data_directory=data_directory)), 1)
            events_path = first.path.with_name("collection-events.jsonl")
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events[-1]["event"], "duplicate_skipped")
            self.assertEqual(
                events[-1]["reason"], "same_source_job_and_content"
            )

    def test_keeps_changed_source_job_as_a_noticed_new_version(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary_directory:
            data_directory = Path(temporary_directory)
            original = CollectedJob(
                title="AI 工具工程师",
                company="示例公司",
                description="使用 Python 开发内部工具。",
                source_id="moka_recruitment_api",
                source_job_id="same-job-id",
            )
            changed = CollectedJob(
                title="AI 工具工程师",
                company="示例公司",
                description="使用 Python 和 Agent 开发内部工具。",
                source_id="moka_recruitment_api",
                source_job_id="same-job-id",
            )
            stage_unique_jobs([original], data_directory=data_directory)
            result = stage_unique_jobs([changed], data_directory=data_directory)
            records = read_staging(data_directory=data_directory)

            self.assertEqual(result.updated_count, 1)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[-1]["collection_status"], "updated_source")
            self.assertEqual(
                records[-1]["previous_content_hash"], records[0]["content_hash"]
            )
            self.assertIn("旧版本", records[-1]["collection_notice"])

    def test_rejects_broken_json_instead_of_hiding_it(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary_directory:
            data_directory = Path(temporary_directory)
            staging_path = data_directory / "collector-staging" / "pending-jobs.jsonl"
            staging_path.parent.mkdir(parents=True)
            staging_path.write_text("{broken", encoding="utf-8")

            with self.assertRaisesRegex(StagingReadError, "第 1 行"):
                read_staging(data_directory=data_directory)

    def test_repairs_escaped_greenhouse_html_with_backup(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary_directory:
            data_directory = Path(temporary_directory)
            staging_path = data_directory / "collector-staging" / "pending-jobs.jsonl"
            staging_path.parent.mkdir(parents=True)
            staging_path.write_text(
                json.dumps(
                    {
                        "title": "AI Tool Engineer",
                        "company": "Example",
                        "description": "&lt;p&gt;Build AI tools.&lt;/p&gt;",
                        "source_id": "greenhouse_job_board_api",
                        "content_hash": "old",
                        "review_status": "pending",
                    }
                ),
                encoding="utf-8",
            )

            result = repair_greenhouse_staging_html(
                data_directory=data_directory
            )
            repaired = read_staging(data_directory=data_directory)[0]

            self.assertEqual(result["changed"], 1)
            self.assertTrue(Path(str(result["backup_path"])).is_file())
            self.assertEqual(repaired["description"], "Build AI tools.")
            self.assertNotEqual(repaired["content_hash"], "old")

    def test_discard_keeps_record_and_writes_review_event(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary_directory:
            data_directory = Path(temporary_directory)
            staging_path = append_to_staging(
                [collect_mock_job()],
                data_directory=data_directory,
            )
            content_hash = read_staging(data_directory=data_directory)[0][
                "content_hash"
            ]

            resolved = resolve_staging_record(
                content_hash,
                decision="discarded",
                details={"reason": "test"},
                data_directory=data_directory,
            )

            self.assertEqual(resolved["review_status"], "discarded")
            self.assertTrue(staging_path.is_file())
            records = read_staging(data_directory=data_directory)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["review_status"], "discarded")
            event_path = staging_path.with_name("review-events.jsonl")
            event = json.loads(event_path.read_text(encoding="utf-8"))
            self.assertEqual(event["decision"], "discarded")

            with self.assertRaisesRegex(KeyError, "已经处理"):
                resolve_staging_record(
                    content_hash,
                    decision="discarded",
                    data_directory=data_directory,
                )


if __name__ == "__main__":
    unittest.main()
