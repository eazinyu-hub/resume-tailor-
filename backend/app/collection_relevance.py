"""Explain whether a staged job is useful for the user's target market."""

import math
import re
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.market_profile import (
    ROLE_FAMILY_LABELS,
    SIMILARITY_WEIGHTS,
    extract_requirements,
    suggest_role_family,
)


TARGET_TECH_FAMILIES = {
    "ai_tool_automation",
    "vibe_coding_fullstack",
    "agent_application",
    "internal_intelligence",
    "indie_ai_developer",
}

SENIOR_TITLE_PATTERNS = (
    ("Staff / Principal 高级岗位", r"\b(?:staff|principal|distinguished)\b|首席|资深专家"),
    ("管理岗位", r"\b(?:director|head|manager)\b|负责人|总监|经理"),
    ("科研岗位", r"research\s+scientist|研究科学家|算法研究员"),
)

RESEARCH_CONTEXT_PATTERN = re.compile(
    r"\bresearch\b|科研|模型训练|预训练|pre-?training|"
    r"reinforcement\s+learning|强化学习|论文",
    re.IGNORECASE,
)

EXPERIENCE_PATTERNS = (
    re.compile(
        r"(?<!\d)(\d{1,2})\s*\+?\s*(?:years?|yrs?)\s+"
        r"(?:of\s+)?(?:professional\s+|relevant\s+|software\s+|"
        r"engineering\s+|development\s+|work\s+)?experience\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bexperience\b.{0,24}?(?<!\d)(\d{1,2})\s*\+?\s*"
        r"(?:years?|yrs?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<!\d)(\d{1,2})\s*\+?\s*年(?:以上)?"
        r"(?:相关|工作|开发|工程|专业)?经验",
        re.IGNORECASE,
    ),
)

WORK_AUTH_PATTERN = re.compile(
    r"legally authorized to work|work authorization|"
    r"does not offer (?:employment )?visa sponsorship|"
    r"no (?:visa )?sponsorship|工作许可|不提供签证",
    re.IGNORECASE,
)

OVERSEAS_ONSITE_PATTERN = re.compile(
    r"\b(?:100%\s+)?on-?site\b|\bin[- ]office\b|现场办公",
    re.IGNORECASE,
)

EDUCATION_REQUIREMENT_PATTERN = re.compile(
    r"本科(?:学历)?及以上.{0,35}(?:计算机|人工智能|数据科学|软件工程).{0,20}相关专业",
    re.IGNORECASE | re.DOTALL,
)


def _signal_tokens(text: str) -> set[tuple[str, str]]:
    return {
        (str(item["category"]), str(item["requirement"]))
        for item in extract_requirements(text)
        if item["category"] != "学历与经验"
    }


def _family_for_reference(reference: Mapping[str, Any]) -> str:
    family = reference.get("role_family")
    if family in ROLE_FAMILY_LABELS:
        return str(family)
    return str(
        suggest_role_family(
            str(reference.get("title", "")),
            str(reference.get("description", "")),
        )["family"]
    )


def _chinese_ratio(text: str) -> float:
    meaningful = re.findall(r"[A-Za-z\u4e00-\u9fff]", text)
    if not meaningful:
        return 0.0
    chinese = sum("\u4e00" <= character <= "\u9fff" for character in meaningful)
    return chinese / len(meaningful)


def _barriers(title: str, description: str) -> tuple[list[str], list[str]]:
    hard_barriers = [
        label
        for label, expression in SENIOR_TITLE_PATTERNS
        if re.search(expression, title, re.IGNORECASE)
    ]
    years = [
        int(value)
        for pattern in EXPERIENCE_PATTERNS
        for value in pattern.findall(description)
    ]
    if years and max(years) >= 4:
        hard_barriers.append(f"明确要求 {max(years)} 年或以上经验")

    context_notes = []
    if RESEARCH_CONTEXT_PATTERN.search(f"{title}\n{description}"):
        context_notes.append("岗位处于科研或模型研究场景")
    if WORK_AUTH_PATTERN.search(description):
        context_notes.append("存在当地工作资格或签证限制")
    if OVERSEAS_ONSITE_PATTERN.search(description):
        context_notes.append("要求在岗位所在地现场办公")
    if EDUCATION_REQUIREMENT_PATTERN.search(description):
        context_notes.append("明确要求本科及以上及相关专业背景")
    return sorted(set(hard_barriers)), context_notes


