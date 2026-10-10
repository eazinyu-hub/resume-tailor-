"""Small, explainable text rules shared by JD statistics and fact matching."""

import re
import unicodedata


def normalize(text: str) -> str:
    text = unicodedata.normalize('NFKC', text or '')
    # Repair OCR line wraps inside words, but retain numbered lines/headings.
    text = re.sub(r'(?<=[\u4e00-\u9fff])\n(?=[\u4e00-\u9fff])', '', text)
    return text


def is_negated(text: str, start: int) -> bool:
    prefix = re.split(r'[，,；;。\n：:]', text[:start])[-1][-24:]
    return bool(re.search(r'(?:无需|不需要|不要求|尚未|暂未|没有|未曾|未使用|未实现|未完成|未部署|不具备|不会|禁止|不要写成|不能写成|计划|拟实现|待实现|准备)(?!只是|仅仅)[^，,；;。]{0,18}$', prefix))


def positive_match(expression: str, text: str):
    for match in re.finditer(expression, text, re.I):
        if not is_negated(text, match.start()):
            return match
    return None


def requirement_match_count(requirement: dict, texts: list[str]) -> int:
    """Count distinct alternatives, not repeated mentions or repeated fact cards."""
    options = requirement.get("alternatives") or [{"expression": requirement["expression"]}]
    return sum(any(positive_match(option["expression"], normalize(text)) for text in texts) for option in options)


def clauses(text: str):
    """Keep heading context so optional requirements aren't promoted to must-haves."""
    headings = r'(岗位职责|工作职责|任职要求|任职资格|岗位要求|基本要求|基础能力|加分项|优先考虑|你将获得|你能获得什么|一天的工作参考)'
    mode = '正文提及'
    for part in re.split(headings, normalize(text)):
        if re.fullmatch(headings, part):
            mode = ('加分项' if part in ('加分项', '优先考虑') else
                    '招聘介绍' if part in ('你将获得', '你能获得什么', '一天的工作参考') else
                    '职责' if part in ('岗位职责', '工作职责') else '任职要求')
            continue
        for sentence in re.split(r'[\n。；;]+', part):
            sentence = sentence.strip(' \r-：:')
            if not sentence or mode == '招聘介绍':
                continue
            yield sentence, ('加分项' if mode == '加分项' or '优先' in sentence else mode)
