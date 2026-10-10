import json
import re
from json import JSONDecodeError
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .adapters.greenhouse import parse_greenhouse_job_board
from .greenhouse_boards import get_allowed_board
from .models import CollectedJob


GREENHOUSE_API_HOST = "boards-api.greenhouse.io"
GREENHOUSE_API_ROOT = f"https://{GREENHOUSE_API_HOST}/v1/boards"
JOB_ID_PATTERN = re.compile(r"^[0-9]+$")
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 20
USER_AGENT = "resume-tailor-personal-research/0.1"


class GreenhouseRequestError(RuntimeError):
    pass


def fetch_public_job(
    *,
    board_id: str,
    job_id: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> CollectedJob:
    """Read one reviewed public Greenhouse job without authentication."""

    board = get_allowed_board(board_id)
    normalized_job_id = str(job_id).strip()
    if not JOB_ID_PATTERN.fullmatch(normalized_job_id):
        raise GreenhouseRequestError("Greenhouse job_id 必须只包含数字")

    url = (
        f"{GREENHOUSE_API_ROOT}/{board.board_token}/jobs/"
        f"{normalized_job_id}"
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
            if not final_url.startswith(f"https://{GREENHOUSE_API_HOST}/"):
                raise GreenhouseRequestError("Greenhouse 请求发生了非预期重定向")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                raise GreenhouseRequestError("Greenhouse 响应超过允许大小")
            raw_response = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        raise GreenhouseRequestError(
            f"Greenhouse 返回 HTTP {error.code}"
        ) from error
    except URLError as error:
        raise GreenhouseRequestError("无法连接 Greenhouse 官方接口") from error

    if len(raw_response) > MAX_RESPONSE_BYTES:
        raise GreenhouseRequestError("Greenhouse 响应超过允许大小")

    try:
        payload = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, JSONDecodeError) as error:
        raise GreenhouseRequestError("Greenhouse 返回的不是有效 UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise GreenhouseRequestError("Greenhouse 岗位详情不是 JSON 对象")

    jobs = parse_greenhouse_job_board(
        {"jobs": [payload]},
        board_token=board.board_token,
        company=board.company,
    )
    return jobs[0]
