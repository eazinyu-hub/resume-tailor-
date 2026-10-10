import re
from collections.abc import Mapping
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from ..models import CollectedJob
from ..policy import require_automated_collection


SOURCE_ID = "greenhouse_job_board_api"
BOARD_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class GreenhousePayloadError(ValueError):
    pass


class _JobDescriptionParser(HTMLParser):
    BLOCK_TAGS = {
        "address",
        "article",
        "blockquote",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ol",
        "p",
        "section",
        "table",
        "tr",
        "ul",
    }
    IGNORED_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag in self.IGNORED_TAGS:
            self.ignored_depth += 1
        elif self.ignored_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.IGNORED_TAGS and self.ignored_depth:
            self.ignored_depth -= 1
        elif self.ignored_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignored_depth == 0:
            self.parts.append(data)

    def text(self) -> str:
        lines = []
        for line in "".join(self.parts).splitlines():
            normalized = re.sub(r"\s+", " ", line).strip()
            if normalized:
                lines.append(normalized)
        return "\n".join(lines)


def clean_greenhouse_description(content: str) -> str:
    """Decode Greenhouse's escaped editor HTML, then keep readable text only."""

    decoded = content
    for _ in range(3):
        next_value = unescape(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    parser = _JobDescriptionParser()
    parser.feed(decoded)
    parser.close()
    return parser.text()


def _required_text(value: Any, field_name: str, job_index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GreenhousePayloadError(
            f"第 {job_index + 1} 条岗位缺少有效字段：{field_name}"
        )
    return value.strip()


def _public_https_url(value: Any, job_index: int) -> str:
    url = _required_text(value, "absolute_url", job_index)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise GreenhousePayloadError(
            f"第 {job_index + 1} 条岗位的 absolute_url 不是公开 HTTPS 地址"
        )
    return url


def parse_greenhouse_job_board(
    payload: Mapping[str, Any],
    *,
    board_token: str,
    company: str,
) -> list[CollectedJob]:
    """Convert an already obtained Greenhouse response without networking."""

    require_automated_collection(SOURCE_ID)
    if not BOARD_TOKEN_PATTERN.fullmatch(board_token):
        raise GreenhousePayloadError("Greenhouse board_token 格式无效")
    normalized_company = company.strip()
    if not normalized_company:
        raise GreenhousePayloadError("公司名称不能为空")

    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list):
        raise GreenhousePayloadError("Greenhouse 响应缺少 jobs 数组")

    jobs: list[CollectedJob] = []
    for index, raw_job in enumerate(raw_jobs):
        if not isinstance(raw_job, Mapping):
            raise GreenhousePayloadError(f"第 {index + 1} 条岗位不是对象")

        title = _required_text(raw_job.get("title"), "title", index)
        html_content = _required_text(raw_job.get("content"), "content", index)
        description = clean_greenhouse_description(html_content)
        if not description:
            raise GreenhousePayloadError(
                f"第 {index + 1} 条岗位正文清洗后为空；"
                "请确认请求使用了 content=true"
            )

        raw_location = raw_job.get("location")
        city = None
        if isinstance(raw_location, Mapping):
            location_name = raw_location.get("name")
            if isinstance(location_name, str) and location_name.strip():
                city = location_name.strip()

        source_job_id = raw_job.get("id")
        if source_job_id is None:
            raise GreenhousePayloadError(f"第 {index + 1} 条岗位缺少 id")

        updated_at = raw_job.get("updated_at")
        jobs.append(
            CollectedJob(
                title=title,
                company=normalized_company,
                description=description,
                source_id=SOURCE_ID,
                source_url=_public_https_url(raw_job.get("absolute_url"), index),
                source_job_id=str(source_job_id),
                source_updated_at=(
                    updated_at.strip()
                    if isinstance(updated_at, str) and updated_at.strip()
                    else None
                ),
                city=city,
            )
        )

    return jobs
