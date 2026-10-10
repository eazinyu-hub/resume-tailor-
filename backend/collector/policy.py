from dataclasses import dataclass
from typing import Literal


SourceStatus = Literal[
    "manual_only",
    "allowed_automated",
    "paused_review",
    "blocked",
]


@dataclass(frozen=True)
class SourcePolicy:
    source_id: str
    display_name: str
    status: SourceStatus
    reason: str
    reviewed_at: str
    evidence_url: str | None = None


SOURCE_POLICIES = {
    "boss_zhipin": SourcePolicy(
        source_id="boss_zhipin",
        display_name="BOSS直聘",
        status="manual_only",
        reason="平台协议限制未经许可的第三方工具、爬虫和自动登录。",
        reviewed_at="2026-09-15",
        evidence_url=(
            "https://www.zhipin.com/web/common/protocol/"
            "protocol-2019-09-30.html"
        ),
    ),
    "mock_local": SourcePolicy(
        source_id="mock_local",
        display_name="本地模拟来源",
        status="allowed_automated",
        reason="仅用于离线测试，不访问网络。",
        reviewed_at="2026-09-15",
    ),
    "greenhouse_job_board_api": SourcePolicy(
        source_id="greenhouse_job_board_api",
        display_name="Greenhouse Job Board API",
        status="allowed_automated",
        reason=(
            "官方文档明确说明公开 Job Board 数据的 GET 接口"
            "无需认证；仅允许读取已发布岗位。"
        ),
        reviewed_at="2026-09-16",
        evidence_url="https://docs.greenhouse.io/job-board.html",
    ),
    "lever_postings_api": SourcePolicy(
        source_id="lever_postings_api",
        display_name="Lever Postings API",
        status="allowed_automated",
        reason=(
            "Lever 官方 Postings API 提供公开岗位读取接口；"
            "仅允许已审核站点的单条岗位和一页限量公开列表；"
            "由用户手动启动或明确启用定时，沿用来源冷却与数量上限。"
        ),
        reviewed_at="2026-09-16",
        evidence_url="https://github.com/lever/postings-api",
    ),
    "moka_recruitment_api": SourcePolicy(
        source_id="moka_recruitment_api",
        display_name="Moka 招聘公开接口",
        status="allowed_automated",
        reason=(
            "Moka 官方文档提供公开招聘岗位详情接口；"
            "仅允许已审核企业的公开岗位详情和一页社招列表；"
            "由用户手动启动或明确启用定时，沿用来源冷却与数量上限。"
        ),
        reviewed_at="2026-09-17",
        evidence_url="https://www.mokahr.com/docs/api/",
    ),
}


def get_source_policy(source_id: str) -> SourcePolicy:
    try:
        return SOURCE_POLICIES[source_id]
    except KeyError as error:
        raise ValueError(f"未审核的采集来源：{source_id}") from error


def require_automated_collection(source_id: str) -> SourcePolicy:
    policy = get_source_policy(source_id)
    if policy.status != "allowed_automated":
        raise PermissionError(
            f"来源 {policy.display_name} 当前状态为 {policy.status}，"
            "不允许自动采集。"
        )
    return policy
