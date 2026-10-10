import unittest

from collector.adapters.moka import MokaPayloadError, parse_moka_job


class MokaAdapterTests(unittest.TestCase):
    def test_converts_open_public_job_to_normalized_job(self) -> None:
        job = parse_moka_job(
            {
                "success": True,
                "id": "57eddbd2-5e18-4b7f-b2b6-e9996a696724",
                "title": "AI 研发效能工程师",
                "status": "open",
                "orgId": "deeproute",
                "description": (
                    "<p>岗位职责</p><ul><li>开发 AI Agent。</li></ul>"
                    "<p>本科及以上，计算机相关专业。</p>"
                ),
                "publishedAt": "2026-04-22T09:46:27.000Z",
                "updatedAt": "2026-08-03T03:25:59.000Z",
                "locations": [
                    {"country": "中国", "province": "广东省", "city": "深圳市"}
                ],
                "minSalary": 15,
                "maxSalary": 25,
            },
            organization_token="deeproute",
            company="深圳元戎启行科技有限公司",
            careers_url=(
                "https://app.mokahr.com/social-recruitment/deeproute/143885"
            ),
        )

        self.assertEqual(job.source_id, "moka_recruitment_api")
        self.assertEqual(job.title, "AI 研发效能工程师")
        self.assertEqual(job.city, "中国 广东省 深圳市")
        self.assertEqual(job.salary, "15-25K")
        self.assertIn("开发 AI Agent。", job.description)
        self.assertNotIn("<li>", job.description)
        self.assertEqual(job.source_updated_at, "2026-08-03T03:25:59.000Z")

    def test_rejects_job_that_is_not_open(self) -> None:
        with self.assertRaisesRegex(MokaPayloadError, "不是招聘中"):
            parse_moka_job(
                {
                    "success": True,
                    "id": "57eddbd2-5e18-4b7f-b2b6-e9996a696724",
                    "title": "AI 工程师",
                    "status": "closed",
                    "orgId": "deeproute",
                    "description": "<p>岗位已关闭</p>",
                },
                organization_token="deeproute",
                company="元戎启行",
                careers_url=(
                    "https://app.mokahr.com/social-recruitment/deeproute/143885"
                ),
            )

    def test_rejects_response_from_another_organization(self) -> None:
        with self.assertRaisesRegex(MokaPayloadError, "白名单不一致"):
            parse_moka_job(
                {
                    "success": True,
                    "id": "57eddbd2-5e18-4b7f-b2b6-e9996a696724",
                    "title": "AI 工程师",
                    "status": "open",
                    "orgId": "another-company",
                    "description": "<p>开发 AI 工具</p>",
                },
                organization_token="deeproute",
                company="元戎启行",
                careers_url=(
                    "https://app.mokahr.com/social-recruitment/deeproute/143885"
                ),
            )


if __name__ == "__main__":
    unittest.main()
