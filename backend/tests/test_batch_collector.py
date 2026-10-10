import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from app.collection_gate import DIRECTIONS, assess_batch_job
from collector.batch import BatchBusyError, BatchCollector, body_fingerprint
from collector.batch_sources import BatchSourceError, SourcePage, fetch_source_page, list_batch_sources
from collector import batch_sources
from collector.models import CollectedJob
from collector.staging import read_staging


TEMP_ROOT = Path(__file__).resolve().parents[2] / "work" / "test-batch-collector"
PROFILE = {"schema_version": 1, "education": {"level": "bachelor", "related_major": False, "elite_school": False},
    "relevant_experience_years": 0, "verified_tools": ["Codex"], "project_count": 3}
GOOD = "岗位职责：使用 Codex 开发内部工具、自动化脚本。任职要求：本科及以上，专业不限，经验不限。"
SOURCES = [dict(key="test:one", company="测试公司一", default_selected=True), dict(key="test:two", company="测试公司二")]


def job(description=GOOD, title="AI 工具开发专员", identifier="1"):
    return CollectedJob(title=title, description=description, source_id="mock_local", company="测试公司",
                        source_job_id=identifier, source_url="https://example.com/jobs/" + identifier)


class BatchGateTests(unittest.TestCase):
    def assess(self, item):
        return assess_batch_job(item, PROFILE, ["tools", "vibe", "agent"])

    def test_explicit_entry_job_passes_but_preferences_do_not_block(self):
        self.assertEqual(self.assess(job())["decision"], "accepted")
        self.assertEqual(self.assess(job(GOOD + "加分项：计算机专业、3年以上开发经验优先。"))["decision"], "accepted")

    def test_hard_experience_and_major_overrule_coding_tools(self):
        value = self.assess(job("使用 Codex 开发 AI 工具。任职要求：本科及以上，计算机相关专业，3年以上开发经验。"))
        self.assertEqual(value["decision"], "excluded")
        self.assertTrue(any("3 年" in reason for reason in value["reasons"]))

    def test_missing_experience_never_means_entry(self):
        value = self.assess(job("使用 Codex 开发内部工具。"))
        self.assertEqual(value["decision"], "needs_review")
        self.assertFalse(any("外文" in reason for reason in value["reasons"]))

    def test_elite_education_senior_and_production_depth_are_rejected(self):
        for text, title in [(GOOD + "要求985/211院校。", "AI 工具开发"),
                            (GOOD, "高级 AI 工具工程师"), (GOOD + "负责高并发大型生产系统。", "AI 工具开发")]:
            with self.subTest(title=title, text=text):
                self.assertEqual(self.assess(job(text, title))["decision"], "excluded")

    def test_campus_and_english_are_uncertain_not_zero_experience_recommendations(self):
        self.assertEqual(self.assess(job(title="AI 工具实习生"))["decision"], "needs_review")
        self.assertEqual(self.assess(job("Build AI automation with Codex and Python.", "AI tool developer"))["decision"], "needs_review")

    def test_unselected_direction_is_rejected(self):
        self.assertEqual(assess_batch_job(job(), PROFILE, ["agent"])["decision"], "excluded")


