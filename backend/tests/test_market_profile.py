import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.market_profile import compare_job_to_market, find_similar_jobs, get_keyword_frequencies, get_role_profiles, suggest_role_family


TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "work" / "test-market-profile"


class KeywordFrequencyTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "samples.sqlite3"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT, description TEXT, "
                "sample_status TEXT DEFAULT 'active', duplicate_of INTEGER)"
            )
            connection.execute("CREATE TABLE job_analyses (job_id INTEGER, role_family TEXT, analysis_status TEXT, is_current INTEGER)")

    def add_job(self, description, title="示例岗位", status="active", duplicate_of=None):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "INSERT INTO jobs (title, description, sample_status, duplicate_of) VALUES (?, ?, ?, ?)",
                (title, description, status, duplicate_of),
            )
            connection.commit()

    def test_counts_documents_separately_from_occurrences_and_includes_zero_hits(self):
        self.add_job("Codex codex CODEX；Agent、Agents、智能体；PYTHON；部署部署；调试")
        self.add_job("了解 Python，无需调试。")
        self.add_job("只做需求梳理。", title="React工程师")
        result = get_keyword_frequencies(self.database)
        items = {item["keyword"]: item for item in result["items"]}
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(items["Codex"]["job_count"], 1)
        self.assertEqual(items["Codex"]["occurrences"], 3)
        self.assertEqual(items["Codex"]["percentage"], 33.3)
        self.assertEqual(items["Agent"]["occurrences"], 3)
        self.assertEqual(items["部署"]["occurrences"], 2)
        self.assertEqual(items["Python"]["job_count"], 2)
        self.assertEqual(items["调试"]["job_count"], 2)  # Mentions, including negation.
        self.assertEqual(items["React"]["occurrences"], 0)  # Titles are excluded.
        self.assertEqual(items["Codex"]["jobs"][0]["id"], 1)
        self.assertIn("Codex codex CODEX", items["Codex"]["jobs"][0]["evidence"])

    def test_excludes_duplicates_without_deleting_and_keeps_unconfirmed_near_matches(self):
        self.add_job("使用 Python 开发。")
        self.add_job("使用\nPython开发。", title="不同标题")
        self.add_job("使用ＰＹＴＨＯＮ开发。")
        self.add_job("这份已人工确认重复", status="duplicate")
        self.add_job("无效内容", status="invalid")
        self.add_job(" \n\t")
        self.add_job("关联主样本的重复内容", duplicate_of=1)
        self.add_job("使用 Python 开发，并部署。")
        original_bytes = self.database.read_bytes()
        result = get_keyword_frequencies(self.database)
        self.assertEqual(result["total_records"], 8)
        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(result["excluded_duplicates"], 4)
        self.assertEqual(result["excluded_invalid"], 2)
        python = next(item for item in result["items"] if item["keyword"] == "Python")
        self.assertEqual(python["job_count"], 2)
        self.assertEqual([job["id"] for job in python["jobs"]], [1, 8])
        self.assertEqual(self.database.read_bytes(), original_bytes)

    def test_matches_english_terms_without_substring_false_positives(self):
        self.add_job("Codexer、AutoAgent、Agentic、Preact、Pythonic。会用Codex和Python以及React.js，配置Agents与智能体。")
        result = get_keyword_frequencies(self.database)
        counts = {item["keyword"]: item["occurrences"] for item in result["items"]}
        self.assertEqual({k: counts[k] for k in ("Codex", "Agent", "Python", "React", "部署", "调试")}, {"Codex": 1, "Agent": 2, "Python": 1, "React": 1, "部署": 0, "调试": 0})

    def test_empty_library_returns_zero_instead_of_dividing_by_zero(self):
        result = get_keyword_frequencies(self.database)
        self.assertEqual(result["sample_count"], 0)
        self.assertIn("MCP", [x["keyword"] for x in result["items"]])
        self.assertTrue(all(item["job_count"] == item["occurrences"] == item["percentage"] == 0 for item in result["items"]))

    def test_rereads_database_after_new_import(self):
        self.add_job("使用 Codex。")
        self.assertEqual(get_keyword_frequencies(self.database)["sample_count"], 1)
        self.add_job("使用 Python。")
        result = get_keyword_frequencies(self.database)
        codex = next(item for item in result["items"] if item["keyword"] == "Codex")
        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(codex["percentage"], 50)

    def test_role_profile_uses_confirmed_group_then_explainable_suggestion(self):
        self.add_job("产品经理负责 AI Coding 产品体验、用户反馈和需求上线。", "AI 产品经理")
        self.add_job("使用 Python、React、Codex 完成前后端开发、部署和调试。", "全栈工程师")
        self.add_job("使用 Python 开发智能体和工具调用逻辑。", "Agent 工程师")
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("INSERT INTO job_analyses (job_id, role_family, analysis_status, is_current) VALUES (1, ?, 'confirmed', 1)", ("vibe_coding_fullstack",))
            connection.commit()
        profile = get_role_profiles(self.database)
        by_family = {item["family"]: item for item in profile["profiles"]}
        self.assertEqual(profile["confirmed_count"], 1)
        self.assertEqual(profile["suggested_count"], 2)
        self.assertEqual(by_family["vibe_coding_fullstack"]["sample_count"], 2)
        self.assertEqual(by_family["agent_application"]["sample_count"], 1)
        sections = {section["name"]: section["items"] for section in by_family["vibe_coding_fullstack"]["sections"]}
        self.assertIn("Python", [item["name"] for item in sections["技术栈"]])
        self.assertIn("Codex", [item["name"] for item in sections["AI 工具"]])
        self.assertIn("部署与维护", [item["name"] for item in sections["交付能力"]])
        portrait = by_family["vibe_coding_fullstack"]["portrait"]
        self.assertIn("样本较少", portrait["summary"])
        self.assertNotIn("Codex", portrait["summary"])  # One mention isn't a market consensus.
        self.assertEqual(portrait["barriers"], [])

    def test_product_title_outweighs_an_agent_example_in_role_suggestion(self):
        result = suggest_role_family("AI 产品经理", "梳理 Agent 场景，设计产品体验并分析用户反馈。")
        self.assertEqual(result["family"], "ai_product_operations")
        self.assertIn("产品经理", result["reasons"])

    def test_compares_target_against_other_samples_without_counting_itself(self):
        self.add_job("使用 Codex、Python、React 完成前后端开发、部署和调试。要求沟通协作。", "目标全栈")
        self.add_job("使用 Codex、Python 完成前后端开发、部署和调试。", "同类一")
        self.add_job("使用 Codex、Python 完成前后端开发、部署和测试。", "同类二")
        result = compare_job_to_market(self.database, 1)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["baseline_count"], 2)
        self.assertIn("Python", [item["name"] for item in result["typical_requirements"]])
        self.assertEqual(result["especially_emphasized"], [])  # Fewer than three peers.
        self.assertEqual(result["possible_copywriting_noise"], [])  # Concrete collaboration is not copywriting noise.

    def test_finds_explainable_similar_samples_without_returning_target_or_duplicates(self):
        self.add_job("使用 Codex、Python、React 完成前后端开发、部署和调试。", "目标全栈")
        self.add_job("使用 Codex、Python 完成前后端开发、部署和测试。", "相似全栈")
        self.add_job("使用 Codex 开发智能体和工具调用。", "Agent 岗位")
        self.add_job("使用 Codex、Python、React 完成前后端开发、部署和调试。", "完全重复", status="duplicate")
        result = find_similar_jobs(self.database, 1, limit=10)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["target_family"], "vibe_coding_fullstack")
        self.assertEqual(result["items"][0]["id"], 2)
        self.assertNotIn(1, [item["id"] for item in result["items"]])
        self.assertNotIn(4, [item["id"] for item in result["items"]])
        self.assertIn("同属Vibe Coding 全栈", result["items"][0]["reasons"])
        self.assertIn({"section": "AI 工具", "name": "Codex"}, result["items"][0]["shared_signals"])


if __name__ == "__main__":
    unittest.main()
