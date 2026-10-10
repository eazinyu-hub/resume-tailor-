import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .greenhouse import clean_greenhouse_description
from ..models import CollectedJob
from ..policy import require_automated_collection


SOURCE_ID = "lever_postings_api"
SITE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class LeverPayloadError(ValueError):
    pass


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LeverPayloadError(f"Lever 岗位缺少有效字段：{field_name}")
    return value.strip()


def _public_job_url(value: Any, site_token: str, posting_id: str) -> str:
    url = _required_text(value, "hostedUrl")
    parsed = urlparse(url)
    expected_path = f"/{site_token}/{posting_id}"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "jobs.lever.co"
        or parsed.path.rstrip("/") != expected_path
    ):
        raise LeverPayloadError("Lever hostedUrl 不是预期的公开岗位地址")
    return url


def _plain_or_html(plain: Any, html: Any) -> str:
    if isinstance(plain, str) and plain.strip():
        return plain.strip()
    if isinstance(html, str) and html.strip():
        return clean_greenhouse_description(html)
    return ""


def _description(payload: Mapping[str, Any]) -> str:
    sections: list[str] = []
    opening = _plain_or_html(
        payload.get("descriptionPlain"),
        payload.get("description"),
    )
    if opening:
        sections.append(opening)

    raw_lists = payload.get("lists")
    if isinstance(raw_lists, list):
        for raw_list in raw_lists:
            if not isinstance(raw_list, Mapping):
                continue
            heading = raw_list.get("text")
            content = raw_list.get("content")
            section_parts = []
            if isinstance(heading, str) and heading.strip():
                section_parts.append(heading.strip())
            if isinstance(content, str) and content.strip():
                cleaned = clean_greenhouse_description(content)
                if cleaned:
                    section_parts.append(cleaned)
            if section_parts:
                sections.append("\n".join(section_parts))

    closing = _plain_or_html(
        payload.get("additionalPlain"),
        payload.get("additional"),
    )
    if closing:
        sections.append(closing)
    return "\n\n".join(sections).strip()


def _published_at(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(
            value / 1000,
            tz=timezone.utc,
        ).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def parse_lever_posting(
    payload: Mapping[str, Any],
    *,
    site_token: str,
    company: str,
) -> CollectedJob:
    """Convert one already obtained Lever posting without networking."""

    require_automated_collection(SOURCE_ID)
    if not SITE_TOKEN_PATTERN.fullmatch(site_token):
        raise LeverPayloadError("Lever site_token 格式无效")
    normalized_company = company.strip()
    if not normalized_company:
        raise LeverPayloadError("公司名称不能为空")

    posting_id = _required_text(payload.get("id"), "id")
    title = _required_text(payload.get("text"), "text")
    description = _description(payload)
    if not description:
        raise LeverPayloadError("Lever 岗位正文清洗后为空")

    categories = payload.get("categories")
    location = None
    if isinstance(categories, Mapping):
        raw_location = categories.get("location")
        if isinstance(raw_location, str) and raw_location.strip():
            location = raw_location.strip()

    return CollectedJob(
        title=title,
        company=normalized_company,
        description=description,
        source_id=SOURCE_ID,
        source_url=_public_job_url(
            payload.get("hostedUrl"),
            site_token,
            posting_id,
        ),
        source_job_id=posting_id,
        published_at=_published_at(payload.get("createdAt")),
        city=location,
    )
