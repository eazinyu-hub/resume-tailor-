import json
import tempfile
import unittest
from pathlib import Path

from app.candidate_fit import evaluate_candidate_fit, load_candidate_fit_profile


PROFILE = {
    "schema_version": 1,
    "education": {"level": "bachelor", "related_major": False},
    "relevant_experience_years": 0,
    "project_count": 3,
    "verified_tools": ["Claude Code", "Codex", "ChatGPT"],
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = REPOSITORY_ROOT / "work" / "test-candidate-fit"


class CandidateFitTests(unittest.TestCase):
    def test_recommends_entry_role_that_values_projects(self) -> None:
        result = evaluate_candidate_fit(
            "初级 AI 工具开发",
            (
                "接受应届和非科班候选人，使用 Codex 开发自动化工具。"
                "有个人项目、GitHub 或可演示 Demo 即可。"
            ),
            PROFILE,
        )

        self.assertEqual(result["level"], "recommended")
        self.assertGreaterEqual(result["score"], 65)
        self.assertTrue(any("个人项目" in item for item in result["strengths"]))

    def test_marks_related_major_requirement_as_personal_barrier(self) -> None:
        result = evaluate_candidate_fit(
            "AI 研发效能工程师",
            (
                "本科及以上，计算机、人工智能、数据科学、软件工程或相关专业。"
                "熟练使用 Claude Code、Codex，有 AI Agent 相关经验。"
            ),
            PROFILE,
        )

        self.assertEqual(result["level"], "low_priority")
        self.assertTrue(any("专业不匹配" in item for item in result["barriers"]))
        self.assertIn("不是录用概率", result["score_note"])

    def test_uses_minimum_year_in_experience_range(self) -> None:
        one_to_three = evaluate_candidate_fit(
            "AI 全栈工程师",
            "要求 1-3 年开发经验，使用 Codex 完成功能开发。",
            PROFILE,
        )
        three_to_five = evaluate_candidate_fit(
            "AI 全栈工程师",
            "要求 3-5 年开发经验，使用 Codex 完成功能开发。",
            PROFILE,
        )

        self.assertGreater(one_to_three["score"], three_to_five["score"])
        self.assertIn("至少要求 1 年", one_to_three["barriers"][0])

    def test_marks_masters_degree_as_hard_barrier_for_bachelor_profile(self) -> None:
        result = evaluate_candidate_fit(
            "端侧 AI 开发工程师",
            (
                "硕士及以上学历，计算机、人工智能等相关专业优先。"
                "熟悉 Python、PyTorch 和端侧推理框架。"
            ),
            PROFILE,
        )

        self.assertEqual(result["level"], "low_priority")
        self.assertTrue(any("硕士及以上" in item for item in result["barriers"]))

    def test_downranks_ai_content_role_outside_vibe_coding_direction(self) -> None:
        result = evaluate_candidate_fit(
            "新媒体编导（AI 短视频方向）",
            (
                "使用 AI 工具完成脚本、分镜和动画制作，"
                "有个人项目或上线作品优先。"
            ),
            PROFILE,
        )

        self.assertEqual(result["level"], "low_priority")
        self.assertTrue(any("不属于当前" in item for item in result["barriers"]))

    def test_loads_only_versioned_private_profile(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary_directory:
            path = Path(temporary_directory) / "fit-profile.json"
            path.write_text(json.dumps(PROFILE), encoding="utf-8")

            loaded = load_candidate_fit_profile(path)

        self.assertEqual(loaded, PROFILE)

    def test_required_preferred_and_unrestricted_major_are_different(self) -> None:
        for description, kind in (
            ("任职要求：计算机相关专业。使用 Codex。", "required"),
            ("任职要求：计算机相关专业优先。使用 Codex。", "preferred"),
            ("加分项：\n计算机相关专业。", "preferred"),
            ("不要求计算机相关专业。使用 Codex。", "unrestricted"),
            ("非计算机相关专业也可以。使用 Codex。", "unrestricted"),
        ):
            with self.subTest(description=description):
                result = evaluate_candidate_fit("AI 工具开发", description, PROFILE)
                condition = next(c for c in result["requirements"] if c["category"] == "major")
                self.assertEqual(condition["kind"], kind)
                self.assertIn(condition["evidence"], description)
                self.assertEqual(
                    any("专业不匹配" in item for item in result["barriers"]),
                    kind == "required",
                )

    def test_optional_major_does_not_relax_required_masters_degree(self) -> None:
        result = evaluate_candidate_fit(
            "AI 工具开发", "硕士及以上学历，计算机相关专业优先。使用 Codex。", PROFILE,
        )
        conditions = {c["category"]: c for c in result["requirements"]}
        self.assertEqual(conditions["education"]["kind"], "required")
        self.assertEqual(conditions["major"]["kind"], "preferred")
        self.assertTrue(any("硕士" in item for item in result["barriers"]))
        self.assertFalse(any("专业不匹配" in item for item in result["barriers"]))

    def test_degree_alternatives_and_degree_preference(self) -> None:
        for description, expected_gap in (
            ("硕士、博士应届毕业生", True),
            ("本科或硕士学历", False),
            ("本科及以上学历，硕士优先", False),
            ("本科及以上学历、硕士优先", False),
            ("加分项：硕士及以上学历", False),
        ):
            with self.subTest(description=description):
                result = evaluate_candidate_fit("AI 工具开发", description, PROFILE)
                self.assertEqual(
                    any("学历不符合" in item for item in result["barriers"]), expected_gap,
                )

    def test_missing_profile_education_is_unknown_not_unqualified(self) -> None:
        profile = {**PROFILE, "education": {}}
        result = evaluate_candidate_fit(
            "AI 工具开发", "本科及以上学历。熟练使用 Codex。", profile,
        )
        self.assertFalse(any("学历不符合" in item for item in result["barriers"]))
        self.assertEqual(result["level"], "insufficient_information")
        self.assertIsNone(result["score"])

    def test_school_is_not_assumed_and_preference_does_not_penalize(self) -> None:
        profile = {**PROFILE, "education": {**PROFILE["education"], "elite_school": False}}
        required = evaluate_candidate_fit("AI 工具开发", "要求985/211院校。使用 Codex。", profile)
        preferred = evaluate_candidate_fit("AI 工具开发", "985/211院校优先。使用 Codex。", profile)
        unknown = evaluate_candidate_fit("AI 工具开发", "要求985/211院校。使用 Codex。", PROFILE)
        self.assertTrue(required["barriers"])
        self.assertFalse(preferred["barriers"])
        self.assertFalse(unknown["barriers"])
        self.assertEqual(unknown["level"], "insufficient_information")

    def test_es6_and_company_history_are_not_experience_years(self) -> None:
        result = evaluate_candidate_fit(
            "AI 全栈工程师",
            "公司介绍：公司成立10年以上。\n任职要求：熟悉 ES6+，使用 Codex，展示个人项目。",
            PROFILE,
        )
        self.assertFalse(any("年相关经验" in item for item in result["barriers"]))
        self.assertFalse(any(c["category"] == "experience" for c in result["requirements"]))
        self.assertTrue(any("未明确经验" in item for item in result["uncertainties"]))

    def test_experience_bonus_and_exception_are_not_absolute_minimum(self) -> None:
        for description, kind in (
            ("任职要求：3年以上开发经验。使用 Codex。", "required"),
            ("加分项：3年以上开发经验。", "preferred"),
            ("3年以上开发经验优先。", "preferred"),
            ("1-3年开发经验，优秀应届生也可以。使用 Codex。", "conditional"),
            ("3年以上开发经验，可放宽。", "conditional"),
        ):
            with self.subTest(description=description):
                result = evaluate_candidate_fit("AI 全栈工程师", description, PROFILE)
                condition = next(c for c in result["requirements"] if c["category"] == "experience")
                self.assertEqual(condition["kind"], kind)
                self.assertEqual(
                    any("年相关经验" in item for item in result["barriers"]), kind == "required",
                )
                if kind == "conditional":
                    self.assertEqual(result["level"], "insufficient_information")

    def test_chinese_years_and_no_experience_limit(self) -> None:
        required = evaluate_candidate_fit("AI 全栈工程师", "三年以上开发经验。", PROFILE)
        self.assertTrue(any("3 年" in item for item in required["barriers"]))
        unrestricted = evaluate_candidate_fit(
            "AI 工具开发", "学历不限，专业不限，经验不限。使用 Codex，展示个人项目。", PROFILE,
        )
        self.assertFalse(unrestricted["barriers"])
        self.assertTrue(all(c["kind"] == "unrestricted" for c in unrestricted["requirements"]))

    def test_alternative_major_path_is_not_rejected_as_wrong_major(self) -> None:
        result = evaluate_candidate_fit(
            "AI 全栈工程师",
            "计算机科学相关专业，或具有全栈开发经验。使用 Codex。",
            PROFILE,
        )
        condition = next(c for c in result["requirements"] if c["category"] == "major")
        self.assertEqual(condition["kind"], "conditional")
        self.assertFalse(any("专业不匹配" in item for item in result["barriers"]))

    def test_sparse_description_does_not_get_default_fifty_points(self) -> None:
        result = evaluate_candidate_fit(
            "AI工作流搭建工程师", "负责内部工作流搭建，认真负责。", PROFILE,
        )
        self.assertIsNone(result["score"])
        self.assertEqual(result["level"], "insufficient_information")
        self.assertEqual(len(result["uncertainties"]), 3)

    def test_broad_major_choices_need_more_than_a_non_cs_flag(self) -> None:
        result = evaluate_candidate_fit(
            "AI 工具开发", "计算机、金融工程、经济等相关专业均可。使用 Codex。", PROFILE,
        )
        self.assertFalse(any("专业不匹配" in item for item in result["barriers"]))
        self.assertEqual(result["level"], "insufficient_information")

    def test_unverified_practical_experience_is_not_inferred_from_job_count(self) -> None:
        result = evaluate_candidate_fit(
            "AI工具开发", "有AI Agent落地经验。使用 Codex。", PROFILE,
        )
        self.assertEqual(result["level"], "insufficient_information")
        self.assertTrue(any("结合项目事实" in item for item in result["uncertainties"]))

    def test_bonus_research_and_negated_tools_do_not_change_hard_score(self) -> None:
        result = evaluate_candidate_fit(
            "初级AI工具开发", "不要求 Codex。加分项：有模型训练经验。", PROFILE,
        )
        self.assertFalse(any("工具匹配" in item for item in result["strengths"]))
        self.assertFalse(any("算法研究" in item for item in result["barriers"]))

    def test_all_assessment_evidence_is_from_original_description(self) -> None:
        description = "本科及以上学历，计算机相关专业优先。\n3年开发经验，优秀应届生也可以。"
        result = evaluate_candidate_fit("AI 工具开发", description, PROFILE)
        self.assertTrue(result["requirements"])
        for item in result["requirements"]:
            self.assertIn(item["evidence"], description)


if __name__ == "__main__":
    unittest.main()
