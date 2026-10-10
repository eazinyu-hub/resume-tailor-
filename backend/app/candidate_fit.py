"""Estimate application priority from private, user-confirmed candidate facts."""

import json
import re
from pathlib import Path
from typing import Any, Mapping

from app.fit_requirements import extract_fit_requirements
from app.jd_signals import is_negated, positive_match


ENTRY_PATTERN = re.compile(
    r"接受应届|应届生|经验不限|不要求科班|接受非科班|非科班|初级|Junior|"
    r"0\s*[-~至]\s*1\s*年|1\s*年以内",
    re.IGNORECASE,
)
NON_DEVELOPMENT_TITLE_PATTERN = re.compile(
    r"编导|编剧|导演|制片|原画|美术|剪辑|摄影|短视频|"
    r"销售|商务|市场(?:专员|经理)?|新媒体运营|内容运营",
    re.IGNORECASE,
)
EDUCATION_LEVELS = {
    "high_school": 1, "associate": 2, "bachelor": 3, "master": 4, "doctorate": 5,
}
EDUCATION_LABELS = {2: "大专", 3: "本科", 4: "硕士", 5: "博士"}
PORTFOLIO_PATTERN = re.compile(
    r"个人项目|个人作品|作品集|GitHub|Gitee|可演示\s*Demo|真实项目",
    re.IGNORECASE,
)
SENIOR_PATTERN = re.compile(
    r"专家|负责人|总监|架构师|\bStaff\b|\bPrincipal\b|\bLead\b", re.IGNORECASE,
)
RESEARCH_PATTERN = re.compile(
    r"算法研究|模型训练|预训练|强化学习|SLAM|感知算法|World Model", re.IGNORECASE,
)
PRODUCTION_DEPTH_PATTERN = re.compile(
    r"独立完成.{0,30}(?:全栈|前后端|移动应用|App).{0,30}(?:上线|部署|维护)|"
    r"高并发|大型生产系统|系统架构|稳定性维护",
    re.IGNORECASE,
)


