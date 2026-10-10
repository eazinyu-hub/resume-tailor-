import unittest

from app.collection_discovery import rank_moka_candidates


REFERENCES = [
    {
        "id": 1,
        "title": "AI Agent 开发工程师",
        "description": (
            "使用 Cursor、Claude Code、Codex 开发 AI Agent 和内部工具，"
            "完成自动化工作流、Python API、调试与部署。"
        ),
        "role_family": "agent_application",
    }
]


class CollectionDiscoveryTests(unittest.TestCase):
    def test_keeps_target_job_and_marks_existing_staging_record(self) -> None:
        candidates = rank_moka_candidates(
            [
                {
                    "id": "target-id",
                    "title": "AI 研发效能工程师",
                    "description": (
                        "<p>使用 Cursor、Claude Code、Codex 开发 AI Agent，"
                        "建设内部效能工具与自动化工作流。</p>"
                    ),
                    "updatedAt": "2026-09-17T00:00:00.000Z",
                }
            ],
            REFERENCES,
            staged_job_ids={"target-id"},
        )

        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0]["already_staged"])
        self.assertIn("研发效能", candidates[0]["signals"])

    def test_excludes_research_algorithm_and_senior_titles(self) -> None:
        candidates = rank_moka_candidates(
            [
                {
                    "id": "research-id",
                    "title": "World Model 算法专家",
                    "description": "<p>研究 AI Agent 与模型训练。</p>",
                },
                {
                    "id": "director-id",
                    "title": "AI 平台负责人",
                    "description": "<p>建设 AI 工具、Agent 和自动化平台。</p>",
                },
            ],
            REFERENCES,
        )

        self.assertEqual(candidates, [])

    def test_excludes_generic_title_that_only_mentions_ai_in_description(self) -> None:
        candidates = rank_moka_candidates(
            [
                {
                    "id": "embedded-id",
                    "title": "嵌入式软件开发实习生",
                    "description": (
                        "<p>使用 AI Coding、Cursor、Codex 开发内部工具，"
                        "并完成自动化工作流。</p>"
                    ),
                }
            ],
            REFERENCES,
        )

        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
