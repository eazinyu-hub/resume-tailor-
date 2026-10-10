from dataclasses import dataclass
from typing import Literal


OrganizationStatus = Literal["allowed_automated", "paused_review", "blocked"]


@dataclass(frozen=True)
class MokaOrganization:
    organization_id: str
    organization_token: str
    company: str
    careers_url: str
    site_id: str
    status: OrganizationStatus
    reviewed_at: str
    reason: str


MOKA_ORGANIZATIONS = {
    "deeproute": MokaOrganization(
        organization_id="deeproute",
        organization_token="deeproute",
        company="深圳元戎启行科技有限公司",
        careers_url="https://app.mokahr.com/social-recruitment/deeproute/143885",
        site_id="143885",
        status="allowed_automated",
        reviewed_at="2026-09-17",
        reason=(
            "企业公开招聘站使用 Moka；允许读取单条公开岗位，"
            "以及用户手动启动或明确启用定时的一页公开社招列表；不自动翻页。"
        ),
    )
}


def get_allowed_organization(organization_id: str) -> MokaOrganization:
    try:
        organization = MOKA_ORGANIZATIONS[organization_id]
    except KeyError as error:
        raise ValueError(f"未审核的 Moka 招聘组织：{organization_id}") from error
    if organization.status != "allowed_automated":
        raise PermissionError(
            f"Moka 招聘组织 {organization.company} 当前状态为 "
            f"{organization.status}"
        )
    return organization
