"""Evidence matching that distinguishes implementation, context, plans and restrictions."""

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from app.jd_signals import normalize, positive_match, requirement_match_count
from app.market_profile import extract_requirements

WRITABLE_STATUS = "已验证"


def _load_cards(facts_dir: Path) -> list[dict]:
    cards = []
    for path in sorted(facts_dir.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(card, dict) and card.get("project_id"):
            cards.append(card)
    return cards


def _fact_items(card: dict) -> list[dict]:
    items = []
    def add(entries, field, direct=False, forced_status=None):
        for index, entry in enumerate(entries if isinstance(entries, list) else []):
            if isinstance(entry, str):
                entry = {"content": entry}
            if not isinstance(entry, dict):
                continue
            content = entry.get("content", "")
            if field == "technology_and_ai_tools":
                content = str(entry.get("name", "")) + "：" + str(entry.get("usage", ""))
            if not isinstance(content, str) or not content.strip():
                continue
            status = forced_status or entry.get("evidence_status", "需要补充")
            if entry.get("level") == "未实际使用":
                status = "禁止写入简历"
            items.append({"content": content, "status": status, "direct": direct,
                          "source_field": field, "fact_id": f"{card.get('project_id')}/{field}/{index}"})
    for field in ("completed_features", "debugging_methods", "technology_and_ai_tools"):
        add(card.get(field, []), field, direct=True)
    for field in ("real_problem", "errors_and_failures"):
        add(card.get(field, []), field)
    add(card.get("do_not_exaggerate", []), "do_not_exaggerate", forced_status="禁止写入简历")
    completion = card.get("completion") or {}
    if isinstance(completion, dict):
        add(completion.get("completed_scope", []), "completed_scope", direct=True)
        add(completion.get("remaining_scope", []), "remaining_scope", forced_status="计划实现")
    return items


def supports_requirement(fact: dict, requirement: dict) -> bool:
    text = normalize(fact["content"])
    if not fact["direct"] or fact["status"] != WRITABLE_STATUS:
        return False
    if fact["source_field"] != "technology_and_ai_tools" and re.search(
        r"岗位方向|方向建议|确认分类|关键词(?:频率|统计)|统计.{0,18}关键词", text
    ):
        return False
    # JD classification is not evidence of having developed the technologies named in it.
    if re.search(r"Agent|RAG|MCP|Prompt|工作流|运营", requirement["requirement"], re.I):
        if re.search(r"岗位|JD|投递|分类|求职", text, re.I):
            return False
    return bool(positive_match(requirement["expression"], text))


def verified_project_facts(card: dict) -> list[dict]:
    return [fact for fact in _fact_items(card) if fact["direct"] and fact["status"] == WRITABLE_STATUS
            and not re.search(r"尚未|暂未|未实现|未部署|计划实现|禁止|不要写成", fact["content"])]


def build_fact_match_table(database_path: Path, facts_dir: Path, job_id: int) -> dict:
    with closing(sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute("SELECT id, title, description FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return {"status": "job_not_found", "items": []}
    cards = _load_cards(facts_dir)
    items = []
    for requirement in extract_requirements(row[2], collapse_alternatives=True):
        matched = []
        # Project accomplishments cannot substantiate a personal degree or years of employment.
        academic = requirement["category"] == "学历与经验"
        for card in cards:
            for fact in _fact_items(card):
                if academic or not re.search(requirement["expression"], normalize(fact["content"]), re.I):
                    continue
                supported = supports_requirement(fact, requirement)
                allowed = supported and card.get("fact_status") == "confirmed"
                if fact["status"] in ("计划实现", "禁止写入简历", "需要补充"):
                    reason = f"事实状态为“{fact['status']}”，不能作为已完成能力"
                elif not supported:
                    reason = "属于背景、失败或否定表述，不能证明已实现该能力"
                elif not allowed:
                    reason = "项目事实卡仍是草稿，需先确认"
                else:
                    reason = "项目卡已确认，且有已验证实现事实"
                matched.append({"project_id": card["project_id"], "project_name": card.get("project_name", "未命名项目"),
                                "fact": fact["content"], "fact_id": fact["fact_id"], "source_field": fact["source_field"],
                                "evidence_status": fact["status"], "supports_requirement": supported,
                                "allowed_in_resume": allowed, "write_reason": reason})
        matched.sort(key=lambda x: (not x["supports_requirement"], not x["allowed_in_resume"], x["fact_id"]))
        supported = [x for x in matched if x["supports_requirement"]]
        minimum = requirement.get("minimum_options", 1)
        option_count = requirement_match_count(requirement, [x["fact"] for x in supported])
        is_supported = option_count >= minimum
        allowed = requirement_match_count(requirement, [x["fact"] for x in supported if x["allowed_in_resume"]]) >= minimum
        if allowed:
            gap = "有可引用的已验证事实；保留原事实范围，不推断熟练程度或业务指标"
        elif supported and is_supported:
            gap = "有直接项目事实，但尚未确认可写入简历"
        elif supported:
            gap = f"至少需要 {minimum} 种，目前只有 {option_count} 种直接事实；请核对剩余选项"
        elif academic:
            gap = "需要核对本人学历、经历或出勤条件，项目事实不能证明这类要求"
        elif matched:
            gap = "只有背景/待补充/计划/禁止内容，未找到可证明已实现能力的事实"
        else:
            gap = "当前没有找到对应项目事实；有真实经历再补充，不应直接写入"
        if requirement.get("alternatives"):
            gap += "。可选项：" + "、".join(x["name"] for x in requirement["alternatives"])
        items.append({k: requirement[k] for k in ("requirement", "category", "kind", "jd_evidence")} |
                     {"matched_facts": matched[:4], "strength": "强" if is_supported else "弱" if supported else "无",
                      "gap": gap, "allowed_in_resume": allowed, "supported": is_supported,
                      "minimum_options": minimum,
                      "alternative_options": [x["name"] for x in requirement.get("alternatives", [])]})
    assessed = [x for x in items if x["category"] != "学历与经验" and x["kind"] != "加分项"]
    count = sum(x["supported"] for x in assessed)
    return {"status": "ready", "job_id": job_id, "job_title": row[1], "job_description": row[2],
            "card_count": len(cards), "items": items,
            "summary": {"supported": count, "total": len(assessed),
                        "coverage": round(100 * count / len(assessed), 1) if assessed else None,
                        "note": "直接项目事实覆盖率；不含加分项和学历条件，不是录用概率。草稿事实仍需确认。"}}
