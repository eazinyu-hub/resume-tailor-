from .models import CollectedJob
from .policy import require_automated_collection


def collect_mock_job() -> CollectedJob:
    """Return one deterministic fixture without touching the network."""

    require_automated_collection("mock_local")
    return CollectedJob(
        title="AI 工具开发（模拟岗位）",
        company="示例公司",
        description="使用 AI 编程工具开发内部自动化工具，并完成调试和验证。",
        source_id="mock_local",
        source_url="https://example.invalid/jobs/ai-tool",
        city="示例城市",
    )
