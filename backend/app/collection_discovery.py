"""Rank public collector candidates without staging or importing them."""

import re
from collections.abc import Iterable, Mapping
from typing import Any

from app.collection_relevance import (
    TARGET_TECH_FAMILIES,
    evaluate_collected_job,
)
from app.candidate_fit import evaluate_candidate_fit
from collector.adapters.greenhouse import clean_greenhouse_description


SIGNAL_PATTERNS = (
    ("研发效能", re.compile(r"研发效能", re.IGNORECASE), 10),
    ("AI Coding", re.compile(r"AI\s*Coding|Vibe\s*Coding", re.IGNORECASE), 10),
    ("Agent", re.compile(r"\bAgent\b|智能体", re.IGNORECASE), 7),
    ("AI 工具", re.compile(r"AI\s*工具|人工智能工具", re.IGNORECASE), 7),
    ("内部工具", re.compile(r"内部工具|开发工具|效能工具", re.IGNORECASE), 5),
    ("自动化", re.compile(r"自动化|工作流", re.IGNORECASE), 4),
    ("AI 编程工具", re.compile(r"Cursor|Claude Code|Codex", re.IGNORECASE), 5),
    ("Agent 工程", re.compile(r"RAG|MCP|Prompt Engineering", re.IGNORECASE), 4),
)

EXCLUDED_TITLE_PATTERN = re.compile(
    r"算法|SLAM|感知|规划控制|模型训练|World Model|Robotaxi|"
    r"Reconstruction|Gaussian Splatting|Video Generation|专家|负责人|总监",
    re.IGNORECASE,
)


def rank_moka_candidates(
    raw_jobs: Iterable[Mapping[str, Any]],
    references: Iterable[Mapping[str, Any]],
    *,
    staged_job_ids: set[str] | None = None,
    candidate_profile: Mapping[str, Any] | None = None,
    maximum: int = 10,
) -> list[dict[str, Any]]:
    """Return target-like candidates; never writes to staging."""

    staged_ids = staged_job_ids or set()
    reference_rows = list(references)
    candidates = []
    for raw_job in raw_jobs:
        posting_id = raw_job.get("id")
        title = raw_job.get("title")
        raw_description = raw_job.get("description")
        if not isinstance(posting_id, str) or not isinstance(title, str):
            continue
        if not isinstance(raw_description, str) or not raw_description.strip():
            continue
        if EXCLUDED_TITLE_PATTERN.search(title):
            continue

        description = clean_greenhouse_description(raw_description)
        combined = f"{title}\n{description}"
        matched_signals = [
            (name, weight)
            for name, pattern, weight in SIGNAL_PATTERNS
            if pattern.search(combined)
        ]
        title_has_strong_signal = bool(
            re.search(
                r"研发效能|AI\s*Coding|Vibe\s*Coding|Agent|智能体|AI\s*工具",
                title,
                re.IGNORECASE,
            )
        )
        if not matched_signals or not title_has_strong_signal:
            continue

        relevance = evaluate_collected_job(
            {"title": title, "description": description},
            reference_rows,
        )
        if (
            relevance["family"] not in TARGET_TECH_FAMILIES
            or float(relevance["score"]) < 25
        ):
            continue
        candidates.append(
            {
                "source_job_id": posting_id,
                "title": title.strip(),
                "updated_at": raw_job.get("updatedAt"),
                "score": relevance["score"],
                "family": relevance["family"],
                "family_label": relevance["family_label"],
                "signals": [name for name, _ in matched_signals],
                "already_staged": posting_id in staged_ids,
                "candidate_fit": evaluate_candidate_fit(
                    title,
                    description,
                    candidate_profile,
                ),
            }
        )

    candidates.sort(
        key=lambda item: (
            -float(item["candidate_fit"].get("score") or 0),
            item["already_staged"],
            -float(item["score"]),
            str(item["title"]),
        )
    )
    return candidates[:maximum]
