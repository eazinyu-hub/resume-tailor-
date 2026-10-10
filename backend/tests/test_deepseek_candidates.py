import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.deepseek_candidates import (
    CandidateError,
    apply_candidate_to_draft,
    generate_candidate_descriptions,
    prepare_candidate_context,
)


class DeepSeekCandidateTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / "work" / "test-deepseek-candidates"
        root.mkdir(parents=True, exist_ok=True)
        # Windows security scanners can briefly retain a closed SQLite file;
        # never let that platform cleanup race hide the assertions above.
        self.temp = tempfile.TemporaryDirectory(dir=root, ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "jobs.sqlite3"
        self.facts = self.root / "facts"
        self.facts.mkdir()
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, description TEXT, sample_status TEXT DEFAULT 'active', duplicate_of INTEGER)")
            connection.execute("CREATE TABLE job_analyses (job_id INTEGER, role_family TEXT, analysis_status TEXT, is_current INTEGER)")
            connection.execute("CREATE TABLE resume_drafts (job_id INTEGER PRIMARY KEY, content_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("INSERT INTO jobs VALUES (1, 'AI 工具开发', '使用 AI 编程工具开发内部小工具，完成前后端开发与调试。', 'active', NULL)")
            connection.execute("INSERT INTO jobs VALUES (2, 'Vibe Coding 全栈', '使用 AI 编程工具完成前后端开发与调试。', 'active', NULL)")
            connection.execute("INSERT INTO resume_drafts(job_id, content_json) VALUES (1, ?)", (json.dumps({"jobTitle": "旧稿", "sections": {"项目经历": ["旧内容"]}, "changes": [], "source": "agent-v1-confirmed-facts"}, ensure_ascii=False),))
            connection.execute("INSERT INTO resume_drafts(job_id, content_json) VALUES (2, ?)", (json.dumps({"jobTitle": "岗位二旧稿", "sections": {}, "changes": [], "source": "agent-v1-confirmed-facts"}, ensure_ascii=False),))
            connection.commit()
        self.card = {
            "project_id": "project-resume-tailor", "project_name": "AI 简历适配工作台",
            "project_type": "个人项目", "ownership": "独立完成", "ownership_note": "负责需求、实现与验收。",
            "fact_status": "confirmed", "updated_at": "2026-09-22", "phone": "13000000000",
            "real_problem": [{"content": "个人求职探索", "evidence_status": "已验证"}],
            "completed_features": [
                {"content": "使用 React 和 FastAPI 实现岗位分析页面与后端接口。", "evidence_status": "已验证"},
                {"content": "实现岗位批量导入、去重与人工确认流程。", "evidence_status": "已验证"},
                {"content": "准备部署功能。", "evidence_status": "计划实现"},
            ],
            "technology_and_ai_tools": [{"name": "Codex", "usage": "辅助拆分需求和调试", "level": "实际使用", "evidence_status": "已验证"}],
            "debugging_methods": [{"content": "运行自动化测试并检查前后端接口。", "evidence_status": "已验证"}],
            "errors_and_failures": [],
            "do_not_exaggerate": [{"content": "未部署到公网，没有真实用户。", "evidence_status": "禁止写入简历"}],
            "completion": {"completed_scope": [], "remaining_scope": [{"content": "公网部署", "evidence_status": "计划实现"}]},
        }
        self.path = self.facts / "project-resume-tailor.json"
        self.path.write_text(json.dumps(self.card, ensure_ascii=False), encoding="utf-8")
        self.resume = {"status": "ready", "sections": {
            "个人简介": ["测试姓名", "电话：待补充"], "教育背景": ["某大学"],
            "工作经历": ["某公司"], "项目经历": ["旧项目｜个人项目"],
        }}

    def valid_output(self, preview):
        facts = preview["context"]["allowed_facts"]
        feature_id = next(item["fact_id"] for item in facts if "React 和 FastAPI" in item["content"])
        debugging_id = next(item["fact_id"] for item in facts if item["source_field"] == "debugging_methods")
        return {"candidates": [{"focus": "AI 全栈侧重点", "bullets": [
            {"text": "使用 React 与 FastAPI 实现岗位分析页面和后端接口。", "fact_ids": [feature_id],
             "jd_evidence": "完成前后端开发与调试", "reason": "岗位强调前后端开发与调试。"},
            {"text": "通过自动化测试和接口检查验证前后端功能。", "fact_ids": [debugging_id],
             "jd_evidence": "完成前后端开发与调试", "reason": "突出实际调试与验证过程。"},
        ]}], "gaps": ["没有公网部署事实"], "risks": ["不要写成已上线产品"]}

    def test_preview_sends_only_bounded_job_and_project_context(self):
        preview = prepare_candidate_context(self.database, self.facts, 1)
        raw = json.dumps(preview, ensure_ascii=False)
        self.assertEqual(preview["status"], "ready")
        self.assertEqual(len(preview["context_hash"]), 64)
        self.assertIn("未部署到公网", raw)
        self.assertNotIn("13000000000", raw)
        self.assertNotIn("准备部署功能", raw)
        self.assertTrue(all(item["fact_id"].startswith("project-resume-tailor/") for item in preview["context"]["allowed_facts"]))
        self.assertNotIn("original_resume", preview["context"])

    def test_generation_returns_preview_only_with_traceable_facts(self):
        preview = prepare_candidate_context(self.database, self.facts, 1)
        calls = []
        def complete(messages, config_error):
            calls.append((messages, config_error))
            return self.valid_output(preview), {"provider": "DeepSeek", "model": "mock", "usage": {"total_tokens": 100}}
        result = generate_candidate_descriptions(
            self.database, self.facts, 1, preview["context_hash"], complete=complete
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "ready")
        self.assertRegex(result["preview_id"], r"^[a-f0-9]{32}$")
        self.assertTrue((self.root / "agent-previews" / f"{result['preview_id']}.json").exists())
        self.assertTrue(result["candidates"][0]["bullets"][0]["facts"])
        self.assertIn("尚未应用", result["note"])

    def test_confirmed_apply_backs_up_old_draft_and_keeps_other_job_independent(self):
        preview = prepare_candidate_context(self.database, self.facts, 1)
        generated = generate_candidate_descriptions(
            self.database, self.facts, 1, preview["context_hash"],
            complete=lambda *_: (self.valid_output(preview), {"provider": "DeepSeek", "model": "mock", "usage": {}}),
        )
        with sqlite3.connect(self.database) as connection:
            before_other = connection.execute("SELECT content_json FROM resume_drafts WHERE job_id=2").fetchone()[0]
        result = apply_candidate_to_draft(
            self.database, self.facts, 1, generated["preview_id"], 0, self.resume
        )
        self.assertEqual(result["status"], "applied")
        self.assertTrue(result["backup_created"])
        self.assertEqual(result["draft"]["source"], "agent-v1-deepseek-confirmed")
        self.assertIn("React", " ".join(result["draft"]["sections"]["项目经历"]))
        backups = list((self.root / "backups" / "resume-drafts").glob("job-1-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8"))["draft"]["jobTitle"], "旧稿")
        with sqlite3.connect(self.database) as connection:
            after_other = connection.execute("SELECT content_json FROM resume_drafts WHERE job_id=2").fetchone()[0]
        self.assertEqual(after_other, before_other)

    def test_stale_or_cross_job_candidate_never_changes_old_draft(self):
        preview = prepare_candidate_context(self.database, self.facts, 1)
        generated = generate_candidate_descriptions(
            self.database, self.facts, 1, preview["context_hash"],
            complete=lambda *_: (self.valid_output(preview), {"provider": "DeepSeek", "model": "mock", "usage": {}}),
        )
        with sqlite3.connect(self.database) as connection:
            old = connection.execute("SELECT content_json FROM resume_drafts WHERE job_id=1").fetchone()[0]
        with self.assertRaises(CandidateError) as caught:
            apply_candidate_to_draft(self.database, self.facts, 2, generated["preview_id"], 0, self.resume)
        self.assertEqual(caught.exception.code, "preview_job_mismatch")
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE jobs SET description = description || ' 新要求' WHERE id=1")
            connection.commit()
        with self.assertRaises(CandidateError) as caught:
            apply_candidate_to_draft(self.database, self.facts, 1, generated["preview_id"], 0, self.resume)
        self.assertEqual(caught.exception.code, "context_changed")
        with sqlite3.connect(self.database) as connection:
            current = connection.execute("SELECT content_json FROM resume_drafts WHERE job_id=1").fetchone()[0]
        self.assertEqual(current, old)

    def test_unknown_fact_unsupported_number_and_restricted_claim_are_blocked(self):
        preview = prepare_candidate_context(self.database, self.facts, 1)
        base = self.valid_output(preview)
        cases = []
        unknown = json.loads(json.dumps(base, ensure_ascii=False)); unknown["candidates"][0]["bullets"][0]["fact_ids"] = ["missing/fact/0"]
        cases.append((unknown, "unknown_fact"))
        number = json.loads(json.dumps(base, ensure_ascii=False)); number["candidates"][0]["bullets"][0]["text"] += "，效率提升 80%"
        cases.append((number, "unsupported_number"))
        deployed = json.loads(json.dumps(base, ensure_ascii=False)); deployed["candidates"][0]["bullets"][0]["text"] = "完成公网部署并上线岗位分析服务。"
        cases.append((deployed, "restricted_claim"))
        for output, code in cases:
            with self.subTest(code=code), self.assertRaises(CandidateError) as caught:
                generate_candidate_descriptions(
                    self.database, self.facts, 1, preview["context_hash"],
                    complete=lambda *_args, value=output: (value, {"provider": "DeepSeek", "model": "mock", "usage": {}}),
                )
            self.assertEqual(caught.exception.code, code)

    def test_context_change_and_unconfirmed_card_are_blocked_before_model(self):
        preview = prepare_candidate_context(self.database, self.facts, 1)
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE jobs SET description = description || ' 新要求' WHERE id=1")
            connection.commit()
        with self.assertRaises(CandidateError) as caught:
            generate_candidate_descriptions(self.database, self.facts, 1, preview["context_hash"],
                                            complete=lambda *_: self.fail("model must not run"))
        self.assertEqual(caught.exception.code, "context_changed")
        self.card["fact_status"] = "draft"
        self.path.write_text(json.dumps(self.card, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(CandidateError) as caught:
            prepare_candidate_context(self.database, self.facts, 1)
        self.assertEqual(caught.exception.code, "facts_not_confirmed")


if __name__ == "__main__":
    unittest.main()