def load_candidate_fit_profile(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("个人可投性配置格式无效")
    return payload


def _assess_condition(condition: dict[str, Any], profile: Mapping[str, Any]):
    category, value, kind = condition["category"], condition["value"], condition["kind"]
    if kind == "unrestricted":
        return {
            **condition, "assessment": "not_required",
            "explanation": "原文明确不要求该条件，不作为缺口。",
        }, 0, None
    education = profile.get("education", {})
    education = education if isinstance(education, Mapping) else {}
    actual = None
    penalty = 0
    unmet_reason = ""
    if category == "education":
        actual = EDUCATION_LEVELS.get(str(education.get("level", "")))
        penalty = 35
        unmet_reason = f"岗位要求{EDUCATION_LABELS[value]}及以上，当前学历不符合"
    elif category == "major":
        actual = education.get("related_major") if value == "related_major" else None
        value = True
        penalty = 30
        unmet_reason = "岗位明确要求计算机等相关专业，当前专业不匹配"
    elif category == "school":
        actual = education.get("elite_school")
        value = True
        penalty = 45
        unmet_reason = "岗位要求 985/211、双一流或 QS100 院校，当前院校条件不符合"
    elif category == "experience":
        actual = profile.get("relevant_experience_years")
        penalty = 35 if isinstance(value, int) and value >= 3 else 15
        unmet_reason = f"岗位至少要求 {value} 年相关经验"
    elif category == "eligibility":
        actual = profile.get("graduate_eligible")
        value = True
        penalty = 30
        unmet_reason = "岗位要求应届或在校身份，当前身份不符合"

    met = None
    if actual is not None and value is not None:
        if isinstance(value, bool) and isinstance(actual, bool):
            met = actual == value
        elif isinstance(actual, (int, float)) and not isinstance(actual, bool):
            met = actual >= value

    if kind == "conditional" and met is not True:
        assessment, explanation = "unknown", "原文允许放宽或替代，需要核实是否符合其中一条路径。"
    elif kind == "preferred":
        assessment = "matched" if met is True else "unmet" if met is False else "unknown"
        explanation = "这是优先/加分条件，不按硬性缺口扣分。"
    elif met is None:
        assessment = "unknown"
        explanation = (
            "原文要求实践经验，但未给出年限；需结合项目事实核实。"
            if category == "experience" and value is None
            else "个人资料尚不足以判断此条件，需要核实。"
        )
    elif met:
        assessment, explanation = "matched", "当前个人资料满足这项已识别条件。"
    else:
        assessment, explanation = "unmet", unmet_reason

    result = {**condition, "assessment": assessment, "explanation": explanation}
    hard_gap = kind == "required" and assessment == "unmet"
    return result, penalty if hard_gap else 0, unmet_reason if hard_gap else None


def evaluate_candidate_fit(
    title: str,
    description: str,
    profile: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return explainable application priority, never a hiring probability."""

    if profile is None:
        return {
            "status": "profile_missing", "score": None, "level": "unavailable",
            "label": "个人条件未配置", "score_note": "尚未读取 D 盘个人可投性配置。",
            "strengths": [], "barriers": [], "requirements": [], "uncertainties": [],
        }

    text = f"{title}\n{description}"
    score = 50
    strengths: list[str] = []
    barriers: list[str] = []
    requirements = []
    uncertainties = []
    for condition in extract_fit_requirements(description):
        assessed, penalty, gap = _assess_condition(condition, profile)
        requirements.append(assessed)
        score -= penalty
        if gap:
            barriers.append(gap)
        if assessed["assessment"] == "unknown" and assessed["kind"] in {"required", "conditional"}:
            uncertainties.append(f"{assessed['label']}：{assessed['explanation']}")

    mentioned = {
        item["category"] for item in requirements
        if item["kind"] != "preferred"
    }
    for category, label in (("education", "学历"), ("major", "专业"), ("experience", "经验")):
        if category not in mentioned:
            uncertainties.append(f"JD 未明确{label}条件；未写明不代表已满足或没有限制。")

    matched_tools = [
        tool for tool in profile.get("verified_tools", [])
        if isinstance(tool, str) and positive_match(re.escape(tool), text)
    ]
    if matched_tools:
        score += min(16, len(matched_tools) * 5)
        strengths.append(f"已验证工具匹配：{'、'.join(matched_tools)}")
    entry_friendly = any(
        not re.search(r"不接受|不招|不考虑|仅限", text[max(0, match.start() - 10):match.start()])
        and (match.group().startswith("不要求") or not is_negated(text, match.start()))
        for match in ENTRY_PATTERN.finditer(text)
    )
    if entry_friendly:
        score += 15
        strengths.append("原文有初级或放宽背景的表述；具体资格仍需逐项核对")
    portfolio = bool(
        positive_match(PORTFOLIO_PATTERN.pattern, text)
        and int(profile.get("project_count", 0)) > 0
    )
    if portfolio:
        score += 12
        strengths.append("岗位重视个人项目或 Demo，可用现有项目进一步举证")

    hard_gap = bool(barriers)
    off_direction = bool(NON_DEVELOPMENT_TITLE_PATTERN.search(title))
    if off_direction:
        score -= 45
        barriers.append("岗位不属于当前 Vibe Coding / AI 工具开发方向")
    senior = bool(SENIOR_PATTERN.search(title))
    if senior:
        score -= 45
        barriers.append("岗位名称体现高级、专家或管理职责")

    # Do not penalize a research/production topic mentioned only as a bonus.
    # Check individual clauses so a nearby '优先' does not weaken other duties.
    risk_texts = []
    bonus_section = False
    for part in re.split(r"(加分项|任职要求|任职资格|岗位要求|岗位职责|工作职责)", description):
        if part == "加分项":
            bonus_section = True
        elif part in {"任职要求", "任职资格", "岗位要求", "岗位职责", "工作职责"}:
            bonus_section = False
        elif not bonus_section:
            risk_texts.extend(
                clause for clause in re.split(r"[\n。；;，,]+", part)
                if not re.search(r"优先(?!级)|加分|更佳", clause)
            )
    research = any(positive_match(RESEARCH_PATTERN.pattern, part) for part in risk_texts)
    if research:
        score -= 40
        barriers.append("岗位偏算法研究或模型训练，不符合当前项目型路线")
    if profile.get("relevant_experience_years") == 0 and any(
        positive_match(PRODUCTION_DEPTH_PATTERN.pattern, part) for part in risk_texts
    ):
        score -= 15
        barriers.append("岗位要求独立生产交付或较深工程维护经验，需补充项目证据")

    score = max(0, min(100, score))
    if hard_gap or off_direction or senior or research:
        score = min(score, 39)
    unresolved = any(
        item["kind"] in {"required", "conditional"} and item["assessment"] == "unknown"
        for item in requirements
    )
    if hard_gap or off_direction or senior or research or barriers and score < 40:
        level, label = "low_priority", "当前门槛偏高"
    elif unresolved or not (matched_tools or portfolio):
        level, label, score = "insufficient_information", "信息不足，待核实", None
    elif score >= 65:
        level, label = "recommended", "推荐优先了解"
    else:
        level, label = "stretch", "可以冲刺"

    return {
        "status": "ready", "score": score, "level": level, "label": label,
        "score_note": "仅依据已识别条件和个人资料估算投递优先级，不是录用概率；信息不足时不打分。",
        "strengths": strengths, "barriers": sorted(set(barriers)),
        "requirements": requirements, "uncertainties": list(dict.fromkeys(uncertainties)),
    }
