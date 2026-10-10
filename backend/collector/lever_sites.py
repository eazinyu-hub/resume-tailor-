from dataclasses import dataclass
from typing import Literal


SiteStatus = Literal["allowed_automated", "paused_review", "blocked"]


@dataclass(frozen=True)
class LeverSite:
    site_id: str
    site_token: str
    company: str
    careers_url: str
    status: SiteStatus
    reviewed_at: str
    reason: str


LEVER_SITES = {
    "kgroupcompanies": LeverSite(
        site_id="kgroupcompanies",
        site_token="kgroupcompanies",
        company="K Group Companies",
        careers_url="https://jobs.lever.co/kgroupcompanies",
        status="allowed_automated",
        reviewed_at="2026-09-16",
        reason=(
            "公开招聘站使用 Lever Postings API；"
            "允许单条读取及用户手动启动或明确启用定时的限量公开列表读取；不自动翻页。"
        ),
    )
}


def get_allowed_site(site_id: str) -> LeverSite:
    try:
        site = LEVER_SITES[site_id]
    except KeyError as error:
        raise ValueError(f"未审核的 Lever 招聘站：{site_id}") from error
    if site.status != "allowed_automated":
        raise PermissionError(
            f"Lever 招聘站 {site.company} 当前状态为 {site.status}"
        )
    return site
