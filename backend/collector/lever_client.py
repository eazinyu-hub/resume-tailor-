import json
import re
from json import JSONDecodeError
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .adapters.lever import parse_lever_posting
from .lever_sites import get_allowed_site
from .models import CollectedJob


LEVER_API_HOST = "api.lever.co"
LEVER_API_ROOT = f"https://{LEVER_API_HOST}/v0/postings"
POSTING_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 20
USER_AGENT = "resume-tailor-personal-research/0.1"


class LeverRequestError(RuntimeError):
    pass


def fetch_public_posting(
    *,
    site_id: str,
    posting_id: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> CollectedJob:
    """Read one allowlisted public Lever posting without authentication."""

    site = get_allowed_site(site_id)
    normalized_posting_id = str(posting_id).strip()
    if not POSTING_ID_PATTERN.fullmatch(normalized_posting_id):
        raise LeverRequestError("Lever posting_id 必须是 UUID")

    url = (
        f"{LEVER_API_ROOT}/{site.site_token}/{normalized_posting_id}"
        "?mode=json"
    )
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            if not final_url.startswith(f"https://{LEVER_API_HOST}/"):
                raise LeverRequestError("Lever 请求发生了非预期重定向")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                raise LeverRequestError("Lever 响应超过允许大小")
            raw_response = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        raise LeverRequestError(f"Lever 返回 HTTP {error.code}") from error
    except URLError as error:
        raise LeverRequestError("无法连接 Lever 官方接口") from error

    if len(raw_response) > MAX_RESPONSE_BYTES:
        raise LeverRequestError("Lever 响应超过允许大小")
    try:
        payload = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, JSONDecodeError) as error:
        raise LeverRequestError("Lever 返回的不是有效 UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise LeverRequestError("Lever 岗位详情不是 JSON 对象")

    return parse_lever_posting(
        payload,
        site_token=site.site_token,
        company=site.company,
    )
