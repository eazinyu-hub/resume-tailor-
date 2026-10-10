import unittest

from collector.adapters.lever import LeverPayloadError, parse_lever_posting


class LeverAdapterTests(unittest.TestCase):
    def test_converts_public_posting_to_normalized_job(self) -> None:
        job = parse_lever_posting(
            {
                "id": "26491a9f-ac14-4f12-a1ff-a2b96bf0356e",
                "text": "Junior AI Engineer",
                "hostedUrl": (
                    "https://jobs.lever.co/kgroupcompanies/"
                    "26491a9f-ac14-4f12-a1ff-a2b96bf0356e"
                ),
                "createdAt": 1789516800000,
                "categories": {"location": "Grand Rapids, Michigan"},
                "descriptionPlain": "Build practical AI automations.",
                "lists": [
                    {
                        "text": "Responsibilities",
                        "content": (
                            "<ul><li>Build n8n workflows.</li>"
                            "<li>Connect APIs and webhooks.</li></ul>"
                        ),
                    }
                ],
                "additionalPlain": "Show us a personal project.",
            },
            site_token="kgroupcompanies",
            company="K Group Companies",
        )

        self.assertEqual(job.source_id, "lever_postings_api")
        self.assertEqual(job.title, "Junior AI Engineer")
        self.assertEqual(job.city, "Grand Rapids, Michigan")
        self.assertIn("Build n8n workflows.", job.description)
        self.assertNotIn("<li>", job.description)
        self.assertEqual(job.published_at, "2026-09-16T00:00:00+00:00")

    def test_rejects_wrong_hosted_url(self) -> None:
        with self.assertRaisesRegex(LeverPayloadError, "公开岗位地址"):
            parse_lever_posting(
                {
                    "id": "26491a9f-ac14-4f12-a1ff-a2b96bf0356e",
                    "text": "Junior AI Engineer",
                    "hostedUrl": "https://example.com/jobs/1",
                    "descriptionPlain": "Build AI tools.",
                },
                site_token="kgroupcompanies",
                company="K Group Companies",
            )


if __name__ == "__main__":
    unittest.main()
