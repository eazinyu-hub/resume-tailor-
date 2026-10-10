"""Build a job-level resume using original resume sections and confirmed project facts."""

from copy import deepcopy


def _verified(entries: object) -> list[dict]:
    if not isinstance(entries, list):
        return []
    return [item for item in entries if isinstance(item, dict) and item.get("evidence_status") == "已验证"]


def choose_candidate(options: list[dict], allowed_fact_ids: set[str], target_family: str) -> dict | None:
    preferred = {
        "ai_tool_automation": "自动化侧重点",
        "vibe_coding_fullstack": "Vibe Coding 侧重点",
        "agent_application": "AI 全栈侧重点",
        "ai_product_operations": "自动化侧重点",
        "internal_intelligence": "AI 全栈侧重点",
        "indie_ai_developer": "Vibe Coding 侧重点",
    }.get(target_family, "AI 全栈侧重点")
    allowed = [option for option in options if option.get("allowed_in_resume")]
    direct = [option for option in allowed if allowed_fact_ids.intersection(option.get("fact_ids", []))]
    eligible = direct or allowed
    if not eligible:
        return None
    chosen = max(eligible, key=lambda option: (
        option.get("label") == preferred,
        len(allowed_fact_ids.intersection(option.get("fact_ids", []))),
        len(option.get("evidence", [])),
    ))
    return {**chosen, "matches_current_jd": chosen in direct}


def build_grounded_resume(
    job_title: str,
    original_resume: dict,
    candidates: list[dict],
    cards: list[dict],
    target_family_label: str,
) -> dict:
    source_sections = original_resume.get("sections") if isinstance(original_resume, dict) else None
    if not isinstance(source_sections, dict) or not candidates:
        return {}
    source = {name: list(values) for name, values in source_sections.items() if isinstance(values, list)}
    confirmed_cards = {card.get("project_id"): card for card in cards if card.get("fact_status") == "confirmed"}

    original_personal = source.get("个人简介", [])
    identity = original_personal[:1]
    contact = [line for line in original_personal[1:3] if "电话" in line or "邮箱" in line or "GitHub" in line]
    project_lines = []
    intro_evidence = []
    for candidate in candidates:
        card = confirmed_cards.get(candidate.get("project_id"), {})
        project_type = card.get("project_type", "项目")
        project_lines.append(f"{candidate.get('project_name', '未命名项目')}｜{project_type}｜{candidate.get('label', '事实版本')}")
        evidence = list(dict.fromkeys(candidate.get("evidence", [])))[:3]
        project_lines.extend(evidence)
        intro_evidence.extend(evidence[:1])

    introduction = f"求职方向：{job_title}。本次按{target_family_label}岗位的侧重点组织以下已确认项目事实。"
    if intro_evidence:
        introduction += "已确认事实包括：" + " ".join(intro_evidence[:2])

    tools = []
    development = []
    for card in confirmed_cards.values():
        for item in _verified(card.get("technology_and_ai_tools")):
            if item.get("level") == "未实际使用":
                continue
            name = str(item.get("name", "")).strip()
            usage = str(item.get("usage", "")).strip()
            if name:
                tools.append(f"{name}：{usage}" if usage else name)
        development.extend(str(item.get("content", "")).strip() for item in _verified(card.get("debugging_methods")))

    sections = {
        "个人简介": identity + [f"求职意向：{job_title}"] + contact + [introduction],
        "教育背景": deepcopy(source.get("教育背景", [])),
        "工作经历": deepcopy(source.get("工作经历", [])),
        "项目经历": project_lines,
        "技术与工具": list(dict.fromkeys(tools)),
        "开发方式": list(dict.fromkeys(item for item in development if item))[:3],
    }
    omitted_projects = max(0, sum("｜个人项目" in line for line in source.get("项目经历", [])) - len(candidates))
    changes = [
        f"个人简介：求职方向调整为“{job_title}”，能力描述仅引用已确认项目事实。",
        f"项目经历：采用 {len(candidates)} 个已确认项目的岗位侧重版本；未从 JD 反推或补写能力。",
        "技术与工具：仅保留已确认事实卡中标记为“已验证”且实际使用的工具。",
    ]
    if omitted_projects:
        changes.append(f"真实性保护：原简历中另有 {omitted_projects} 个项目尚无已确认事实卡，本次未自动写入。")
    if any(not candidate.get("matches_current_jd", False) for candidate in candidates):
        changes.append("岗位缺口：当前已确认项目事实未直接覆盖该 JD 的核心要求；草稿仅保留真实项目，没有伪造匹配经历。")
    return {"jobTitle": job_title, "sections": sections, "changes": changes, "source": "agent-v1-confirmed-facts"}
