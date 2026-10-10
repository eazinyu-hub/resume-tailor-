import json
import tempfile
import unittest
from pathlib import Path

from app.candidate_descriptions import build_project_candidate_descriptions


TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "work" / "test-candidate-descriptions"


class CandidateDescriptionTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.directory.cleanup)
        self.facts_dir = Path(self.directory.name)
        self.card = {
            "project_id": "one", "project_name": "项目一", "fact_status": "draft",
            "real_problem": [{"content": "手工处理岗位数据容易遗漏。", "evidence_status": "已验证"}],
            "completed_features": [{"content": "实现 JD 导入、去重和匹配分析。", "evidence_status": "已验证"}],
            "debugging_methods": [{"content": "使用测试和 Git 小步提交验证。", "evidence_status": "已验证"}],
            "technology_and_ai_tools": [
                {"name": "React", "evidence_status": "已验证"},
                {"name": "Codex", "evidence_status": "已验证"},
                {"name": "Cursor", "evidence_status": "禁止写入简历"},
            ],
        }
        (self.facts_dir / "one.json").write_text(json.dumps(self.card, ensure_ascii=False), encoding="utf-8")

    def test_generates_three_grounded_angles_but_blocks_draft_card_from_resume(self):
        result = build_project_candidate_descriptions(self.facts_dir, "one")
        self.assertEqual(result["status"], "ready")
        self.assertEqual([item["label"] for item in result["candidates"]], ["自动化侧重点", "AI 全栈侧重点", "Vibe Coding 侧重点"])
        self.assertTrue(all(not item["allowed_in_resume"] for item in result["candidates"]))
        joined_evidence = " ".join(item for candidate in result["candidates"] for item in candidate["evidence"])
        self.assertIn("Codex", joined_evidence)
        self.assertNotIn("Cursor", joined_evidence)

    def test_allows_candidate_when_card_is_confirmed(self):
        self.card["fact_status"] = "confirmed"
        (self.facts_dir / "one.json").write_text(json.dumps(self.card, ensure_ascii=False), encoding="utf-8")
        result = build_project_candidate_descriptions(self.facts_dir, "one")
        self.assertTrue(all(item["allowed_in_resume"] for item in result["candidates"]))


if __name__ == "__main__":
    unittest.main()
