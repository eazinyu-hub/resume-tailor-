import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from unittest.mock import Mock, patch

from app.collection_gate import DIRECTIONS, assess_batch_job
from collector.batch import BatchBusyError, BatchCollector
from collector.batch_sources import SourcePage
from collector.models import CollectedJob
from collector.scheduler import CollectionScheduler
from collector.staging import read_staging


ROOT = Path(__file__).resolve().parents[2] / "work" / "test-collection-scheduler"
PROFILE = {"schema_version": 1, "education": {"level": "bachelor", "related_major": False},
           "relevant_experience_years": 0, "verified_tools": ["Codex"], "project_count": 1}
GOOD = "使用 Codex 开发自动化内部工具。任职要求：本科及以上，专业不限，经验不限。"
CATALOG = [dict(key="test:one", company="测试公司", default_selected=True)]


class CollectionSchedulerTests(unittest.TestCase):
    def setUp(self):
        ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.time = datetime.now(timezone.utc)
        self.page = SourcePage([CollectedJob(title="AI工具开发", description=GOOD, source_id="mock_local")], 1, 1, False, [])
        self.fetch = Mock(return_value=self.page)
        self.profile = Mock(return_value=PROFILE)
        self.fingerprints = Mock(return_value=set())
        self.batch = BatchCollector(self.root, assess_batch_job, DIRECTIONS, fetch=self.fetch, catalog=lambda: CATALOG)
        self.scheduler = self.new_scheduler()
        self.addCleanup(self.scheduler.stop)
        self.options = {**self.batch.defaults(), "per_source_limit": 10, "staging_limit": 5}

    def new_scheduler(self):
        return CollectionScheduler(self.batch, self.profile, self.fingerprints, clock=lambda: self.time, tick_seconds=.01)

    def advance(self, minutes):
        self.time += timedelta(minutes=minutes)

    def test_default_paused_and_no_schedule_file_created_by_read(self):
        self.assertFalse(self.scheduler.state()["enabled"])
        self.scheduler.tick()
        self.fetch.assert_not_called()
        self.assertFalse(self.scheduler.path.exists())

    def test_enabled_schedule_waits_then_reuses_pipeline_and_limits(self):
        state = self.scheduler.configure(60, self.options)
        self.assertEqual(state["next_run_at"], (self.time + timedelta(hours=1)).isoformat())
        self.scheduler.tick()
        self.advance(59)
        self.scheduler.tick()
        self.fetch.assert_not_called()
        self.advance(1)
        self.scheduler.tick()
        self.fetch.assert_called_once_with("test:one", 10)
        run = self.batch.state()["latest"]
        self.assertEqual(run["trigger"], "scheduled")
        self.assertEqual(run["counts"]["added"], 1)
        self.assertEqual(run["settings"]["staging_limit"], 5)
        self.assertEqual(self.scheduler.state()["last_run_id"], run["id"])
        self.assertEqual(read_staging(data_directory=self.root)[0]["review_status"], "pending")
        self.assertFalse((self.root / "runtime").exists())
        self.assertEqual(self.profile.call_count, 2)  # Enable + fresh facts at execution.
        self.assertEqual(self.batch.state()["settings"]["per_source_limit"], 30)  # Do not overwrite manual configuration.

    def test_pause_prevents_new_runs_and_retains_settings(self):
        self.scheduler.configure(360, self.options)
        self.scheduler.pause()
        self.advance(1000)
        self.scheduler.tick()
        self.fetch.assert_not_called()
        state = self.new_scheduler().state()
        self.assertFalse(state["enabled"])
        self.assertIsNone(state["next_run_at"])
        self.assertEqual(state["options"], self.options)

    def test_resume_resets_deadline_without_immediate_fetch(self):
        self.scheduler.configure(60, self.options)
        self.scheduler.pause()
        self.advance(80)
        self.scheduler.configure(60, self.options)
        self.scheduler.tick()
        self.assertEqual(self.scheduler.state()["next_run_at"], (self.time + timedelta(hours=1)).isoformat())
        self.fetch.assert_not_called()

    def test_manual_settings_changes_do_not_change_schedule_snapshot(self):
        self.scheduler.configure(60, self.options)
        self.options["per_source_limit"] = 100
        self.batch.create(self.options, PROFILE)
        self.assertEqual(self.scheduler.state()["options"]["per_source_limit"], 10)

    def test_manual_active_run_defers_instead_of_starting_another(self):
        self.scheduler.configure(60, self.options)
        self.batch.create(self.options, PROFILE)
        self.advance(60)
        self.scheduler.tick()
        state = self.scheduler.state()
        self.assertEqual(state["last_event"]["kind"], "deferred")
        self.assertEqual(state["next_run_at"], (self.time + timedelta(minutes=1)).isoformat())
        self.fetch.assert_not_called()

    def test_source_cooldown_is_honored(self):
        self.scheduler.configure(60, self.options)
        self.advance(60)
        until = (self.time + timedelta(minutes=25)).isoformat()
        with patch.object(self.batch, "create", side_effect=BatchBusyError("冷却", retry_at=until)):
            self.scheduler.tick()
        self.assertEqual(self.scheduler.state()["next_run_at"], until)
        self.fetch.assert_not_called()

    def test_restart_skips_missed_intervals_and_preserves_future_deadline(self):
        self.scheduler.configure(60, self.options)
        self.advance(20)
        scheduler = self.new_scheduler()
        scheduler.recover()
        self.assertEqual(scheduler.state()["next_run_at"], (self.time + timedelta(minutes=40)).isoformat())
        self.advance(200)
        scheduler = self.new_scheduler()
        scheduler.recover()
        scheduler.tick()
        self.assertEqual(scheduler.state()["last_event"]["kind"], "missed_skipped")
        self.assertEqual(scheduler.state()["next_run_at"], (self.time + timedelta(minutes=60)).isoformat())
        self.fetch.assert_not_called()

    def test_overdue_tick_executes_once_not_every_missed_interval(self):
        self.scheduler.configure(60, self.options)
        self.advance(24 * 60)
        self.scheduler.tick()
        self.scheduler.tick()
        self.fetch.assert_called_once()

    def test_pause_is_responsive_during_run_and_double_tick_does_not_duplicate(self):
        self.scheduler.configure(60, self.options)
        self.advance(60)
        entered, release = Event(), Event()
        def fetch(key, limit):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test timed out")
            return self.page
        self.fetch.side_effect = fetch
        worker = Thread(target=self.scheduler.tick)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.scheduler.tick()
            self.scheduler.pause()
            self.assertFalse(self.scheduler.state()["enabled"])
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.fetch.assert_called_once()
        self.assertFalse(self.scheduler.state()["enabled"])
        self.assertIsNone(self.scheduler.state()["next_run_at"])
        self.assertEqual(self.scheduler.state()["last_result"]["status"], "completed")

    def test_invalid_config_and_missing_profile_do_not_enable_schedule(self):
        for value in (0, 1, 10, True, "60", 120):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.scheduler.configure(value, self.options)
        with self.assertRaises(ValueError):
            self.scheduler.configure(60, {**self.options, "source_keys": ["boss_zhipin"]})
        self.profile.return_value = None
        with self.assertRaises(ValueError):
            self.scheduler.configure(60, self.options)
        self.assertFalse(self.scheduler.path.exists())

    def test_missing_profile_at_due_time_pauses_safely(self):
        self.scheduler.configure(60, self.options)
        self.advance(60)
        self.profile.return_value = None
        with self.assertLogs("collector.scheduler", level="ERROR"):
            self.scheduler.tick()
        self.assertFalse(self.scheduler.state()["enabled"])
        self.fetch.assert_not_called()

    def test_network_failure_records_result_without_retry_burst(self):
        self.scheduler.configure(60, self.options)
        self.advance(60)
        self.fetch.side_effect = RuntimeError("HTTP 429")
        self.scheduler.tick()
        self.scheduler.tick()
        self.assertEqual(self.scheduler.state()["last_result"]["status"], "failed")
        self.fetch.assert_called_once()

    def test_corrupted_configuration_does_not_start_or_overwrite_file(self):
        self.scheduler.path.parent.mkdir(parents=True)
        self.scheduler.path.write_text("broken", encoding="utf-8")
        with self.assertLogs("collector.scheduler", level="ERROR"):
            self.scheduler.start()
        self.assertIsNone(self.scheduler.thread)
        self.assertIsNotNone(self.scheduler.runtime_error)
        self.assertEqual(self.scheduler.path.read_text(), "broken")
        self.fetch.assert_not_called()

    def test_write_failure_rolls_back_enable(self):
        with patch.object(self.scheduler, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.scheduler.configure(60, self.options)
        self.assertFalse(self.scheduler.state()["enabled"])

    def test_background_loop_runs_without_browser_and_stops(self):
        self.scheduler.configure(60, self.options)
        self.scheduler.start()
        original = self.scheduler.thread
        self.scheduler.start()
        self.assertIs(self.scheduler.thread, original)
        self.advance(60)
        done = Event()
        original_execute = self.batch.execute
        def execute(*args):
            original_execute(*args)
            done.set()
        with patch.object(self.batch, "execute", side_effect=execute):
            self.assertTrue(done.wait(2))
        self.scheduler.stop()
        self.assertFalse(original.is_alive())
        self.fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
