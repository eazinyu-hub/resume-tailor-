from dataclasses import dataclass
from typing import Literal


BoardStatus = Literal["allowed_automated", "paused_review", "blocked"]


@dataclass(frozen=True)
class GreenhouseBoard:
    board_id: str
    board_token: str
    company: str
    careers_url: str
    status: BoardStatus
    reviewed_at: str
    reason: str


GREENHOUSE_BOARDS = {
    "anthropic": GreenhouseBoard(
        board_id="anthropic",
        board_token="anthropic",
        company="Anthropic",
        careers_url="https://job-boards.greenhouse.io/anthropic",
        status="allowed_automated",
        reviewed_at="2026-09-16",
        reason="公开招聘板使用 Greenhouse Job Board，试点仅允许读取已发布岗位。",
    )
}


def get_allowed_board(board_id: str) -> GreenhouseBoard:
    try:
        board = GREENHOUSE_BOARDS[board_id]
    except KeyError as error:
        raise ValueError(f"未审核的 Greenhouse 招聘板：{board_id}") from error
    if board.status != "allowed_automated":
        raise PermissionError(
            f"Greenhouse 招聘板 {board.company} 当前状态为 {board.status}"
        )
    return board
