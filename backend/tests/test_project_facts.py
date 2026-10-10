import json
import tempfile
import unittest
from pathlib import Path

from app.project_facts import ProjectFactError, confirm_project_fact_card, save_project_fact_card


def example_card() -> dict:
    item = {"content": "真实内容", "evidence_status": "已验证"}
    return {
        "project_id": "example-project", "project_name": "示例项目", "project_type": "个人项目",
        "ownership": "主要负责", "ownership_note": "负责需求与验收。", "fact_status": "confirmed",
        "real_problem": [item], "completed_features": [item],
        "technology_and_ai_tools": [{"name": "Python", "usage": "后端", "level": "实际使用", "evidence_status": "已验证"}],
        "errors_and_failures": [item], "debugging_methods": [item],
        "completion": {"status": "本地原型", "completed_scope": [item], "remaining_scope": [{"content": "部署", "evidence_status": "计划实现"}], "last_verified_at": "2026-09-15"},
        "evidence": [{"type": "测试", "reference": "测试通过", "visibility": "private", "evidence_status": "已验证"}],
        "do_not_exaggerate": [{"content": "未部署", "evidence_status": "禁止写入简历"}], "updated_at": "2026-09-14",
    }


class ProjectFactTests(unittest.TestCase):
    def test_editing_reverts_confirmed_card_to_draft_then_can_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            facts_dir = Path(directory)
            path = facts_dir / "example-project.json"
            path.write_text(json.dumps(example_card(), ensure_ascii=False), encoding="utf-8")
            payload = example_card()
            payload["project_name"] = "修改后的项目"
            saved = save_project_fact_card(facts_dir, "example-project", payload)
            self.assertEqual(saved["project_name"], "修改后的项目")
            self.assertEqual(saved["fact_status"], "draft")
            confirmed = confirm_project_fact_card(facts_dir, "example-project")
            self.assertEqual(confirmed["fact_status"], "confirmed")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["fact_status"], "confirmed")

    def test_rejects_project_id_mismatch_and_invalid_evidence_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            facts_dir = Path(directory)
            (facts_dir / "example-project.json").write_text("{}", encoding="utf-8")
            payload = example_card()
            payload["project_id"] = "another-project"
            with self.assertRaises(ProjectFactError):
                save_project_fact_card(facts_dir, "example-project", payload)
            payload = example_card()
            payload["real_problem"][0]["evidence_status"] = "随便写"
            with self.assertRaises(ProjectFactError):
                save_project_fact_card(facts_dir, "example-project", payload)


if __name__ == "__main__":
    unittest.main()
