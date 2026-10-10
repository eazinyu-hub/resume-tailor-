import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.agent_v1 import build_agent_v1


class AgentV1Tests(unittest.TestCase):
    def test_blocks_formal_resume_for_draft_fact_card(self):
        temp_root = Path(__file__).resolve().parents[2] / "work" / "test-agent-v1"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as root:
            root = Path(root); database = root / "jobs.sqlite3"; facts = root / "facts"; facts.mkdir()
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, description TEXT, sample_status TEXT DEFAULT 'active', duplicate_of INTEGER)")
                connection.execute("CREATE TABLE job_analyses (job_id INTEGER, role_family TEXT, analysis_status TEXT, is_current INTEGER)")
                connection.execute("INSERT INTO jobs VALUES (1, 'Vibe 全栈', '使用 Python、Codex 完成前后端开发和部署。', 'active', NULL)")
                connection.execute("INSERT INTO jobs VALUES (2, '全栈', '使用 Python、Codex 完成前后端开发和部署。', 'active', NULL)")
                connection.commit()
            card = {"project_id": "one", "project_name": "项目", "fact_status": "draft", "real_problem": [], "completed_features": [{"content": "使用 Python、Codex 完成前后端开发和部署。", "evidence_status": "已验证"}], "technology_and_ai_tools": [], "errors_and_failures": [], "debugging_methods": [], "do_not_exaggerate": [], "completion": {"completed_scope": []}}
            (facts / "one.json").write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
            result = build_agent_v1(database, facts, 1, "ready")
            self.assertEqual(result["status"], "needs_confirmation")
            self.assertTrue(result["formal_resume"]["blocked"])
            self.assertTrue(result["change_reasons"])
            self.assertTrue(result["interviewer_questions"])

    def test_builds_full_resume_from_confirmed_facts_and_original_resume(self):
        temp_root = Path(__file__).resolve().parents[2] / "work" / "test-agent-v1"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as root:
            root = Path(root); database = root / "jobs.sqlite3"; facts = root / "facts"; facts.mkdir()
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, description TEXT, sample_status TEXT DEFAULT 'active', duplicate_of INTEGER)")
                connection.execute("CREATE TABLE job_analyses (job_id INTEGER, role_family TEXT, analysis_status TEXT, is_current INTEGER)")
                connection.execute("INSERT INTO jobs VALUES (1, 'Vibe 全栈', '使用 Python、Codex 完成前后端开发和调试。', 'active', NULL)")
                connection.execute("INSERT INTO jobs VALUES (2, '全栈', '使用 Python、Codex 完成前后端开发和调试。', 'active', NULL)")
                connection.commit()
            card = {
                "project_id": "one", "project_name": "事实项目", "project_type": "个人项目", "fact_status": "confirmed",
                "real_problem": [],
                "completed_features": [{"content": "使用 Python、Codex 完成前后端开发。", "evidence_status": "已验证"}],
                "technology_and_ai_tools": [{"name": "Codex", "usage": "辅助开发", "level": "实际使用", "evidence_status": "已验证"}],
                "errors_and_failures": [], "do_not_exaggerate": [],
                "debugging_methods": [{"content": "运行测试验证接口。", "evidence_status": "已验证"}],
                "completion": {"completed_scope": []},
            }
            (facts / "one.json").write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
            resume = {"status": "ready", "sections": {"个人简介": ["张三", "旧方向", "电话：待补充", "旧评价"], "教育背景": ["某大学"], "工作经历": ["某公司"], "项目经历": ["旧项目｜个人项目", "未确认内容"], "技术与工具": ["Cursor"]}}
            result = build_agent_v1(database, facts, 1, resume)
            self.assertEqual(result["status"], "ready")
            self.assertFalse(result["formal_resume"]["blocked"])
            draft = result["formal_resume"]["draft"]
            self.assertEqual(draft["source"], "agent-v1-confirmed-facts")
            self.assertIn("事实项目", str(draft["sections"]["项目经历"]))
            self.assertNotIn("未确认内容", str(draft))
