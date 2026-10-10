"""Candidate wording consists only of selected, verifiable source sentences."""

from pathlib import Path
import re

from app.fact_matching import _load_cards, verified_project_facts

ANGLES = (
    ("自动化侧重点", r"导入|去重|自动化|数据处理|批量|工作流"),
    ("AI 全栈侧重点", r"前端|后端|react|fastapi|sqlite|数据库|API|导出"),
    ("Vibe Coding 侧重点", r"codex|claude\\s*code|git|测试|调试|迭代|验收|构建"),
)


def build_project_candidate_descriptions(facts_dir: Path, project_id: str) -> dict:
    card = next((card for card in _load_cards(facts_dir) if card["project_id"] == project_id), None)
    if card is None:
        return {"status": "project_not_found", "candidates": []}
    facts = verified_project_facts(card)
    if not facts:
        return {"status": "no_verified_facts", "project_id": project_id, "candidates": []}
    candidates = []
    for label, pattern in ANGLES:
        chosen = [fact for fact in facts if re.search(pattern, fact["content"], re.I)][:3]
        evidence = list(dict.fromkeys(fact["content"] for fact in chosen))
        allowed = bool(evidence) and card.get("fact_status") == "confirmed"
        candidates.append({"project_id": project_id, "project_name": card.get("project_name", ""),
                           "label": label, "summary": " ".join(evidence), "evidence": evidence,
                           "fact_ids": [fact["fact_id"] for fact in chosen], "allowed_in_resume": allowed,
                           "write_reason": "缺少此方向的已验证事实" if not evidence else
                           "项目卡已确认，可引用这些原始事实" if allowed else "草稿事实，仅供核对，尚不能写入简历"})
    return {"status": "ready", "project_id": project_id, "project_name": card.get("project_name"),
            "fact_status": card.get("fact_status"), "candidates": candidates}