class BatchCollectorTests(unittest.TestCase):
    def setUp(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fetch = Mock(return_value=SourcePage([job()], 1, 1, False, []))
        self.manager = BatchCollector(self.root, assess_batch_job, DIRECTIONS, fetch=self.fetch, catalog=lambda: SOURCES)

    def run_batch(self, **changes):
        options = {**self.manager.defaults(), **changes}
        run = self.manager.create(options, PROFILE)
        self.manager.execute(run["id"], PROFILE, set())
        return self.manager.get_run(run["id"])

    def clear_cooldown(self):
        for run in self.manager._state["runs"]:
            for source in run["sources"]:
                source["next_allowed_at"] = None

    def test_full_pipeline_stages_full_jd_without_creating_formal_database(self):
        run = self.run_batch()
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["counts"]["added"], 1)
        records = read_staging(data_directory=self.root)
        self.assertEqual(records[0]["description"], GOOD)
        self.assertEqual(records[0]["batch_screening"]["decision"], "accepted")
        self.assertEqual(records[0]["review_status"], "pending")
        self.assertFalse((self.root / "runtime").exists())
        state_text = self.manager.path.read_text(encoding="utf-8")
        self.assertNotIn("verified_tools", state_text)
        self.assertNotIn(GOOD, state_text)

    def test_zero_passes_does_not_pad_results(self):
        self.fetch.return_value = SourcePage([job("任职要求：3年以上开发经验。使用 Codex 开发内部工具。")], 1, 1, False, [])
        run = self.run_batch()
        self.assertEqual(run["counts"]["excluded"], 1)
        self.assertEqual(read_staging(data_directory=self.root), [])

    def test_uncertain_is_opt_in_and_labeled(self):
        self.fetch.return_value = SourcePage([job("使用 Codex 开发内部工具。")], 1, 1, False, [])
        run = self.run_batch()
        self.assertEqual(run["counts"]["needs_review"], 1)
        self.assertEqual(run["counts"]["added"], 0)
        self.clear_cooldown()
        run = self.run_batch(include_uncertain=True)
        self.assertEqual(run["counts"]["added"], 1)
        self.assertEqual(read_staging(data_directory=self.root)[0]["batch_screening"]["decision"], "needs_review")

    def test_duplicate_and_staging_cap_are_enforced(self):
        self.fetch.return_value = SourcePage([job(), job(GOOD + "编写使用说明。", identifier="2")], 2, 2, False, [])
        run = self.run_batch(staging_limit=1)
        self.assertEqual(run["counts"]["added"], 1)
        self.assertEqual(run["counts"]["limited"], 1)
        self.clear_cooldown()
        run = self.run_batch(staging_limit=1)
        self.assertEqual(run["counts"]["duplicates"], 1)
        self.assertEqual(run["counts"]["added"], 1)

    def test_formal_database_body_duplicate_is_not_staged(self):
        run = self.manager.create(self.manager.defaults(), PROFILE)
        self.manager.execute(run["id"], PROFILE, {body_fingerprint(GOOD)})
        self.assertEqual(self.manager.get_run(run["id"])["counts"]["duplicates"], 1)
        self.assertEqual(read_staging(data_directory=self.root), [])

    def test_source_failure_does_not_stop_other_source_and_persists_cooldown(self):
        self.fetch.side_effect = [BatchSourceError("HTTP 429"), SourcePage([job()], 1, 1, False, [])]
        run = self.run_batch(source_keys=["test:one", "test:two"])
        self.assertEqual(run["status"], "partial_failure")
        self.assertEqual(run["counts"]["added"], 1)
        self.assertIn("429", run["sources"][0]["error"])
        reloaded = BatchCollector(self.root, assess_batch_job, DIRECTIONS, fetch=self.fetch, catalog=lambda: SOURCES)
        with self.assertRaises(BatchBusyError):
            reloaded.create(reloaded.defaults(), PROFILE)

    def test_active_lock_restart_recovery_and_no_automatic_retry(self):
        self.manager.create(self.manager.defaults(), PROFILE)
        with self.assertRaises(BatchBusyError):
            self.manager.create(self.manager.defaults(), PROFILE)
        reloaded = BatchCollector(self.root, assess_batch_job, DIRECTIONS, fetch=self.fetch, catalog=lambda: SOURCES)
        self.assertEqual(reloaded.state()["latest"]["status"], "interrupted")
        self.fetch.assert_not_called()

    def test_invalid_options_or_missing_profile_do_not_make_requests(self):
        for change in [dict(source_keys=["https://example.com"]), dict(source_keys=[]), dict(per_source_limit=101),
                       dict(per_source_limit=True), dict(directions=["random"]), dict(include_uncertain="true")]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.manager.create({**self.manager.defaults(), **change}, PROFILE)
        with self.assertRaises(ValueError):
            self.manager.create(self.manager.defaults(), None)
        self.fetch.assert_not_called()
        self.assertFalse(self.manager.path.exists())

    def test_malformed_history_does_not_get_overwritten(self):
        self.manager.path.parent.mkdir(parents=True)
        self.manager.path.write_text("broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.manager.state()
        self.assertEqual(self.manager.path.read_text(), "broken")


class BatchSourceTests(unittest.TestCase):
    def setUp(self):
        batch_sources._CACHE.clear()
        batch_sources._PAUSED.clear()

    def test_redirects_are_stopped_before_following(self):
        with self.assertRaises(BatchSourceError):
            batch_sources._NoRedirect().redirect_request(None, None, 302, "", {}, "http://127.0.0.1/private")

    @patch("collector.batch_sources.build_opener")
    def test_rate_limit_stops_further_requests_without_retry(self, opener):
        opener.return_value.open.side_effect = HTTPError("https://api.lever.co/", 429, "slow", {}, None)
        for _ in range(2):
            with self.assertRaises(BatchSourceError):
                batch_sources._read_json("https://api.lever.co/test", "lever")
        self.assertEqual(opener.return_value.open.call_count, 1)

    @patch("collector.batch_sources.build_opener")
    def test_successful_public_response_is_cached(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value = b'[]'
        self.assertEqual(batch_sources._read_json("https://api.lever.co/test", "lever"), [])
        self.assertEqual(batch_sources._read_json("https://api.lever.co/test", "lever"), [])
        self.assertEqual(opener.return_value.open.call_count, 1)

    def test_catalog_is_reviewed_sources_only_and_overseas_opt_in(self):
        sources = list_batch_sources()
        self.assertFalse(any("boss" in source["key"] for source in sources))
        self.assertTrue(all(not source["default_selected"] for source in sources if source["provider"] != "moka"))

    def test_unreviewed_source_is_rejected_before_network(self):
        with patch("collector.batch_sources._read_json") as reader:
            with self.assertRaises(ValueError):
                fetch_source_page("greenhouse:unknown", 30)
            reader.assert_not_called()

    @patch("collector.batch_sources.fetch_public_job_list")
    def test_moka_list_body_is_parsed_without_per_job_requests(self, reader):
        reader.return_value = (2, [dict(id="abc", title="AI工具开发", status="open", orgId="deeproute", description="<p>开发工具</p>"), dict(id="bad")])
        page = fetch_source_page("moka:deeproute", 30)
        self.assertEqual(len(page.jobs), 1)
        self.assertEqual(page.jobs[0].description, "开发工具")
        self.assertEqual(len(page.errors), 1)
        reader.assert_called_once_with(organization_id="deeproute", limit=30)

    @patch("collector.batch_sources._read_json")
    def test_greenhouse_one_response_is_bounded_and_keeps_full_body(self, reader):
        raw = dict(id=1, title="AI tools", content="<p>Full JD</p>", absolute_url="https://example.com/jobs/1")
        reader.return_value = {"jobs": [raw, {**raw, "id": 2}]}
        page = fetch_source_page("greenhouse:anthropic", 1)
        self.assertEqual(page.scanned, 1)
        self.assertTrue(page.truncated)
        self.assertEqual(page.jobs[0].description, "Full JD")
        self.assertIn("content=true", reader.call_args.args[0])

    @patch("collector.batch_sources._read_json")
    def test_lever_uses_bounded_public_list(self, reader):
        reader.return_value = [dict(id="x", text="AI tool engineer", descriptionPlain="Full description", hostedUrl="https://jobs.lever.co/kgroupcompanies/x")]
        page = fetch_source_page("lever:kgroupcompanies", 30)
        self.assertEqual(page.jobs[0].description, "Full description")
        self.assertIn("skip=0&limit=30", reader.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
