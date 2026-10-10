import unittest

from app.collection_relevance import evaluate_collected_job


REFERENCES = [
    {
        "id": 1,
        "title": "Vibe Coding 全栈工程师",
        "description": (
            "使用 Cursor、Claude Code 完成 AI 应用原型，"
            "独立进行前端开发、后端开发、API 联调、调试和部署。"
        ),
        "role_family": "vibe_coding_fullstack",
    },
    {
        "id": 2,
        "title": "AI 工具开发",
        "description": (
            "使用 Python 开发内部工具和自动化脚本，处理数据，"
            "完成需求分析、调试、测试和使用文档。"
        ),
        "role_family": "ai_tool_automation",
    },
]


class CollectionRelevanceTests(unittest.TestCase):
    def test_allows_aligned_chinese_entry_level_job(self) -> None:
        result = evaluate_collected_job(
            {
                "title": "Vibe Coding 开发工程师",
                "description": (
                    "使用 Claude Code 开发 AI 应用，完成前端开发、"
                    "后端开发、API 联调、调试与部署，接受优秀应届生。"
                ),
            },
            REFERENCES,
        )

        self.assertEqual(result["market_scope"], "china_target")
        self.assertEqual(result["sample_usage"], "target_market")
        self.assertTrue(result["allow_market_profile"])
        self.assertGreater(result["score"], 25)

    def test_keeps_english_research_role_out_of_core_portrait(self) -> None:
        result = evaluate_collected_job(
            {
                "title": "Staff Software Engineer, Research Tools",
                "description": (
                    "Build full-stack research infrastructure for reinforcement "
                    "learning experiments. Requires 8+ years of experience."
                ),
            },
            REFERENCES,
        )

        self.assertEqual(result["market_scope"], "overseas")
        self.assertEqual(result["sample_usage"], "overseas_reference")
        self.assertFalse(result["allow_market_profile"])
        self.assertTrue(any("8 年" in item for item in result["exclusion_reasons"]))
        self.assertTrue(any("Staff" in item for item in result["exclusion_reasons"]))

    def test_score_is_not_presented_as_candidate_competence(self) -> None:
        result = evaluate_collected_job(
            {"title": "普通岗位", "description": "负责日常工作。"},
            REFERENCES,
        )

        self.assertIn("不是胜任度或录用概率", result["score_note"])
        self.assertFalse(result["allow_market_profile"])

    def test_explains_overseas_work_authorization_and_onsite_limits(self) -> None:
        result = evaluate_collected_job(
            {
                "title": "Junior AI & Automation Engineer",
                "description": (
                    "Build internal AI tools, n8n workflows, APIs and webhooks. "
                    "Applicants must be legally authorized to work in the US. "
                    "This role is 100% onsite and does not offer visa sponsorship."
                ),
            },
            REFERENCES,
        )

        self.assertEqual(result["sample_usage"], "overseas_reference")
        self.assertFalse(result["allow_market_profile"])
        self.assertIn(
            "存在当地工作资格或签证限制",
            result["exclusion_reasons"],
        )
        self.assertIn(
            "要求在岗位所在地现场办公",
            result["exclusion_reasons"],
        )
        self.assertFalse(
            any("年或以上经验" in item for item in result["exclusion_reasons"])
        )

    def test_company_history_is_not_candidate_experience(self) -> None:
        result = evaluate_collected_job(
            {
                "title": "Junior AI Engineer",
                "description": (
                    "We have 40+ years of relationships with our customers. "
                    "Build AI tools and automation workflows with Python APIs."
                ),
            },
            REFERENCES,
        )

        self.assertFalse(
            any("年或以上经验" in item for item in result["exclusion_reasons"])
        )

    def test_preserves_degree_and_major_requirement_as_context(self) -> None:
        result = evaluate_collected_job(
            {
                "title": "AI 研发效能工程师",
                "description": (
                    "使用 Cursor、Claude Code、Codex 开发 AI Agent。"
                    "本科及以上，计算机、人工智能、数据科学、"
                    "软件工程或相关专业。"
                ),
            },
            REFERENCES,
        )

        self.assertIn(
            "明确要求本科及以上及相关专业背景",
            result["exclusion_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
