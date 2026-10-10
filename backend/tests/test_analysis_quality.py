"""Synthetic regression cases; never contain private JDs or personal resume data."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from app.market_profile import suggest_role_family, extract_requirements, get_role_profiles, find_similar_jobs, compare_job_to_market
from app.fact_matching import build_fact_match_table
from app.agent_v1 import build_agent_v1
from app.candidate_descriptions import build_project_candidate_descriptions


class AnalysisQualityTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[2] / 'work' / 'test-analysis-quality'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'sample.sqlite3'
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, title TEXT, description TEXT, sample_status TEXT DEFAULT 'active', duplicate_of INTEGER)")
            c.execute('CREATE TABLE job_analyses(job_id INTEGER, role_family TEXT, analysis_status TEXT, is_current INTEGER)')
        self.facts = self.root / 'facts'
        self.facts.mkdir()

    def job(self, title, body):
        with closing(sqlite3.connect(self.db)) as c:
            result = c.execute('INSERT INTO jobs(title,description) VALUES (?,?)', (title, body)).lastrowid
            c.commit()
            return result

    def card(self, **overrides):
        card = {'project_id': 'test', 'project_name': '合成示例项目', 'fact_status': 'confirmed',
                'completed_features': [{'content': '用 Python 完成接口开发。', 'evidence_status': '已验证'}]}
        card.update(overrides)
        (self.facts / 'test.json').write_text(json.dumps(card, ensure_ascii=False), encoding='utf-8')

    def test_titles_and_actual_duties_outweigh_mentions_of_coworkers(self):
        for title, body, family in [
            ('AI 智能体开发', '与产品经理合作，开发 MCP Server。', 'agent_application'),
            ('Agent 产品实习生', '消费者研究，用 Python 做竞品分析。', 'ai_product_operations'),
            ('上下文工程师', '设计 Prompt 和评测方案。', 'agent_application'),
            ('Vibe Coding 工程师', '开发 Web 工具。', 'vibe_coding_fullstack'),
            ('AI Coding 开发工程师', '参与 Agent 推理与行动循环研发。', 'agent_application'),
            ('普通项目助理', '认真负责。', 'unclassified'),
        ]:
            with self.subTest(title=title):
                self.assertEqual(suggest_role_family(title, body)['family'], family)

    def test_negation_bonus_and_education_are_not_simple_keyword_mentions(self):
        requirements = extract_requirements('任职要求：无需 Python 经验。使用自动化处理数据。加分项：有 MCP Server 和 Dify 经验。')
        names = {x['requirement']: x for x in requirements}
        self.assertNotIn('Python', names)
        self.assertNotIn('计算机/AI相关专业', names)
        self.assertEqual(names['MCP']['kind'], '加分项')
        self.assertIn('Dify', names)

    def test_same_direction_alone_is_not_enough_and_scores_are_bounded(self):
        target = self.job('全栈工程师', '使用 Python、React 进行前端开发。')
        self.job('全栈工程师', '负责品牌活动执行。')
        peer = self.job('全栈工程师', '使用 Python、React 进行前端开发及测试。')
        result = find_similar_jobs(self.db, target)
        self.assertEqual([x['id'] for x in result['items']], [peer])
        self.assertTrue(0 < result['items'][0]['score'] <= 100)

    def test_duplicate_target_can_be_read_but_not_retrieved_as_reference(self):
        self.job('原版全栈', 'Python React 前端开发。')
        target = self.job('重发全栈', 'Python  React\n前端开发。')
        self.assertEqual(find_similar_jobs(self.db, target)['items'], [])
        self.assertEqual(get_role_profiles(self.db, exclude_job_id=target)['sample_count'], 0)
        self.assertEqual(compare_job_to_market(self.db, target)['baseline_count'], 0)

    def test_forbidden_planned_and_problem_context_never_support_ability(self):
        target = self.job('Agent工程师', '任职要求：使用 Cursor，开发 Agent、RAG、MCP 并部署。')
        self.card(
            real_problem=[{'content': '帮助投递 Agent 和 RAG 岗位。', 'evidence_status': '已验证'}],
            technology_and_ai_tools=[{'name': 'Cursor', 'usage': '未使用', 'evidence_status': '禁止写入简历'}],
            completion={'remaining_scope': [{'content': 'MCP 与部署', 'evidence_status': '已验证'}]},
            do_not_exaggerate=[{'content': '不要写成已部署', 'evidence_status': '已验证'}])
        result = build_fact_match_table(self.db, self.facts, target)
        for item in result['items']:
            self.assertFalse(item['allowed_in_resume'], item['requirement'])
            self.assertNotEqual(item['strength'], '强')
            self.assertNotIn('已具备可写入', item['gap'])

    def test_candidate_cannot_add_capabilities_not_present_in_its_evidence(self):
        self.card()
        result = build_project_candidate_descriptions(self.facts, 'test')
        for candidate in result['candidates']:
            self.assertEqual(candidate['summary'], ' '.join(candidate['evidence']))
        text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn('已上线', text)
        self.assertNotIn('简历草稿', text)

    def test_explicit_one_of_languages_is_one_requirement(self):
        target = self.job('AI开发', '任职要求：接触过至少一种编程语言，例如Python、Java、JavaScript。')
        self.card()
        result = build_fact_match_table(self.db, self.facts, target)
        self.assertEqual(result['summary']['total'], 1)
        self.assertEqual(result['summary']['supported'], 1)
        self.assertTrue(result['items'][0]['allowed_in_resume'])
        self.assertEqual(result['items'][0]['alternative_options'], ['Python', 'JavaScript', 'Java'])

    def test_two_tools_requires_two_distinct_verified_tools(self):
        target = self.job('AI开发', '任职要求：使用至少2种AI编程工具（Codex、Cursor、Claude Code）。')
        self.card(technology_and_ai_tools=[{'name': 'Codex', 'usage': '开发调试', 'evidence_status': '已验证'}])
        result = build_fact_match_table(self.db, self.facts, target)
        requirement = next(x for x in result['items'] if x['category'] == 'AI 工具')
        self.assertFalse(requirement['supported'])
        self.assertFalse(requirement['allowed_in_resume'])
        self.assertIn('目前只有 1 种', requirement['gap'])

    def test_api_keeps_incomplete_alternative_group_unmatched_and_empty_coverage_null(self):
        # Import main only in an isolated process: its startup initializes a database.
        environment = {**os.environ, 'DATA_DIR': str(self.root / 'api-data'), 'PYTHONDONTWRITEBYTECODE': '1'}
        code = '''
import sqlite3
from unittest.mock import patch
from app import main
with sqlite3.connect(main.DB_PATH) as connection:
    connection.execute("INSERT INTO jobs(title, description) VALUES (?, ?)", ("合成岗位", "负责日常事项"))
partial = {"items": [{"requirement": "AI 工具（至少 2 种）", "category": "AI 工具", "kind": "任职要求", "allowed_in_resume": False,
    "jd_evidence": "至少两种工具", "gap": "目前只有一种", "matched_facts": [{"allowed_in_resume": True, "project_name": "合成项目", "fact": "使用 Codex"}]}]}
with patch.object(main, "preview_latest_resume", return_value={"status": "ready", "paragraphs": ["使用 Codex"]}), patch.object(main, "build_fact_match_table", return_value=partial):
    assert main.match_core_requirements(1)["items"][0]["matched"] is False
    assert main.match_job_keywords(1)["coverage"] is None
'''
        subprocess.run([sys.executable, '-B', '-c', code], cwd=Path(__file__).resolve().parents[1],
                       env=environment, check=True, capture_output=True, text=True, encoding='utf-8')

    def test_classification_labels_and_keyword_statistics_are_not_implementation(self):
        target = self.job('工具开发工程师', '任职要求：Python、自动化、Agent 开发。')
        self.card(completed_features=[
            {'content': '实现岗位方向建议与人工确认分类，支持 AI 工具与自动化、Agent 应用等方向。', 'evidence_status': '已验证'},
            {'content': '统计 Python 等关键词频率。', 'evidence_status': '已验证'},
        ])
        result = build_fact_match_table(self.db, self.facts, target)
        self.assertEqual(result['summary']['supported'], 0)

    def test_agent_is_job_specific_and_missing_resume_stays_blocked(self):
        first = self.job('Python工程师', '任职要求：Python 接口开发。')
        second = self.job('Agent工程师', '任职要求：RAG、MCP。加分项：Dify。')
        self.card()
        before = self.db.read_bytes()
        one = build_agent_v1(self.db, self.facts, first, {'status': 'empty'})
        two = build_agent_v1(self.db, self.facts, second, {'status': 'ready'})
        self.assertTrue(one['formal_resume']['blocked'])
        self.assertNotEqual(one['evidence_coverage']['coverage'], two['evidence_coverage']['coverage'])
        self.assertNotEqual(one['self_introduction_preview'], two['self_introduction_preview'])
        self.assertNotIn('完成了本地导入', two['self_introduction_preview'])
        self.assertEqual(two['prompt_package']['current_jd']['description'], '任职要求：RAG、MCP。加分项：Dify。')
        self.assertEqual(self.db.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
