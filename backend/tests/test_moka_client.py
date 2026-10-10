import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from collector.moka_client import (
    MokaRequestError,
    fetch_public_job,
    fetch_public_job_list,
    reset_request_state_for_tests,
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


class MokaClientTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_request_state_for_tests()

    @patch("collector.moka_client.urlopen")
    def test_reads_one_allowlisted_public_job(self, mocked_urlopen) -> None:
        posting_id = "57eddbd2-5e18-4b7f-b2b6-e9996a696724"
        endpoint = (
            "https://api.mokahr.com/api-platform/v1/jobs/deeproute/"
            + posting_id
        )
        mocked_urlopen.return_value = _FakeResponse(
            {
                "success": True,
                "id": posting_id,
                "title": "AI 研发效能工程师",
                "status": "open",
                "orgId": "deeproute",
                "description": "<p>开发 AI Agent。</p>",
            },
            endpoint,
        )

        job = fetch_public_job(
            organization_id="deeproute",
            posting_id=posting_id,
        )

        self.assertEqual(job.company, "深圳元戎启行科技有限公司")
        self.assertEqual(job.source_job_id, posting_id)
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, endpoint)
        self.assertNotIn("Authorization", dict(request.header_items()))

    def test_rejects_unreviewed_organization_before_network_access(self) -> None:
        with patch("collector.moka_client.urlopen") as mocked_urlopen:
            with self.assertRaisesRegex(ValueError, "未审核"):
                fetch_public_job(
                    organization_id="unknown",
                    posting_id="57eddbd2-5e18-4b7f-b2b6-e9996a696724",
                )
            mocked_urlopen.assert_not_called()

    def test_rejects_invalid_posting_id_before_network_access(self) -> None:
        with patch("collector.moka_client.urlopen") as mocked_urlopen:
            with self.assertRaisesRegex(MokaRequestError, "UUID"):
                fetch_public_job(
                    organization_id="deeproute",
                    posting_id="../all",
                )
            mocked_urlopen.assert_not_called()

    @patch("collector.moka_client.urlopen")
    def test_reads_one_controlled_page_of_open_jobs(self, mocked_urlopen) -> None:
        endpoint = (
            "https://api.mokahr.com/api-platform/v1/jobs/deeproute?"
            "mode=social&status=open&limit=20&offset=0&siteId=143885"
        )
        mocked_urlopen.return_value = _FakeResponse(
            {
                "code": 0,
                "total": 1,
                "jobs": [
                    {
                        "id": "57eddbd2-5e18-4b7f-b2b6-e9996a696724",
                        "orgId": "deeproute",
                        "title": "AI 研发效能工程师",
                        "status": "open",
                        "description": "<p>开发 AI Agent。</p>",
                    }
                ],
            },
            endpoint,
        )

        total, jobs = fetch_public_job_list(
            organization_id="deeproute",
            limit=20,
        )

        self.assertEqual(total, 1)
        self.assertEqual(jobs[0]["title"], "AI 研发效能工程师")
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, endpoint)
        self.assertNotIn("Authorization", dict(request.header_items()))

    def test_rejects_unbounded_list_limit_before_network_access(self) -> None:
        with patch("collector.moka_client.urlopen") as mocked_urlopen:
            with self.assertRaisesRegex(MokaRequestError, "1 到 100"):
                fetch_public_job_list(
                    organization_id="deeproute",
                    limit=101,
                )
            mocked_urlopen.assert_not_called()

    @patch("collector.moka_client.urlopen")
    def test_reuses_cached_list_instead_of_requesting_again(
        self,
        mocked_urlopen,
    ) -> None:
        endpoint = (
            "https://api.mokahr.com/api-platform/v1/jobs/deeproute?"
            "mode=social&status=open&limit=20&offset=0&siteId=143885"
        )
        mocked_urlopen.return_value = _FakeResponse(
            {"code": 0, "total": 0, "jobs": []},
            endpoint,
        )

        fetch_public_job_list(organization_id="deeproute", limit=20)
        fetch_public_job_list(organization_id="deeproute", limit=20)

        self.assertEqual(mocked_urlopen.call_count, 1)

    @patch("collector.moka_client.urlopen")
    def test_pauses_source_after_rate_limit_without_retrying(
        self,
        mocked_urlopen,
    ) -> None:
        mocked_urlopen.side_effect = HTTPError(
            "https://api.mokahr.com/api-platform/v1/jobs/deeproute",
            429,
            "Too Many Requests",
            {},
            None,
        )

        with self.assertRaisesRegex(MokaRequestError, "HTTP 429"):
            fetch_public_job_list(organization_id="deeproute", limit=20)
        with self.assertRaisesRegex(MokaRequestError, "临时暂停"):
            fetch_public_job_list(organization_id="deeproute", limit=20)

        self.assertEqual(mocked_urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
