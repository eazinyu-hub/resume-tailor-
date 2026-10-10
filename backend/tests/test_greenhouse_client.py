import json
import unittest
from unittest.mock import patch

from collector.greenhouse_client import (
    GreenhouseRequestError,
    fetch_public_job,
)


class _FakeResponse:
    def __init__(self, payload: dict, final_url: str) -> None:
        self.body = json.dumps(payload).encode("utf-8")
        self.final_url = final_url
        self.headers = {"Content-Length": str(len(self.body))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback

    def geturl(self) -> str:
        return self.final_url

    def read(self, size: int) -> bytes:
        return self.body[:size]


class GreenhouseClientTests(unittest.TestCase):
    @patch("collector.greenhouse_client.urlopen")
    def test_reads_one_allowlisted_public_job(self, mocked_urlopen) -> None:
        endpoint = (
            "https://boards-api.greenhouse.io/v1/boards/"
            "anthropic/jobs/4981828008"
        )
        mocked_urlopen.return_value = _FakeResponse(
            {
                "id": 4981828008,
                "title": "Software Engineer, Research Tools",
                "updated_at": "2026-09-15T00:00:00Z",
                "location": {"name": "San Francisco, CA"},
                "absolute_url": (
                    "https://job-boards.greenhouse.io/anthropic/"
                    "jobs/4981828008"
                ),
                "content": "<p>Build tools for AI researchers.</p>",
            },
            endpoint,
        )

        job = fetch_public_job(
            board_id="anthropic",
            job_id="4981828008",
        )

        self.assertEqual(job.company, "Anthropic")
        self.assertEqual(job.source_job_id, "4981828008")
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, endpoint)
        self.assertEqual(request.get_method(), "GET")
        self.assertNotIn("Authorization", dict(request.header_items()))

    def test_rejects_unreviewed_board_before_network_access(self) -> None:
        with patch("collector.greenhouse_client.urlopen") as mocked_urlopen:
            with self.assertRaisesRegex(ValueError, "未审核"):
                fetch_public_job(board_id="unknown", job_id="1")
            mocked_urlopen.assert_not_called()

    def test_rejects_non_numeric_job_id_before_network_access(self) -> None:
        with patch("collector.greenhouse_client.urlopen") as mocked_urlopen:
            with self.assertRaisesRegex(GreenhouseRequestError, "数字"):
                fetch_public_job(board_id="anthropic", job_id="../all")
            mocked_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
