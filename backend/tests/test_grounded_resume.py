import unittest

from app.grounded_resume import build_grounded_resume, choose_candidate


class GroundedResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cards = [{
            "project_id": "one", "project_name": "事实项目", "project_type": "个人项目", "fact_status": "confirmed",
            "technology_and_ai_tools": [
                {"name": "Python", "usage": "开发后端接口", "level": "实际使用", "evidence_status": "已验证"},
                {"name": "Cursor", "usage": "尚未使用", "level": "未实际使用", "evidence_status": "禁止写入简历"},
            ],
            "debugging_methods": [{"content": "运行单元测试验证接口。", "evidence_status": "已验证"}],
        }]
        self.resume = {"sections": {
            "个人简介": ["张三", "旧求职方向", "电话：待补充", "未经确认的自我评价"],
            "教育背景": ["某大学"], "工作经历": ["某公司"],
            "项目经历": ["旧项目｜个人项目", "未经确认的 Agent 能力"],
            "技术与工具": ["Cursor、Agent"], "开发方式": ["旧描述"],
        }}
        self.candidate = {"project_id": "one", "project_name": "事实项目", "label": "AI 全栈侧重点",
                          "evidence": ["使用 Python 完成后端接口。"], "fact_ids": ["one/completed_features/0"], "allowed_in_resume": True}

    def test_resume_replaces_unconfirmed_projects_and_tools(self) -> None:
        result = build_grounded_resume("Python 工程师", self.resume, [self.candidate], self.cards, "AI 工具与自动化")
        text = str(result)
        self.assertIn("某大学", text)
        self.assertIn("使用 Python 完成后端接口。", text)
        self.assertIn("Python：开发后端接口", text)
        self.assertNotIn("未经确认的 Agent 能力", text)
        self.assertNotIn("Cursor、Agent", text)
        self.assertEqual(result["source"], "agent-v1-confirmed-facts")

    def test_candidate_angle_changes_with_role_family(self) -> None:
        options = [
            {**self.candidate, "label": "自动化侧重点"},
            {**self.candidate, "label": "Vibe Coding 侧重点"},
        ]
        fact_ids = {"one/completed_features/0"}
        self.assertEqual(choose_candidate(options, fact_ids, "ai_tool_automation")["label"], "自动化侧重点")
        self.assertEqual(choose_candidate(options, fact_ids, "vibe_coding_fullstack")["label"], "Vibe Coding 侧重点")

    def test_no_direct_match_uses_truthful_fallback_instead_of_blocking(self) -> None:
        options = [{**self.candidate, "label": "自动化侧重点"}]
        chosen = choose_candidate(options, {"another/fact/0"}, "ai_tool_automation")
        self.assertEqual(chosen["label"], "自动化侧重点")
        self.assertFalse(chosen["matches_current_jd"])
        result = build_grounded_resume("Agent 工程师", self.resume, [chosen], self.cards, "Agent 应用开发")
        self.assertIn("岗位缺口", " ".join(result["changes"]))


if __name__ == "__main__":
    unittest.main()
