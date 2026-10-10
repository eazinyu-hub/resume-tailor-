"""Run the stable, human-readable regression fixture without private data."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.fact_matching import build_fact_match_table
from app.market_profile import extract_requirements, find_similar_jobs, suggest_role_family


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "analysis_regression_cases.json"
WORK_ROOT = Path(__file__).resolve().parents[2] / "work" / "test-saved-regressions"


class SavedRegressionCasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        if cls.suite.get("schema_version") != 1:
            raise AssertionError("Unsupported regression fixture schema")

    def setUp(self):
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=WORK_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def create_database(self, case_id: str = "cases") -> Path:
        database = self.root / f"{case_id}.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                "CREATE TABLE jobs(id INTEGER PRIMARY KEY, title TEXT, description TEXT, "
                "sample_status TEXT DEFAULT 'active', duplicate_of INTEGER)"
            )
            connection.execute(
                "CREATE TABLE job_analyses(job_id INTEGER, role_family TEXT, "
                "analysis_status TEXT, is_current INTEGER)"
            )
        return database

    def test_saved_classification_cases(self):
        for case in self.suite["classification_cases"]:
            with self.subTest(case=case["id"]):
                result = suggest_role_family(case["title"], case["jd"])
                self.assertEqual(result["family"], case["expected_family"], case["bug"])

    def test_saved_requirement_cases(self):
        for case in self.suite["requirement_cases"]:
            with self.subTest(case=case["id"]):
                requirements = extract_requirements(case["jd"])
                actual = {(item["requirement"], item["kind"]) for item in requirements}
                for expected in case["expected"]:
                    self.assertIn((expected["name"], expected["kind"]), actual, case["bug"])
                names = {item["requirement"] for item in requirements}
                self.assertTrue(names.isdisjoint(case["absent"]), case["bug"])

    def test_saved_alternative_cases(self):
        for case in self.suite["alternative_cases"]:
            with self.subTest(case=case["id"]):
                requirements = extract_requirements(case["jd"], collapse_alternatives=True)
                item = next(
                    requirement for requirement in requirements
                    if requirement["requirement"] == case["expected_requirement"]
                )
                self.assertEqual(item["minimum_options"], case["minimum_options"], case["bug"])
                self.assertEqual(
                    [option["name"] for option in item["alternatives"]],
                    case["expected_options"],
                    case["bug"],
                )

    def test_saved_fact_boundary_cases(self):
        for case in self.suite["fact_boundary_cases"]:
            with self.subTest(case=case["id"]):
                database = self.create_database(case["id"])
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute(
                        "INSERT INTO jobs(id,title,description) VALUES (1,?,?)",
                        (case["jd_title"], case["jd"]),
                    )
                    connection.commit()
                facts = self.root / f"facts-{case['id']}"
                facts.mkdir()
                (facts / "fixture-project.json").write_text(
                    json.dumps(case["card"], ensure_ascii=False), encoding="utf-8"
                )
                result = build_fact_match_table(database, facts, 1)
                supported = {item["requirement"] for item in result["items"] if item["supported"]}
                allowed = {item["requirement"] for item in result["items"] if item["allowed_in_resume"]}
                self.assertEqual(supported, set(case["expected_supported"]), case["bug"])
                self.assertTrue(allowed.isdisjoint(case["expected_not_allowed"]), case["bug"])

    def test_saved_similarity_cases(self):
        for case in self.suite["similarity_cases"]:
            with self.subTest(case=case["id"]):
                database = self.create_database(case["id"])
                rows = [case["target"], *case["candidates"]]
                with closing(sqlite3.connect(database)) as connection:
                    connection.executemany(
                        "INSERT INTO jobs(id,title,description) VALUES (:id,:title,:jd)", rows
                    )
                    connection.commit()
                result = find_similar_jobs(database, case["target"]["id"], limit=10)
                actual_ids = [item["id"] for item in result["items"]]
                self.assertEqual(actual_ids, case["expected_ids"], case["bug"])
                self.assertTrue(set(actual_ids).isdisjoint(case["excluded_ids"]), case["bug"])


if __name__ == "__main__":
    unittest.main()
