import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.fact_matching import build_fact_match_table


TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "work" / "test-fact-matching"


class FactMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database = root / "jobs.sqlite3"
        self.facts_dir = root / "project-facts"
        self.facts_dir.mkdir()
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, description TEXT)")
            connection.execute("INSERT INTO jobs VALUES (1, '全栈岗位', '使用 Python、React、Codex 完成部署和调试。')")
            connection.commit()
        card = {
            "project_id": "one", "project_name": "项目一", "fact_status": "draft",
            "completed_features": [{"content": "使用 Python、React 和 Codex 完成部署。", "evidence_status": "已验证"}],
            "technology_and_ai_tools": [], "real_problem": [], "errors_and_failures": [], "debugging_methods": [], "do_not_exaggerate": [],
            "completion": {"completed_scope": []},
        }
        (self.facts_dir / "one.json").write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")

    def test_matches_verified_fact_but_blocks_resume_until_card_is_confirmed(self):
        result = build_fact_match_table(self.database, self.facts_dir, 1)
        python = next(item for item in result["items"] if item["requirement"] == "Python")
        self.assertEqual(python["strength"], "强")
        self.assertFalse(python["allowed_in_resume"])
        self.assertIn("草稿", python["matched_facts"][0]["write_reason"])
        self.assertIn("尚未确认", python["gap"])

    def test_returns_gap_when_no_fact_exists(self):
        result = build_fact_match_table(self.database, self.facts_dir, 1)
        debugging = next(item for item in result["items"] if item["requirement"] == "调试与测试")
        self.assertEqual(debugging["strength"], "无")
        self.assertFalse(debugging["allowed_in_resume"])


if __name__ == "__main__":
    unittest.main()