def evaluate_collected_job(
    job: Mapping[str, Any],
    references: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate usefulness, not candidate competence or hiring probability."""

    title = str(job.get("title", ""))
    description = str(job.get("description", ""))
    suggestion = suggest_role_family(title, description)
    target_family = str(suggestion["family"])
    target_tokens = _signal_tokens(description)
    reference_rows = list(references)
    reference_tokens = [
        (reference, _signal_tokens(str(reference.get("description", ""))))
        for reference in reference_rows
    ]
    frequency = Counter(token for _, tokens in reference_tokens for token in tokens)

    def weight(token: tuple[str, str]) -> float:
        base = SIMILARITY_WEIGHTS.get(token[0], 1)
        return base * (
            1 + math.log((len(reference_tokens) + 1) / (frequency[token] + 1))
        )

    similar_samples = []
    for reference, tokens in reference_tokens:
        shared = tokens & target_tokens
        union = tokens | target_tokens
        if len(shared) < 2 or not union:
            continue
        similarity = sum(weight(token) for token in shared) / sum(
            weight(token) for token in union
        )
        reference_family = _family_for_reference(reference)
        similar_samples.append(
            {
                "id": reference.get("id"),
                "title": reference.get("title"),
                "score": round(similarity * 100, 1),
                "family": reference_family,
                "family_label": ROLE_FAMILY_LABELS.get(
                    reference_family, "待确认方向"
                ),
                "shared_signals": [
                    name
                    for _, name in sorted(
                        shared,
                        key=lambda token: (-weight(token), token),
                    )[:5]
                ],
            }
        )
    similar_samples.sort(
        key=lambda item: (
            item["family"] != target_family,
            -item["score"],
            item["id"] or 0,
        )
    )
    similar_samples = similar_samples[:5]

    hard_barriers, context_notes = _barriers(title, description)
    overseas = _chinese_ratio(f"{title}\n{description}") < 0.15
    best_similarity = max(
        (float(item["score"]) for item in similar_samples),
        default=0.0,
    )
    target_signal_bonus = min(15.0, len(target_tokens) * 1.5)
    family_bonus = 12.0 if target_family in TARGET_TECH_FAMILIES else 0.0
    score = round(
        max(
            0.0,
            min(
                100.0,
                best_similarity + target_signal_bonus + family_bonus
                - len(hard_barriers) * 18.0,
            ),
        ),
        1,
    )

    reasons = []
    if target_family in TARGET_TECH_FAMILIES:
        reasons.append(f"内容方向接近{suggestion['label']}")
    if similar_samples:
        reasons.append(
            f"与现有样本最高内容相似度 {similar_samples[0]['score']}%"
        )
    if target_tokens:
        highlighted = sorted({name for _, name in target_tokens})[:6]
        reasons.append(f"识别到目标能力：{'、'.join(highlighted)}")

    exclusion_reasons = list(hard_barriers)
    exclusion_reasons.extend(context_notes)
    if overseas:
        exclusion_reasons.append("英文海外岗位，不代表当前中文求职市场")
    if target_family not in TARGET_TECH_FAMILIES:
        exclusion_reasons.append("未稳定落入当前五个技术目标方向")
    if best_similarity < 15:
        exclusion_reasons.append("与现有真实岗位样本相似度较低")

    allow_market_profile = (
        not overseas
        and not hard_barriers
        and target_family in TARGET_TECH_FAMILIES
        and best_similarity >= 15
    )
    if allow_market_profile:
        sample_usage = "target_market"
        recommendation = "建议保留，人工确认后可进入目标岗位画像。"
    elif overseas:
        sample_usage = "overseas_reference"
        recommendation = "仅建议作为海外参考，不进入当前核心岗位画像。"
    else:
        sample_usage = "needs_review"
        recommendation = "暂不进入岗位画像，建议人工核对后决定。"

    return {
        "score": score,
        "score_note": "衡量岗位样本对当前求职方向的参考价值，不是胜任度或录用概率。",
        "family": target_family,
        "family_label": str(suggestion["label"]),
        "market_scope": "overseas" if overseas else "china_target",
        "sample_usage": sample_usage,
        "allow_market_profile": allow_market_profile,
        "recommendation": recommendation,
        "reasons": reasons,
        "exclusion_reasons": sorted(set(exclusion_reasons)),
        "similar_samples": similar_samples,
        "reference_count": len(reference_rows),
    }


def read_reference_jobs(database_path: Path) -> list[dict[str, Any]]:
    with closing(
        sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)
    ) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT jobs.id, jobs.title, jobs.description,
                   job_analyses.role_family, job_analyses.analysis_status
            FROM jobs
            LEFT JOIN job_analyses
              ON job_analyses.job_id = jobs.id AND job_analyses.is_current = 1
            WHERE COALESCE(jobs.sample_status, 'active') = 'active'
              AND jobs.duplicate_of IS NULL
            ORDER BY jobs.id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def evaluate_staging_items(
    database_path: Path,
    items: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    references = read_reference_jobs(database_path)
    return [
        {**dict(item), "relevance": evaluate_collected_job(item, references)}
        for item in items
    ]
