"""Public, deterministic demonstration of two job-specific Agent outcomes."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.deepseek_candidates import (
    apply_candidate_to_draft,
    generate_candidate_descriptions,
    prepare_candidate_context,
)


FIXTURE = Path(__file__).parent / "fixtures" / "deepseek_agent_demo_cases.json"
WORK_ROOT = Path(__file__).resolve().parents[2] / "work" / "test-deepseek-agent-demo"


class DeepSeekAgentDemoTests(unittest.TestCase):
    def setUp(self):
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=WORK_ROOT, ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.suite = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.database = self.root / "app.sqlite3"
        self.facts = self.root / "project-facts"
        self.facts.mkdir()
        (self.facts / "project-resume-tailor.json").write_text(
            json.dumps(self.suite["project"], ensure_ascii=False), encoding="utf-8"
        )
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "CREATE TABLE jobs(id INTEGER PRIMARY KEY, title TEXT, description TEXT, "
                "sample_status TEXT DEFAULT 'active', duplicate_of INTEGER)"
            )
            connection.execute(
                "CREATE TABLE job_analyses(job_id INTEGER, role_family TEXT, "
                "analysis_status TEXT, is_current INTEGER)"
            )
            connection.execute(
                "CREATE TABLE resume_drafts(job_id INTEGER PRIMARY KEY, content_json TEXT NOT NULL, "
                "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            for job_id, case in enumerate(self.suite["cases"], start=1):
                connection.execute(
                    "INSERT INTO jobs(id,title,description) VALUES (?,?,?)",
                    (job_id, case["title"], case["jd"]),
                )
            connection.commit()

    def model_output(self, case):
        candidate = {
            "focus": case["output"]["focus"],
            "bullets": [{
                "text": item["text"],
                "fact_ids": [f"project-resume-tailor/{item['fact_slot']}"],
                "jd_evidence": item["jd_evidence"],
                "reason": item["reason"],
            } for item in case["output"]["bullets"]],
        }
        return {"candidates": [candidate], "gaps": [], "risks": []}

    def test_two_jobs_produce_distinct_grounded_drafts(self):
        drafts = []
        for job_id, case in enumerate(self.suite["cases"], start=1):
            preview = prepare_candidate_context(self.database, self.facts, job_id)
            generated = generate_candidate_descriptions(
                self.database, self.facts, job_id, preview["context_hash"],
                complete=lambda *_args, current=case: (
                    self.model_output(current),
                    {"provider": "DeepSeek", "model": "fixture", "usage": {"total_tokens": 0}},
                ),
            )
            self.assertEqual(generated["candidates"][0]["focus"], case["expected_focus"])
            applied = apply_candidate_to_draft(
                self.database, self.facts, job_id, generated["preview_id"], 0, self.suite["resume"]
            )
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(applied["draft"]["source"], "agent-v1-deepseek-confirmed")
            text = json.dumps(applied["draft"], ensure_ascii=False)
            for term in case["expected_terms"]:
                self.assertIn(term, text)
            for term in case["forbidden_terms"]:
                self.assertNotIn(term, text)
            drafts.append(applied["draft"])

        first_projects = drafts[0]["sections"]["项目经历"]
        second_projects = drafts[1]["sections"]["项目经历"]
        self.assertNotEqual(first_projects, second_projects)
        self.assertIn("批量导入", " ".join(first_projects))
        self.assertNotIn("批量导入", " ".join(second_projects))
        self.assertIn("React", " ".join(second_projects))
        self.assertNotIn("React", " ".join(first_projects))

        with sqlite3.connect(self.database) as connection:
            saved = connection.execute(
                "SELECT job_id, content_json FROM resume_drafts ORDER BY job_id"
            ).fetchall()
        self.assertEqual([row[0] for row in saved], [1, 2])
        self.assertNotEqual(json.loads(saved[0][1])["jobTitle"], json.loads(saved[1][1])["jobTitle"])


if __name__ == "__main__":
    unittest.main()
