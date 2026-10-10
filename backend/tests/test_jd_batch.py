import unittest

from app.jd_batch import build_batch_preview, split_batch_jds


class BatchJdSplitterTests(unittest.TestCase):
    def test_splits_numbered_chinese_job_blocks(self) -> None:
        text = """
岗位一，AI工具开发
岗位职责：
1、开发内部工具。
岗位要求：
会使用 Codex。

岗位二：AI Agent产品运营
岗位职责：
跟进 Agent 产品落地。
岗位要求：
具备产品运营经验。
"""

        jobs = split_batch_jds(text)

        self.assertEqual([job["title"] for job in jobs], [
            "AI工具开发",
            "AI Agent产品运营",
        ])
        self.assertIn("岗位职责：", jobs[0]["description"])
        self.assertIn("岗位要求：", jobs[0]["description"])
        self.assertNotIn("岗位二", jobs[0]["description"])

    def test_accepts_arabic_numbered_markers(self) -> None:
        jobs = split_batch_jds(
            "岗位1 - Vibe Coding工程师\n负责完整开发闭环。\n"
            "岗位2、Agent开发\n负责智能体工作流。"
        )

        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[1], {
            "title": "Agent开发",
            "description": "负责智能体工作流。",
        })

    def test_empty_input_returns_empty_list(self) -> None:
        self.assertEqual(split_batch_jds(" \n "), [])

    def test_rejects_unmarked_text_instead_of_guessing(self) -> None:
        with self.assertRaisesRegex(ValueError, "未识别"):
            split_batch_jds("AI工具开发\n负责开发内部工具。")

    def test_rejects_job_without_description(self) -> None:
        with self.assertRaisesRegex(ValueError, "缺少 JD 正文"):
            split_batch_jds("岗位一：AI工具开发")

    def test_builds_save_free_batch_preview(self) -> None:
        preview = build_batch_preview(
            "岗位一：AI工具开发\n开发内部工具。\n"
            "岗位二：Agent开发\n开发智能体。"
        )

        self.assertEqual(preview, {
            "count": 2,
            "items": [
                {
                    "position": 1,
                    "title": "AI工具开发",
                    "description_length": 7,
                },
                {
                    "position": 2,
                    "title": "Agent开发",
                    "description_length": 6,
                },
            ],
        })


if __name__ == "__main__":
    unittest.main()
