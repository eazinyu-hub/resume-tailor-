"""Bounded list readers for reviewed public sources; no login or arbitrary URLs."""

import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .adapters.greenhouse import parse_greenhouse_job_board
from .adapters.lever import parse_lever_posting
from .adapters.moka import parse_moka_job
from .greenhouse_boards import GREENHOUSE_BOARDS, get_allowed_board
from .lever_sites import LEVER_SITES, get_allowed_site
from .models import CollectedJob
from .moka_client import fetch_public_job_list
from .moka_organizations import MOKA_ORGANIZATIONS, get_allowed_organization
from .policy import require_automated_collection


@dataclass(frozen=True)
class BatchSource:
    key: str
    provider: str
    organization_id: str
    company: str
    url: str
    note: str
    default_selected: bool = False


@dataclass
class SourcePage:
    jobs: list[CollectedJob]
    total: int | None
    scanned: int
    truncated: bool
    errors: list[dict]


def list_batch_sources() -> list[dict]:
    sources = []
    for key, org in MOKA_ORGANIZATIONS.items():
        if org.status == "allowed_automated":
            sources.append(BatchSource(f"moka:{key}", "moka", key, org.company,
                org.careers_url, "国内公开来源；现有岗位可能偏资深，不代表适合投递。", True))
    for key, board in GREENHOUSE_BOARDS.items():
        if board.status == "allowed_automated":
            sources.append(BatchSource(f"greenhouse:{key}", "greenhouse", key,
                board.company, board.careers_url, "海外参考源，默认不选；不作为低门槛推荐。"))
    for key, site in LEVER_SITES.items():
        if site.status == "allowed_automated":
            sources.append(BatchSource(f"lever:{key}", "lever", key,
                site.company, site.careers_url, "海外参考源，默认不选；资格与语言需人工核实。"))
    return [asdict(source) for source in sources]


class BatchSourceError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BatchSourceError("公开接口发生重定向，已停止；不会跟随到其他地址")


_HTTP_LOCK = Lock()
_CACHE: dict = {}
_PAUSED: dict[str, float] = {}
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def _read_json(url: str, provider: str):
    # Only this module builds URLs, from server-side reviewed organization IDs.
    with _HTTP_LOCK:
        now = monotonic()
        if now < _PAUSED.get(provider, 0):
            raise BatchSourceError("来源在限流冷却期，请 30 分钟后再试")
        cached = _CACHE.get(url)
        if cached and now - cached[0] < 600:
            return deepcopy(cached[1])
        request = Request(url, headers={"Accept": "application/json",
            "User-Agent": "resume-tailor-personal-research/0.1"})
        try:
            with build_opener(_NoRedirect()).open(request, timeout=20) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            if error.code in {403, 429}:
                _PAUSED[provider] = monotonic() + 1800
            raise BatchSourceError(f"公开接口返回 HTTP {error.code}；未自动重试") from error
        except (URLError, TimeoutError, OSError) as error:
            raise BatchSourceError("公开接口连接失败或超时；未自动重试") from error
        if len(raw) > MAX_RESPONSE_BYTES:
            raise BatchSourceError("公开接口响应超过 5 MB 安全上限，已停止")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError) as error:
            raise BatchSourceError("公开接口没有返回有效 JSON") from error
        _CACHE[url] = (monotonic(), deepcopy(payload))
        return payload


def fetch_source_page(key: str, limit: int) -> SourcePage:
    if key not in {source["key"] for source in list_batch_sources()}:
        raise ValueError("未审核或已暂停的采集来源")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("单来源处理上限必须为 1～100")
    provider, organization_id = key.split(":", 1)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", organization_id):
        raise ValueError("来源标识无效")
    total = None
    if provider == "moka":
        require_automated_collection("moka_recruitment_api")
        org = get_allowed_organization(organization_id)
        total, raw_jobs = fetch_public_job_list(organization_id=organization_id, limit=limit)
        # The list endpoint validates code/open/orgId. The detail adapter uses
        # success=True; this flag translates envelopes, not recruiting status.
        def parse(raw):
            return parse_moka_job({**raw, "success": True}, organization_token=org.organization_token,
                company=org.company, careers_url=org.careers_url)
    elif provider == "greenhouse":
        require_automated_collection("greenhouse_job_board_api")
        board = get_allowed_board(organization_id)
        payload = _read_json(f"https://boards-api.greenhouse.io/v1/boards/{board.board_token}/jobs?content=true", provider)
        raw_jobs = payload.get("jobs") if isinstance(payload, dict) else None
        def parse(raw):
            return parse_greenhouse_job_board({"jobs": [raw]}, board_token=board.board_token, company=board.company)[0]
        if isinstance(raw_jobs, list):
            total = len(raw_jobs)
    else:
        require_automated_collection("lever_postings_api")
        site = get_allowed_site(organization_id)
        raw_jobs = _read_json(f"https://api.lever.co/v0/postings/{site.site_token}?mode=json&skip=0&limit={limit}", provider)
        def parse(raw):
            return parse_lever_posting(raw, site_token=site.site_token, company=site.company)
    if not isinstance(raw_jobs, list):
        raise BatchSourceError("公开接口缺少岗位列表")
    jobs, errors = [], []
    for index, raw in enumerate(raw_jobs[:limit]):
        try:
            if not isinstance(raw, dict):
                raise ValueError("岗位不是有效对象")
            jobs.append(parse(raw))
        except (ValueError, TypeError, KeyError) as error:
            errors.append({"index": index + 1, "reason": str(error)[:200]})
    truncated = total > limit if total is not None else len(raw_jobs) >= limit
    return SourcePage(jobs, total, min(len(raw_jobs), limit), truncated, errors)
