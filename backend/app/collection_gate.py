"""Conservative batch admission, independent of the old relevance score."""

import re
from app.candidate_fit import evaluate_candidate_fit
from app.jd_signals import positive_match


DIRECTIONS = {
    "tools": "AI 工具与业务自动化",
    "vibe": "Vibe Coding / AI 全栈",
    "agent": "Agent 应用开发",
}
TOOL = r"AI\s*工具|内部工具|自动化|自动处理|数据处理|RPA|automation|internal tools|workflow"
CODING = r"AI\s*Coding|Vibe\s*Coding|Codex|Claude\s*Code|Cursor|Copilot|AI\s*编程"
DEVELOPMENT = r"开发|编程|脚本|全栈|工程师|developer|engineer|coding|programming"
SENIOR = r"高级|资深|专家|负责人|总监|架构师|首席|\b(?:senior|staff|principal|lead|director|head)\b"


def assess_batch_job(job, profile: dict, directions: list[str]) -> dict:
    text = f"{job.title}\n{job.description}"
    matched = []
    if positive_match(TOOL, text) and positive_match(DEVELOPMENT, text):
        matched.append("tools")
    if positive_match(CODING, text) and positive_match(DEVELOPMENT, text):
        matched.append("vibe")
    if positive_match(r"\bAgent\b|智能体", text) and positive_match(DEVELOPMENT, text):
        matched.append("agent")
    fit = evaluate_candidate_fit(job.title, job.description, profile)
    reasons = []
    if not set(matched).intersection(directions):
        reasons.append("不属于本次选择的开发方向")
    if re.search(SENIOR, job.title, re.I):
        reasons.append("岗位名称明确要求高级、资深或管理职责")
    if re.search(r"算法|研究员|科学家|产品经理|运营|销售|research scientist", job.title, re.I):
        reasons.append("岗位不是本次目标的入门工具 / 应用开发职位")
    reasons.extend(fit.get("barriers", []))
    if reasons:
        return {"decision": "excluded", "reasons": list(dict.fromkeys(reasons)), "directions": matched}

    unknown = list(fit.get("uncertainties", []))
    conditions = fit.get("requirements", [])
    unresolved = [item for item in conditions
        if item["kind"] in {"required", "conditional"} and item["assessment"] == "unknown"]
    # No Chinese qualification support for overseas postings in this version.
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", job.description))
    if len(re.findall(r"[A-Za-z]", job.description)) > max(30, chinese_count * 3):
        unknown.append("外文 JD 的学历、年限和工作资格尚不能可靠判断")
        unresolved.append({})
    if job.source_id in {"greenhouse_job_board_api", "lever_postings_api"}:
        unknown.append("当前海外参考来源的地区与工作资格尚待确认")
        unresolved.append({})
    if re.search(r"实习|校招|校园|intern|campus|graduate", job.title, re.I) and profile.get("graduate_eligible") is not True:
        unknown.append("实习 / 校招身份未确认，不能默认符合")
        unresolved.append({})
    # Years left unstated is NOT entry-level evidence, regardless of AI score.
    entry = any(item["category"] == "experience" and (
        item["kind"] == "unrestricted" or
        item["kind"] == "required" and item.get("value") == 0
    ) for item in conditions)
    if not entry:
        unknown.append("未明确接受零相关工作经验，不能当作低门槛岗位")
    decision = "needs_review" if unresolved or not entry else "accepted"
    return {"decision": decision, "directions": matched, "reasons": list(dict.fromkeys(unknown)) or [
        "原文允许零经验且未识别出硬性冲突；仅通过规则初筛，仍需人工核对完整 JD"
    ]}
