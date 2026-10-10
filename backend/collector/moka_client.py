import json
import re
from copy import deepcopy
from collections.abc import Mapping
from json import JSONDecodeError
from typing import Any
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .adapters.moka import parse_moka_job
from .moka_organizations import get_allowed_organization
from .models import CollectedJob


MOKA_API_HOST = "api.mokahr.com"
MOKA_API_ROOT = f"https://{MOKA_API_HOST}/api-platform/v1/jobs"
POSTING_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 20
USER_AGENT = "resume-tailor-personal-research/0.1"
LIST_CACHE_SECONDS = 10 * 60
DETAIL_CACHE_SECONDS = 30 * 60
RATE_LIMIT_PAUSE_SECONDS = 30 * 60
_REQUEST_LOCK = Lock()
_RESPONSE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SOURCE_PAUSED_UNTIL = 0.0


class MokaRequestError(RuntimeError):
    pass


def _request_json(
    url: str,
    timeout_seconds: int,
    *,
    cache_seconds: int,
) -> dict[str, Any]:
    global _SOURCE_PAUSED_UNTIL

    with _REQUEST_LOCK:
        now = monotonic()
        cached = _RESPONSE_CACHE.get(url)
        if cached and now - cached[0] < cache_seconds:
            return deepcopy(cached[1])
        if now < _SOURCE_PAUSED_UNTIL:
            raise MokaRequestError("Moka 来源因限流或拒绝访问而临时暂停")

        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                final_url = urlparse(response.geturl())
                if (
                    final_url.scheme != "https"
                    or final_url.hostname != MOKA_API_HOST
                ):
                    raise MokaRequestError("Moka 请求发生了非预期重定向")
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                    raise MokaRequestError("Moka 响应超过允许大小")
                raw_response = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            if error.code in {403, 429}:
                _SOURCE_PAUSED_UNTIL = monotonic() + RATE_LIMIT_PAUSE_SECONDS
            raise MokaRequestError(f"Moka 返回 HTTP {error.code}") from error
        except URLError as error:
            raise MokaRequestError("无法连接 Moka 官方接口") from error

        if len(raw_response) > MAX_RESPONSE_BYTES:
            raise MokaRequestError("Moka 响应超过允许大小")
        try:
            payload = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise MokaRequestError("Moka 返回的不是有效 UTF-8 JSON") from error
        if not isinstance(payload, dict):
            raise MokaRequestError("Moka 返回内容不是 JSON 对象")
        _RESPONSE_CACHE[url] = (monotonic(), deepcopy(payload))
        return payload


def reset_request_state_for_tests() -> None:
    global _SOURCE_PAUSED_UNTIL
    with _REQUEST_LOCK:
        _RESPONSE_CACHE.clear()
        _SOURCE_PAUSED_UNTIL = 0.0


def fetch_public_job(
    *,
    organization_id: str,
    posting_id: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> CollectedJob:
    """Read one allowlisted public Moka posting without authentication."""

    organization = get_allowed_organization(organization_id)
    normalized_posting_id = str(posting_id).strip()
    if not POSTING_ID_PATTERN.fullmatch(normalized_posting_id):
        raise MokaRequestError("Moka posting_id 必须是 UUID")

    url = (
        f"{MOKA_API_ROOT}/{organization.organization_token}/"
        f"{normalized_posting_id}"
    )
    payload = _request_json(
        url,
        timeout_seconds,
        cache_seconds=DETAIL_CACHE_SECONDS,
    )

    return parse_moka_job(
        payload,
        organization_token=organization.organization_token,
        company=organization.company,
        careers_url=organization.careers_url,
    )


def fetch_public_job_list(
    *,
    organization_id: str,
    limit: int = 100,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[int, list[dict[str, Any]]]:
    """Read one controlled page of open social jobs from an allowlisted site."""

    organization = get_allowed_organization(organization_id)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise MokaRequestError("Moka 岗位列表 limit 必须在 1 到 100 之间")
    query = urlencode(
        {
            "mode": "social",
            "status": "open",
            "limit": str(limit),
            "offset": "0",
            "siteId": organization.site_id,
        }
    )
    url = f"{MOKA_API_ROOT}/{organization.organization_token}?{query}"
    payload = _request_json(
        url,
        timeout_seconds,
        cache_seconds=LIST_CACHE_SECONDS,
    )
    if payload.get("code") != 0:
        raise MokaRequestError("Moka 岗位列表接口未返回成功结果")
    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list):
        raise MokaRequestError("Moka 岗位列表缺少 jobs 数组")
    jobs = []
    for raw_job in raw_jobs:
        if not isinstance(raw_job, Mapping):
            raise MokaRequestError("Moka 岗位列表包含无效岗位对象")
        if raw_job.get("status") != "open":
            continue
        if raw_job.get("orgId") != organization.organization_token:
            raise MokaRequestError("Moka 岗位列表包含非白名单企业岗位")
        jobs.append(dict(raw_job))
    total = payload.get("total")
    return (total if isinstance(total, int) else len(jobs), jobs)
