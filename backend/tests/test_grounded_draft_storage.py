import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class GroundedDraftStorageTests(unittest.TestCase):
    def test_legacy_draft_is_hidden_and_grounded_source_is_returned(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        backend_root = repository_root / "backend"
        temp_root = repository_root / "work" / "test-grounded-draft-storage"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            environment = {**os.environ, "DATA_DIR": directory, "PYTHONDONTWRITEBYTECODE": "1"}
            code = r'''
import json
import sqlite3
from app import main
from app.main import ResumeDraftRequest
with sqlite3.connect(main.DB_PATH) as connection:
    job_id = connection.execute("INSERT INTO jobs(title, description) VALUES (?, ?)", ("测试岗位", "Python")).lastrowid
    connection.execute("INSERT INTO resume_drafts(job_id, content_json) VALUES (?, ?)", (job_id, json.dumps({"jobTitle": "旧稿", "sections": {}, "changes": []})))
    connection.commit()
assert main.get_resume_draft(job_id)["status"] == "legacy"
saved = main.save_resume_draft(job_id, ResumeDraftRequest(job_title="新稿", sections={"项目经历": ["已确认事实"]}, changes=[], source="agent-v1-confirmed-facts"))
assert saved["draft"]["source"] == "agent-v1-confirmed-facts"
assert main.get_resume_draft(job_id)["status"] == "ready"
deepseek_saved = main.save_resume_draft(job_id, ResumeDraftRequest(job_title="AI 稿", sections={"项目经历": ["人工确认的 AI 候选"]}, changes=[], source="agent-v1-deepseek-confirmed"))
assert deepseek_saved["draft"]["source"] == "agent-v1-deepseek-confirmed"
assert main.get_resume_draft(job_id)["status"] == "ready"
'''
            subprocess.run([sys.executable, "-B", "-c", code], cwd=backend_root, env=environment,
                           check=True, capture_output=True, text=True, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
