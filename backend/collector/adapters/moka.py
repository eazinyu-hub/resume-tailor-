import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from .greenhouse import clean_greenhouse_description
from ..models import CollectedJob
from ..policy import require_automated_collection


SOURCE_ID = "moka_recruitment_api"
ORGANIZATION_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class MokaPayloadError(ValueError):
    pass


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MokaPayloadError(f"Moka 岗位缺少有效字段：{field_name}")
    return value.strip()


def _public_job_url(careers_url: str, posting_id: str) -> str:
    parsed = urlparse(careers_url)
    if parsed.scheme != "https" or parsed.hostname != "app.mokahr.com":
        raise MokaPayloadError("Moka careers_url 不是预期的公开招聘地址")
    return f"{careers_url.rstrip('/')}#/job/{posting_id}"


def _location_name(raw_locations: Any) -> str | None:
    if not isinstance(raw_locations, list):
        return None
    locations = []
    for raw_location in raw_locations:
        if not isinstance(raw_location, Mapping):
            continue
        parts = []
        for field_name in ("country", "province", "city", "area"):
            value = raw_location.get(field_name)
            if isinstance(value, str) and value.strip() and value.strip() not in parts:
                parts.append(value.strip())
        if parts:
            locations.append(" ".join(parts))
    return "；".join(dict.fromkeys(locations)) or None


def _salary(minimum: Any, maximum: Any) -> str | None:
    if isinstance(minimum, bool) or isinstance(maximum, bool):
        return None
    if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)):
        return f"{minimum:g}-{maximum:g}K"
    return None


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def parse_moka_job(
    payload: Mapping[str, Any],
    *,
    organization_token: str,
    company: str,
    careers_url: str,
) -> CollectedJob:
    """Convert one already obtained Moka posting without networking."""

    require_automated_collection(SOURCE_ID)
    if not ORGANIZATION_TOKEN_PATTERN.fullmatch(organization_token):
        raise MokaPayloadError("Moka organization_token 格式无效")
    normalized_company = company.strip()
    if not normalized_company:
        raise MokaPayloadError("公司名称不能为空")
    if payload.get("success") is not True:
        raise MokaPayloadError("Moka 接口未返回成功结果")

    posting_id = _required_text(payload.get("id"), "id")
    title = _required_text(payload.get("title"), "title")
    status = _required_text(payload.get("status"), "status").lower()
    if status != "open":
        raise MokaPayloadError("Moka 岗位当前不是招聘中状态")
    response_organization = _required_text(payload.get("orgId"), "orgId")
    if response_organization != organization_token:
        raise MokaPayloadError("Moka 响应组织与白名单不一致")

    raw_description = _required_text(payload.get("description"), "description")
    description = clean_greenhouse_description(raw_description)
    if not description:
        raise MokaPayloadError("Moka 岗位正文清洗后为空")

    return CollectedJob(
        title=title,
        company=normalized_company,
        description=description,
        source_id=SOURCE_ID,
        source_url=_public_job_url(careers_url, posting_id),
        source_job_id=posting_id,
        published_at=(
            _optional_text(payload.get("publishedAt"))
            or _optional_text(payload.get("openedAt"))
        ),
        source_updated_at=_optional_text(payload.get("updatedAt")),
        city=_location_name(payload.get("locations")),
        salary=_salary(payload.get("minSalary"), payload.get("maxSalary")),
    )
