import json
import tempfile
import unittest
from pathlib import Path

from collector.adapters.greenhouse import (
    GreenhousePayloadError,
    parse_greenhouse_job_board,
)
from collector.staging import append_to_staging


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPOSITORY_ROOT / "examples" / "collector" / "greenhouse-jobs.json"
)
TEST_TEMP_ROOT = REPOSITORY_ROOT / "work" / "test-greenhouse-adapter"


class GreenhouseAdapterTests(unittest.TestCase):
    def test_converts_official_shape_to_normalized_staging_record(self) -> None:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        jobs = parse_greenhouse_job_board(
            payload,
            board_token="example",
            company="示例公司",
        )

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "AI Application Engineer")
        self.assertEqual(jobs[0].company, "示例公司")
        self.assertEqual(jobs[0].source_job_id, "10001")
        self.assertEqual(jobs[0].source_updated_at, "2026-09-10T08:30:00Z")
        self.assertNotIn("<h2>", jobs[0].description)
        self.assertIn("Build internal AI tools", jobs[0].description)
        self.assertIn("Experience with Python and APIs.", jobs[0].description)

        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary_directory:
            staging_path = append_to_staging(
                jobs,
                data_directory=Path(temporary_directory),
            )
            record = json.loads(staging_path.read_text(encoding="utf-8"))

        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(record["review_status"], "pending")
        self.assertEqual(record["source_id"], "greenhouse_job_board_api")

    def test_requires_content_instead_of_silently_saving_empty_jd(self) -> None:
        payload = {
            "jobs": [
                {
                    "id": 1,
                    "title": "AI Engineer",
                    "absolute_url": "https://boards.greenhouse.io/example/jobs/1",
                }
            ]
        }

        with self.assertRaisesRegex(GreenhousePayloadError, "content"):
            parse_greenhouse_job_board(
                payload,
                board_token="example",
                company="示例公司",
            )

    def test_decodes_greenhouse_escaped_html_before_cleaning(self) -> None:
        jobs = parse_greenhouse_job_board(
            {
                "jobs": [
                    {
                        "id": 2,
                        "title": "AI Tool Engineer",
                        "content": (
                            "&lt;h2&gt;Responsibilities&lt;/h2&gt;"
                            "&lt;p&gt;Build AI tools &amp;amp; workflows.&lt;/p&gt;"
                        ),
                        "absolute_url": (
                            "https://boards.greenhouse.io/example/jobs/2"
                        ),
                    }
                ]
            },
            board_token="example",
            company="示例公司",
        )

        self.assertEqual(
            jobs[0].description,
            "Responsibilities\nBuild AI tools & workflows.",
        )
        self.assertNotIn("&lt;", jobs[0].description)
        self.assertNotIn("<p>", jobs[0].description)

    def test_rejects_invalid_board_token_and_non_https_job_url(self) -> None:
        with self.assertRaisesRegex(GreenhousePayloadError, "board_token"):
            parse_greenhouse_job_board(
                {"jobs": []},
                board_token="../private",
                company="示例公司",
            )

        payload = {
            "jobs": [
                {
                    "id": 1,
                    "title": "AI Engineer",
                    "content": "<p>Build AI tools.</p>",
                    "absolute_url": "http://example.test/jobs/1",
                }
            ]
        }
        with self.assertRaisesRegex(GreenhousePayloadError, "HTTPS"):
            parse_greenhouse_job_board(
                payload,
                board_token="example",
                company="示例公司",
            )


if __name__ == "__main__":
    unittest.main()
