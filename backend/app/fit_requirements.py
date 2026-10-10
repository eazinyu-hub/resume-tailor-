"""Extract a small set of applicant conditions with their original evidence.

These Chinese rules deliberately keep preferences and exceptions separate from
requirements. They do not infer that an unmentioned condition is satisfied.
"""

import re
from typing import Any

from app.jd_signals import is_negated


HEADINGS = re.compile(
    r"岗位职责|工作职责|主要职责|任职要求|任职资格|岗位要求|基本要求|"
    r"加分项|优先条件|优先考虑|公司介绍|关于我们|岗位定位|职位概述|我们提供"
)
PREFERRED = re.compile(r"优先(?!级)|加分|更佳|为佳|preferred|nice.to.have", re.I)
DEGREES = {"专科": 2, "大专": 2, "本科": 3, "学士": 3, "硕士": 4, "研究生": 4, "博士": 5}
DEGREE = re.compile("|".join(DEGREES))
MAJOR = re.compile(
    r"(?:计算机|软件工程|人工智能|数据科学)[^，,。；;\n]{0,65}?"
    r"(?:相关专业|专业|背景)"
)
SCHOOL = re.compile(r"985|211|双一流|QS\s*(?:TOP)?\s*100", re.I)
YEARS = re.compile(
    r"(?<![A-Za-z\d])(?P<minimum>\d{1,2}|[一二三四五六七八九十两])\s*"
    r"(?:(?:[-~～至到–—])\s*(?:\d{1,2}|[一二三四五六七八九十两])\s*)?"
    r"\+?\s*年(?:及以上|以上|以内|以下|起)?"
)
EXPERIENCE = re.compile(
    r"(?:具备|有|拥有)[^，,。；;\n]{0,35}(?:AI|Agent|开发|全栈|Vibe\s*Coding)"
    r"[^，,。；;\n]{0,25}(?:经验|经历)", re.I
)
OPEN_CONDITIONS = {
    "education": re.compile(r"学历不限|不限学历|不(?:要求|限制)学历"),
    "major": re.compile(r"专业不限|不限专业|不要求科班(?:出身)?|不(?:要求|限制)[^，,。；;\n]{0,16}(?:专业|背景)|非计算机[^，,。；;\n]{0,8}专业[^，,。；;\n]{0,8}(?:也可|亦可)"),
    "experience": re.compile(r"经验不限|不限经验|无需[^，,。；;\n]{0,8}经验|不要求[^，,。；;\n]{0,8}经验"),
}
EXCEPTION = re.compile(r"(?:接受|欢迎)[^，,。；;\n]{0,12}应届|应届[^。；;\n]{0,16}(?:也可|亦可|可投)|可放宽|可替代")
LABELS = {"education": "学历", "major": "专业", "school": "院校", "experience": "经验", "eligibility": "应届/在校身份"}


def _sentences(text: str):
    mode = "required"
    for part in re.split(f"({HEADINGS.pattern})", text):
        if HEADINGS.fullmatch(part):
            mode = (
                "preferred" if part in {"加分项", "优先条件", "优先考虑"}
                else "ignore" if part in {"岗位职责", "工作职责", "主要职责", "公司介绍", "关于我们", "岗位定位", "职位概述", "我们提供"}
                else "required"
            )
            continue
        if mode == "ignore":
            continue
        for sentence in re.split(r"[\n。；;]+", part):
            sentence = sentence.strip()
            if sentence:
                yield sentence, mode


def extract_fit_requirements(description: str) -> list[dict[str, Any]]:
    conditions: list[dict[str, Any]] = []

    def add(category, kind, evidence, value=None):
        item = {"category": category, "label": LABELS[category], "kind": kind, "evidence": evidence, "value": value}
        if item not in conditions:
            conditions.append(item)

    for sentence, mode in _sentences(description):
        # Commas separate requirements such as "硕士及以上，计算机专业优先".
        # Keep the complete sentence as evidence so exceptions remain visible.
        for part in re.split(r"[，,]", sentence):
            part = part.strip()
            if not part:
                continue
            kind = "preferred" if mode == "preferred" or PREFERRED.search(part) else "required"
            open_categories = set()
            for category, pattern in OPEN_CONDITIONS.items():
                if pattern.search(part):
                    add(category, "unrestricted", sentence)
                    open_categories.add(category)

            degrees = list(DEGREE.finditer(part))
            if degrees and "education" not in open_categories:
                # Degree alternatives (硕士、博士 / 本科或硕士) use the lowest
                # allowed level; 本科及以上、硕士优先 are separate conditions.
                groups = []
                for match in degrees:
                    if groups and re.fullmatch(r"[\s、/或和及]+", part[groups[-1][-1].end():match.start()]):
                        groups[-1].append(match)
                    else:
                        groups.append([match])
                for index, group in enumerate(groups):
                    first = group[0]
                    end = groups[index + 1][0].start() if index + 1 < len(groups) else len(part)
                    local = part[first.start():end]
                    degree_kind = "preferred" if mode == "preferred" or PREFERRED.search(local) else "required"
                    # School or major mentions alone are not degree requirements.
                    degree_context = re.search(r"学历|学位|毕业|在读|在校|及以上|以上|要求|必须|优先", part)
                    if degree_context or mode == "required" and re.fullmatch(r"[\d.、\s]*(?:硕士|博士|本科|大专|专科)", part):
                        if is_negated(part, first.start()):
                            degree_kind = "unrestricted"
                        add("education", degree_kind, sentence, min(DEGREES[m.group()] for m in group))

            major = MAJOR.search(part)
            if major and "major" not in open_categories:
                major_kind = "unrestricted" if is_negated(part, major.start()) else kind
                if major_kind == "required" and re.search(r"[，,、]?\s*或(?:者)?(?:具有|具备|有).{0,20}(?:经验|经历)", sentence):
                    major_kind = "conditional"
                # A boolean "non-CS major" cannot rule out a job that also
                # accepts finance/economics or other disciplines.
                broader = re.search(r"金融|经济|经管|管理|数学|统计|电子|自动化|设计", part)
                add("major", major_kind, sentence, "broader_major" if broader else "related_major")
            school = SCHOOL.search(part)
            if school:
                add("school", "unrestricted" if is_negated(part, school.start()) else kind, sentence, "elite_school")

            year_matches = list(YEARS.finditer(part))
            if year_matches and "experience" not in open_categories:
                for match in year_matches:
                    context = part[max(0, match.start() - 15):match.end() + 20]
                    if not re.search(r"经验|经历|工作|开发|从业", context) or re.search(r"成立|创立|深耕|历史", part):
                        continue
                    raw_years = match.group("minimum")
                    minimum = int(raw_years) if raw_years.isdigit() else {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}[raw_years]
                    if "以内" in match.group() or "以下" in match.group():
                        minimum = 0
                    year_kind = kind
                    if is_negated(part, match.start()):
                        year_kind = "unrestricted"
                    elif kind == "required" and (EXCEPTION.search(sentence) or len(DEGREE.findall(sentence)) > 1):
                        year_kind = "conditional"
                    add("experience", year_kind, sentence, minimum)
            elif "experience" not in open_categories:
                experience = EXPERIENCE.search(part)
                if experience:
                    add("experience", "unrestricted" if is_negated(part, experience.start()) else kind, sentence)

            if re.search(r"应届毕业生|在校生|在读", part) and not re.search(r"接受|欢迎|也可|亦可|不限|优先", sentence):
                add("eligibility", kind, sentence, "graduate_eligible")
    return conditions
