import json
import unittest
from unittest.mock import patch

from collector.lever_client import LeverRequestError, fetch_public_posting


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


class LeverClientTests(unittest.TestCase):
    @patch("collector.lever_client.urlopen")
    def test_reads_one_allowlisted_public_posting(self, mocked_urlopen) -> None:
        posting_id = "26491a9f-ac14-4f12-a1ff-a2b96bf0356e"
        endpoint = (
            "https://api.lever.co/v0/postings/kgroupcompanies/"
            f"{posting_id}?mode=json"
        )
        mocked_urlopen.return_value = _FakeResponse(
            {
                "id": posting_id,
                "text": "Junior AI Engineer",
                "hostedUrl": (
                    "https://jobs.lever.co/kgroupcompanies/" + posting_id
                ),
                "descriptionPlain": "Build AI workflows.",
            },
            endpoint,
        )

        job = fetch_public_posting(
            site_id="kgroupcompanies",
            posting_id=posting_id,
        )

        self.assertEqual(job.company, "K Group Companies")
        self.assertEqual(job.source_job_id, posting_id)
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, endpoint)
        self.assertNotIn("Authorization", dict(request.header_items()))

    def test_rejects_unreviewed_site_before_network_access(self) -> None:
        with patch("collector.lever_client.urlopen") as mocked_urlopen:
            with self.assertRaisesRegex(ValueError, "未审核"):
                fetch_public_posting(
                    site_id="unknown",
                    posting_id="26491a9f-ac14-4f12-a1ff-a2b96bf0356e",
                )
            mocked_urlopen.assert_not_called()

    def test_rejects_invalid_posting_id_before_network_access(self) -> None:
        with patch("collector.lever_client.urlopen") as mocked_urlopen:
            with self.assertRaisesRegex(LeverRequestError, "UUID"):
                fetch_public_posting(
                    site_id="kgroupcompanies",
                    posting_id="../all",
                )
            mocked_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
