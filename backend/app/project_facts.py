import json
import re
from copy import deepcopy
from datetime import date
from pathlib import Path


PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
EVIDENCE_STATUSES = {"已验证", "需要补充", "计划实现", "禁止写入简历"}
FACT_LIST_FIELDS = (
    "real_problem",
    "completed_features",
    "errors_and_failures",
    "debugging_methods",
    "do_not_exaggerate",
)


class ProjectFactError(ValueError):
    pass


def _card_path(facts_dir: Path, project_id: str) -> Path:
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ProjectFactError("项目 ID 只能包含小写字母、数字和连字符。")
    return facts_dir / f"{project_id}.json"


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProjectFactError(f"{label}不能为空。")
    return text


def _validate_status(value: object, label: str) -> str:
    status = str(value or "").strip()
    if status not in EVIDENCE_STATUSES:
        raise ProjectFactError(f"{label}无效。")
    return status


def _validate_fact_items(value: object, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ProjectFactError(f"{label}必须是列表。")
    items = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ProjectFactError(f"{label}第 {index} 项格式无效。")
        items.append({
            "content": _required_text(item.get("content"), f"{label}第 {index} 项内容"),
            "evidence_status": _validate_status(item.get("evidence_status"), f"{label}第 {index} 项证据状态"),
        })
    return items


def validate_project_fact_card(payload: object, project_id: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ProjectFactError("事实卡格式无效。")
    if payload.get("project_id") != project_id:
        raise ProjectFactError("请求中的项目 ID 与事实卡不一致。")

    card = deepcopy(payload)
    for field, label in (
        ("project_name", "项目名称"),
        ("project_type", "项目类型"),
        ("ownership", "负责方式"),
        ("ownership_note", "负责内容"),
    ):
        card[field] = _required_text(card.get(field), label)

    for field in FACT_LIST_FIELDS:
        card[field] = _validate_fact_items(card.get(field), field)

    tools = card.get("technology_and_ai_tools")
    if not isinstance(tools, list):
        raise ProjectFactError("技术与 AI 工具必须是列表。")
    card["technology_and_ai_tools"] = [{
        "name": _required_text(item.get("name") if isinstance(item, dict) else "", "工具名称"),
        "usage": _required_text(item.get("usage") if isinstance(item, dict) else "", "工具用途"),
        "level": _required_text(item.get("level") if isinstance(item, dict) else "", "使用程度"),
        "evidence_status": _validate_status(item.get("evidence_status") if isinstance(item, dict) else "", "工具证据状态"),
    } for item in tools]

    completion = card.get("completion")
    if not isinstance(completion, dict):
        raise ProjectFactError("当前完成度格式无效。")
    card["completion"] = {
        "status": _required_text(completion.get("status"), "当前完成度"),
        "completed_scope": _validate_fact_items(completion.get("completed_scope"), "已完成范围"),
        "remaining_scope": _validate_fact_items(completion.get("remaining_scope"), "待做范围"),
        "last_verified_at": _required_text(completion.get("last_verified_at"), "最后核对日期"),
    }

    evidence = card.get("evidence")
    if not isinstance(evidence, list):
        raise ProjectFactError("展示证据必须是列表。")
    card["evidence"] = [{
        "type": _required_text(item.get("type") if isinstance(item, dict) else "", "证据类型"),
        "reference": _required_text(item.get("reference") if isinstance(item, dict) else "", "证据内容"),
        "visibility": _required_text(item.get("visibility") if isinstance(item, dict) else "", "证据可见性"),
        "evidence_status": _validate_status(item.get("evidence_status") if isinstance(item, dict) else "", "证据状态"),
    } for item in evidence]

    card["project_id"] = project_id
    card["fact_status"] = "draft"
    card["updated_at"] = date.today().isoformat()
    return card


def list_project_fact_cards(facts_dir: Path) -> list[dict[str, object]]:
    items = []
    if not facts_dir.exists():
        return items
    for path in sorted(facts_dir.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


def _write_card(path: Path, card: dict[str, object]) -> None:
    temporary_path = path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


def save_project_fact_card(facts_dir: Path, project_id: str, payload: object) -> dict[str, object]:
    path = _card_path(facts_dir, project_id)
    if not path.exists():
        raise FileNotFoundError(project_id)
    card = validate_project_fact_card(payload, project_id)
    facts_dir.mkdir(parents=True, exist_ok=True)
    _write_card(path, card)
    return card


def confirm_project_fact_card(facts_dir: Path, project_id: str) -> dict[str, object]:
    path = _card_path(facts_dir, project_id)
    if not path.exists():
        raise FileNotFoundError(project_id)
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectFactError("事实卡无法读取。") from error
    card = validate_project_fact_card(card, project_id)
    card["fact_status"] = "confirmed"
    card["updated_at"] = date.today().isoformat()
    _write_card(path, card)
    return card
