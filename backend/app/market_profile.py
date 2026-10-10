"""Read-only keyword frequencies for the locally collected JD sample library."""

import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from collections import Counter
import math

from app.jd_signals import normalize, clauses, positive_match


# English token boundaries deliberately allow adjacent Chinese characters.
KEYWORD_PATTERNS = (
    ("Codex", r"(?<![a-z0-9_])codex(?![a-z0-9_])"),
    ("Agent", r"(?<![a-z0-9_])agents?(?![a-z0-9_])|智能体"),
    ("Python", r"(?<![a-z0-9_])python(?![a-z0-9_])"),
    ("React", r"(?<![a-z0-9_])react(?![a-z0-9_])"),
    ("部署", r"部署"),
    ("调试", r"调试"),
    ("MCP", r"(?<![a-z0-9_])mcp(?![a-z0-9_])|mcpserver"),
    ("RAG", r"(?<![a-z0-9_])rag(?![a-z0-9_])|检索增强"),
    ("Prompt", r"prompt|提示词"),
    ("Dify", r"dify"), ("Coze", r"coze|扣子"),
    ("工作流", r"工作流|workflow"),
)

ROLE_FAMILY_LABELS = {
    "ai_tool_automation": "AI 工具与自动化",
    "vibe_coding_fullstack": "Vibe Coding 全栈",
    "agent_application": "Agent 应用开发",
    "ai_product_operations": "AI 产品与运营",
    "internal_intelligence": "内部智能化系统",
    "indie_ai_developer": "独立开发/一人公司",
    "unclassified": "待确认方向",
}

PROFILE_CATALOGS = {
    "技术栈": (
        ("Python", r"(?<![a-z0-9_])python(?![a-z0-9_])"), ("JavaScript", r"(?<![a-z0-9_])javascript(?![a-z0-9_])"),
        ("TypeScript", r"(?<![a-z0-9_])typescript(?![a-z0-9_])"), ("React", r"(?<![a-z0-9_])react(?![a-z0-9_])"),
        ("Vue", r"(?<![a-z0-9_])vue(?![a-z0-9_])"), ("Next.js", r"(?<![a-z0-9_])next\.js(?![a-z0-9_])"),
        ("Node.js", r"(?<![a-z0-9_])node\.js(?![a-z0-9_])"), ("Java", r"(?<![a-z0-9_])java(?![a-z0-9_])"),
        ("Go", r"(?<![a-z0-9_])go(?![a-z0-9_])"), ("FastAPI", r"(?<![a-z0-9_])fastapi(?![a-z0-9_])"),
        ("API", r"(?<![a-z0-9_])api(?![a-z0-9_])"), ("SQL", r"(?<![a-z0-9_])sql(?![a-z0-9_])"),
        ("MySQL", r"(?<![a-z0-9_])mysql(?![a-z0-9_])"), ("PostgreSQL", r"(?<![a-z0-9_])postgresql(?![a-z0-9_])"),
        ("MongoDB", r"(?<![a-z0-9_])mongodb(?![a-z0-9_])"), ("Redis", r"(?<![a-z0-9_])redis(?![a-z0-9_])"),
        ("C++", r"(?<![a-z0-9_])c\+\+(?!\+)"), ("C#", r"(?<![a-z0-9_])c#"), ("C", r"(?<![a-z0-9_])c(?![a-z0-9_+#])"),
        ("Git", r"(?<![a-z0-9_])git(?![a-z0-9_])"), ("Docker", r"(?<![a-z0-9_])docker(?![a-z0-9_])"),
        ("Linux", r"(?<![a-z0-9_])linux(?![a-z0-9_])"), ("Nginx", r"(?<![a-z0-9_])nginx(?![a-z0-9_])"),
        ("MCP", r"(?<![a-z0-9_])mcp(?![a-z0-9_])|mcpserver"), ("RAG", r"(?<![a-z0-9_])rag(?![a-z0-9_])|检索增强"),
        ("Prompt / 上下文工程", r"prompt|提示词|上下文工程|上下文管理"),
        ("LangChain", r"langchain"), ("LangGraph", r"langgraph"),
        ("工具调用", r"tool\s*calling|function\s*calling|工具调用"),
        ("Flask", r"flask"), ("Celery", r"celery"), ("HTTP / JSON", r"\bhttp\b|\bjson\b|rest\b"),
        ("SQLite", r"sqlite"),
    ),
    "AI 工具": (
        ("Codex", r"(?<![a-z0-9_])codex(?![a-z0-9_])"), ("Claude Code", r"claude\s*code"),
        ("Cursor", r"(?<![a-z0-9_])cursor(?![a-z0-9_])"), ("GitHub Copilot", r"github\s*copilot|(?<![a-z0-9_])copilot(?![a-z0-9_])"),
        ("Windsurf", r"(?<![a-z0-9_])windsurf(?![a-z0-9_])"), ("OpenClaw", r"(?<![a-z0-9_])openclaw(?![a-z0-9_])"),
        ("Qoder", r"(?<![a-z0-9_])qoder(?![a-z0-9_])"),
        ("Dify", r"dify"), ("Coze", r"coze|扣子"), ("ComfyUI", r"comfyui"), ("飞书 / Aily", r"飞书|aily|妙搭"), ("ChatGPT", r"(?<![a-z0-9_])chatgpt(?![a-z0-9_])"),
    ),
    "工作职责": (
        ("需求拆解", r"需求拆解|需求分析|需求挖掘"), ("前端开发", r"前端开发|页面开发"), ("后端开发", r"后端开发|后端服务"),
        ("AI/Agent 开发", r"(?:agent|智能体).{0,14}(?:开发|搭建|编排|实现)|(?:开发|搭建|编排|实现).{0,14}(?:agent|智能体)"), ("工具与自动化", r"内部工具|自动化|自动化脚本"),
        ("数据处理", r"数据处理|数据清洗|数据分析"), ("工作流设计", r"工作流|workflow|\bskills?\b"),
        ("调试与测试", r"调试|测试|bug修复|报错"), ("部署上线", r"部署|系统上线|服务上线"),
        ("评测与效果优化", r"评测|效果评估|评估基准|评估体系|swe.bench|humaneval"),
        ("插件与工具开发", r"插件.{0,8}开发|mcp\s*server|开发.{0,15}(?:plugin|skill|tool)|参数校验|鉴权|超时|重试"),
        ("内容运营与研究", r"内容运营|内容审核|选题|内容营销|竞品分析|消费者研究"),
        ("产品体验与迭代", r"产品体验|体验问题|迭代优化|用户体验"), ("客户与跨团队协作", r"客户|跨部门|业务团队|协作"),
        ("文档与培训", r"文档|使用说明|培训|教程"),
    ),
    "项目类型": (
        ("可运行 Web/后台/Demo", r"官网|web\s*demo|demo页面|管理后台|后台页面|产品原型"),
        ("AI 工具与自动化", r"内部工具|自动化|脚本|数据处理流程"), ("Agent / RAG 应用", r"agent|智能体|\brag\b|检索增强"),
        ("AI 工作流 / Skill", r"工作流|workflow|skill"), ("内部智能化系统", r"内部智能化|数据看板|内部数据"),
        ("AI 产品与运营", r"ai产品|产品配置|内容营销|运营"), ("移动 App", r"移动应用|app开发"),
    ),
    "学历与经验": (
        ("本科及以上", r"本科及以上|本科以上"), ("硕士/博士", r"硕士|博士"), ("大专及以上", r"大专及以上"), ("实习出勤", r"每周.{0,6}[天日]|至少.{0,6}个月|实习期"), ("硕士在读", r"硕士在读"), ("计算机/AI相关专业", r"(?:计算机|软件工程|人工智能|自动化|电子信息)[^。；;\n]{0,45}专业"),
        ("优秀应届/在读可投", r"优秀应届|应届毕业生|在校大学生|本科及以上在读"), ("1-3 年经验", r"1\s*[-－~至]\s*3\s*年|1-3年"),
        ("真实项目/作品", r"真实项目|个人作品|开源项目|github|gitee|可访问demo|代表性作品"), ("实习经历", r"实习"),
    ),
    "交付能力": (
        ("独立完成开发闭环", r"独立完成|完整闭环|端到端|全流程"), ("从需求到上线", r"需求.*?(开发|实现).*?(部署|上线)|需求.*?上线"),
        ("原型 / MVP 验证", r"原型|mvp|验证"), ("前后端与数据存储", r"前端.*?(后端|数据存储)|后端.*?(前端|数据存储)"),
        ("调试测试与迭代", r"调试.*?(测试|迭代)|测试.*?(迭代|调试)|bug修复"), ("部署与维护", r"部署|上线|维护|生产环境"),
        ("可演示作品", r"可演示|可访问demo|作品|github|gitee"),
    ),
}


TITLE_RULES = (
    ("ai_product_operations", r"产品经理|产品.*?(?:实习|运营)|内容.*?(?:工程|运营)"),
    ("agent_application", r"agent.*?(?:开发|工程)|智能体.*?(?:开发|工程)|prompt|上下文"),
    ("indie_ai_developer", r"一人公司|独立开发|开发专家"),
    ("internal_intelligence", r"内部智能化|智能化方向"),
    ("ai_tool_automation", r"工具开发|工作流搭建|workflow|自动化"),
    ("vibe_coding_fullstack", r"全栈|vibe\s*coding"),
)
BODY_RULES = {
    "agent_application": r"agent.{0,15}(?:开发|能力建设|推理|插件|作品)|智能体|mcp|tool\s*calling|rag|prompt|提示词",
    "ai_product_operations": r"内容运营|选题|消费者|市场洞察|竞品分析|产品规划",
    "internal_intelligence": r"内部智能化|内部数据|业务流程|内部.*?系统|各部门",
    "ai_tool_automation": r"自动化|脚本|excel|csv|数据处理|工作流|workflow",
    "vibe_coding_fullstack": r"前端|后端|全栈|web|小程序|数据库|部署",
    "indie_ai_developer": r"一人公司|独立开发移动|app开发",
}


def suggest_role_family(title: str, description: str) -> dict[str, object]:
    title, body = normalize(title), normalize(description)
    title_hit = next(((family, re.search(pattern, title, re.I)) for family, pattern in TITLE_RULES if re.search(pattern, title, re.I)), None)
    if title_hit:
        family, hit = title_hit
        matches, score = [hit.group()], 10
    elif re.search(r"agent.{0,12}(?:推理|行动循环|插件生态|核心开发)", body, re.I):
        family, matches, score = "agent_application", ["Agent 推理/插件开发职责"], 12
    else:
        scores = []
        for family, pattern in BODY_RULES.items():
            matches = sorted({m.group().casefold() for m in re.finditer(pattern, body, re.I)})
            scores.append((len(matches), family, matches))
        score, family, matches = max(scores)
        if not score:
            family, matches = "unclassified", ["现有六类方向缺少直接依据，待人工确认"]
    return {"family": family, "label": ROLE_FAMILY_LABELS[family], "reasons": matches, "score": score,
            "confidence": "低" if score < 3 else "中" if score < 10 else "高"}


def role_family(row) -> str:
    if row["analysis_status"] == "confirmed" and row["role_family"] in ROLE_FAMILY_LABELS:
        return row["role_family"]
    return suggest_role_family(row["title"], row["description"])["family"]


def read_job(database_path: Path, job_id: int):
    with closing(sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """SELECT jobs.*, job_analyses.role_family, job_analyses.analysis_status FROM jobs
               LEFT JOIN job_analyses ON job_analyses.job_id=jobs.id AND job_analyses.is_current=1
               WHERE jobs.id=?""", (job_id,)).fetchone()


def extract_requirements(text: str, collapse_alternatives: bool = False) -> list[dict]:
    result = {}
    priority = {"任职要求": 3, "职责": 3, "正文提及": 2, "加分项": 1}
    for sentence, kind in clauses(text):
        for category, catalog in PROFILE_CATALOGS.items():
            for name, expression in catalog:
                match = positive_match(expression, sentence)
                if match:
                    key = (category, name)
                    if key not in result or priority[kind] > priority[result[key]["kind"]]:
                        result[key] = {"requirement": name, "category": category, "expression": expression,
                                       "kind": kind, "jd_evidence": sentence, "matched_text": match.group()}
    items = list(result.values())
    return _collapse_alternatives(items) if collapse_alternatives else items


def _collapse_alternatives(items: list[dict]) -> list[dict]:
    """Only group explicitly stated minimum-choice requirements, never infer AND/OR."""
    number = {"1": 1, "一": 1, "2": 2, "二": 2, "两": 2, "3": 3, "三": 3}
    languages = {"Python", "JavaScript", "TypeScript", "Java", "Go", "C", "C++", "C#"}
    groups = {}
    for index, item in enumerate(items):
        sentence = item["jd_evidence"]
        minimum = re.search(r"至少\s*([1一2二两3三])\s*(?:种|款|门)", sentence)
        if not minimum:
            continue
        label = ("编程语言" if item["category"] == "技术栈" and item["requirement"] in languages and "语言" in sentence
                 else "AI 工具" if item["category"] == "AI 工具" else None)
        if label:
            groups.setdefault((sentence, label, number[minimum[1]]), []).append(index)
    replaced = {}
    removed = set()
    for (_, label, minimum), indexes in groups.items():
        if len(indexes) < 2 or len(indexes) < minimum:
            continue
        options = [{"name": items[i]["requirement"], "expression": items[i]["expression"]} for i in indexes]
        replaced[indexes[0]] = {**items[indexes[0]], "requirement": f"{label}（至少 {minimum} 种）",
                                "expression": "|".join(f"(?:{x['expression']})" for x in options),
                                "alternatives": options, "minimum_options": minimum}
        removed.update(indexes[1:])
    return [replaced.get(i, item) for i, item in enumerate(items) if i not in removed]


def _read_usable_samples(database_path: Path) -> tuple[list[sqlite3.Row], int, int]:
    with closing(sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT jobs.id, jobs.title, jobs.description, jobs.sample_status, jobs.duplicate_of,
                      job_analyses.role_family, job_analyses.analysis_status
               FROM jobs LEFT JOIN job_analyses
               ON job_analyses.job_id = jobs.id AND job_analyses.is_current = 1 ORDER BY jobs.id"""
        ).fetchall()
    seen_bodies: set[str] = set()
    samples, duplicates, invalid = [], 0, 0
    for row in rows:
        body = unicodedata.normalize("NFKC", row["description"])
        fingerprint = re.sub(r"\s+", "", body).casefold()
        if row["sample_status"] == "invalid" or not fingerprint:
            invalid += 1
        elif row["sample_status"] == "duplicate" or row["duplicate_of"] is not None or fingerprint in seen_bodies:
            duplicates += 1
        else:
            seen_bodies.add(fingerprint)
            samples.append(row)
    return samples, duplicates, invalid


def get_keyword_frequencies(database_path: Path) -> dict[str, object]:
    """Count mentions, not requirements; never update the source database."""
    samples, duplicate_count, invalid_count = _read_usable_samples(database_path)

    items = []
    for keyword, expression in KEYWORD_PATTERNS:
        pattern = re.compile(expression, re.IGNORECASE)
        jobs = []
        for row in samples:
            body = unicodedata.normalize("NFKC", row["description"])
            matches = list(pattern.finditer(body))
            if not matches:
                continue
            # Locate evidence in the same normalized text used for matching.
            first = matches[0]
            start, end = max(0, first.start() - 28), min(len(body), first.end() + 48)
            evidence = ("…" if start else "") + body[start:end] + ("…" if end < len(body) else "")
            jobs.append({
                "id": row["id"],
                "title": row["title"],
                "occurrences": len(matches),
                "evidence": evidence,
            })
        items.append({
            "keyword": keyword,
            "job_count": len(jobs),
            "percentage": round(len(jobs) / len(samples) * 100, 1) if samples else 0,
            "occurrences": sum(job["occurrences"] for job in jobs),
            "jobs": jobs,
        })

    items.sort(key=lambda item: -item["job_count"])
    return {
        "total_records": len(samples) + duplicate_count + invalid_count,
        "sample_count": len(samples),
        "excluded_duplicates": duplicate_count,
        "excluded_invalid": invalid_count,
        "items": items,
    }


def _profile_items(samples, catalog) -> list[dict]:
    items = []
    for name, expression in catalog:
        jobs = []
        for row in samples:
            hits = [(sentence, kind) for sentence, kind in clauses(row["description"]) if positive_match(expression, sentence)]
            if hits:
                sentence, kind = next((hit for hit in hits if hit[1] != "加分项"), hits[0])
                jobs.append({"id": row["id"], "title": row["title"], "evidence": sentence,
                             "kind": kind, "bonus_only": all(hit[1] == "加分项" for hit in hits)})
        if jobs:
            items.append({"name": name, "job_count": len(jobs), "percentage": round(len(jobs) / len(samples) * 100, 1),
                          "bonus_count": sum(job["bonus_only"] for job in jobs), "jobs": jobs})
    return sorted(items, key=lambda item: (-item["job_count"], item["name"]))


def _names(sections: dict[str, list[dict[str, object]]], section: str, limit: int = 3) -> list[str]:
    return [str(item["name"]) for item in sections[section] if item["job_count"] >= 2 and item["percentage"] >= 40 and item["job_count"] > item.get("bonus_count", 0)][:limit]


def _join(names: list[str]) -> str:
    return "、".join(names) if names else "暂未形成稳定信号"


def _build_portrait(label: str, sample_count: int, sections: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    """Turn observed signals into concise, evidence-bounded reading guidance."""
    tools = _names(sections, "AI 工具")
    responsibilities = _names(sections, "工作职责")
    delivery = _names(sections, "交付能力")
    projects = _names(sections, "项目类型", 2)
    barriers = _names(sections, "学历与经验", 2)
    if sample_count == 0:
        return {"summary": f"当前还没有归入“{label}”的有效岗位样本。", "resume_focus": [], "barriers": []}
    qualifiers = "样本较少，以下仅作初步观察；" if sample_count < 5 else ""
    summary = (
        qualifiers +
        f"当前 {sample_count} 份“{label}”样本中，常见 AI 工具是{_join(tools)}；"
        f"工作内容集中在{_join(responsibilities)}；交付上常提到{_join(delivery)}。"
    )
    resume_focus = []
    if tools:
        resume_focus.append("说明已实际使用的 AI 工具如何参与项目与交付")
    if projects:
        resume_focus.append(f"优先展示{_join(projects)}相关项目")
    if delivery:
        resume_focus.append(f"写清{_join(delivery[:2])}的实际证据")
    return {"summary": summary, "resume_focus": resume_focus, "barriers": barriers}


def get_role_profiles(database_path: Path, exclude_job_id: int | None = None) -> dict[str, object]:
    """Return a read-only, evidence-backed market profile per job direction."""
    samples, duplicates, invalid = _read_usable_samples(database_path)
    if exclude_job_id is not None:
        target = read_job(database_path, exclude_job_id)
        if target:
            body = re.sub(r"\s+", "", normalize(target["description"])).casefold()
            samples = [row for row in samples if row["id"] != exclude_job_id and re.sub(r"\s+", "", normalize(row["description"])).casefold() != body]
    groups: dict[str, list[sqlite3.Row]] = {family: [] for family in ROLE_FAMILY_LABELS}
    confirmed_count = 0
    suggested_count = 0
    for row in samples:
        if row["analysis_status"] == "confirmed" and row["role_family"] in groups:
            family = row["role_family"]
            confirmed_count += 1
        else:
            family = suggest_role_family(row["title"], row["description"])["family"]
            suggested_count += 1
        groups[family].append(row)

    profiles = []
    for family, label in ROLE_FAMILY_LABELS.items():
        group_samples = groups[family]
        section_items = {name: _profile_items(group_samples, catalog) for name, catalog in PROFILE_CATALOGS.items()}
        profiles.append({
            "family": family,
            "label": label,
            "sample_count": len(group_samples),
            "portrait": _build_portrait(label, len(group_samples), section_items),
            "sections": [{"name": section, "items": items} for section, items in section_items.items()],
        })
    return {
        "total_records": len(samples) + duplicates + invalid,
        "sample_count": len(samples),
        "excluded_duplicates": duplicates,
        "excluded_invalid": invalid,
        "confirmed_count": confirmed_count,
        "suggested_count": suggested_count,
        "profiles": profiles,
    }


NOISE_PATTERNS = (
    ("通用沟通素质表述（仍需结合职责）", r"沟通能力良好|良好的沟通能力|良好的团队合作精神"),
    ("学习与自驱", r"学习意愿|学习能力|自驱|主动性|探索热情"),
    ("责任心与抗压", r"责任心|抗压|吃苦"),
)


def _job_signals(row: sqlite3.Row) -> tuple[dict[str, list[dict[str, object]]], str]:
    """Extract the same explainable catalog signals for a single target JD."""
    return ({name: _profile_items([row], catalog) for name, catalog in PROFILE_CATALOGS.items()}, unicodedata.normalize("NFKC", row["description"]))


def compare_job_to_market(database_path: Path, job_id: int) -> dict[str, object]:
    """Compare one JD against other usable samples in its role family without writes."""
    samples, _, _ = _read_usable_samples(database_path)
    target = read_job(database_path, job_id)
    if target is None:
        return {"status": "job_not_found"}
    family = role_family(target)
    label = ROLE_FAMILY_LABELS[family]
    fingerprint = re.sub(r"\s+", "", normalize(target["description"])).casefold()
    baseline = [row for row in samples if role_family(row) == family
                and re.sub(r"\s+", "", normalize(row["description"])).casefold() != fingerprint]
    target_sections, target_text = _job_signals(target)
    baseline_sections = {name: _profile_items(baseline, catalog) for name, catalog in PROFILE_CATALOGS.items()}
    target_names = {name: {str(item["name"]) for item in items} for name, items in target_sections.items()}

    typical, missing_common, especially = [], [], []
    for section, baseline_items in baseline_sections.items():
        for item in baseline_items:
            name, count, percentage = str(item["name"]), int(item["job_count"]), float(item["percentage"])
            entry = {"section": section, "name": name, "job_count": count, "percentage": percentage}
            if count >= 2 and percentage >= 40:
                if name in target_names[section]:
                    typical.append(entry)
                else:
                    missing_common.append(entry)
        for item in target_sections[section]:
            name = str(item["name"])
            baseline_item = next((candidate for candidate in baseline_items if candidate["name"] == name), None)
            baseline_percentage = float(baseline_item["percentage"]) if baseline_item else 0
            if len(baseline) >= 3 and baseline_percentage < 40:
                especially.append({"section": section, "name": name, "market_percentage": baseline_percentage})

    noise = [noise_label for noise_label, expression in NOISE_PATTERNS if re.search(expression, target_text, re.IGNORECASE)]
    sort_key = lambda item: (-float(item.get("percentage", item.get("market_percentage", 0))), str(item["name"]))
    return {
        "status": "ready", "job_id": job_id, "family": family, "family_label": label, "baseline_count": len(baseline),
        "typical_requirements": sorted(typical, key=sort_key)[:8],
        "especially_emphasized": sorted(especially, key=sort_key)[:6],
        "common_but_not_mentioned": sorted(missing_common, key=sort_key)[:6],
        "possible_copywriting_noise": noise,
        "sample_note": "少于 3 条同类参考，暂不判断独有要求。" if len(baseline) < 3 else "常见要求指至少 2 条、40% 同类参考提及；不等于目标岗位必需。",
    }


SIMILARITY_WEIGHTS = {
    "AI 工具": 5,
    "技术栈": 3,
    "工作职责": 4,
    "项目类型": 3,
    "交付能力": 3,
    "学历与经验": 1,
}


def _signal_names(row: sqlite3.Row) -> dict[str, set[str]]:
    return {
        section: {str(item["name"]) for item in _profile_items([row], catalog)}
        for section, catalog in PROFILE_CATALOGS.items()
    }


def find_similar_jobs(database_path: Path, job_id: int, limit: int = 5) -> dict[str, object]:
    """Weighted Jaccard + corpus rarity, bounded 0-100; no same-family-only fill."""
    samples, duplicates, invalid = _read_usable_samples(database_path)
    target = read_job(database_path, job_id)
    if target is None:
        return {"status": "job_not_found", "items": []}
    family = role_family(target)
    fingerprint = re.sub(r"\s+", "", normalize(target["description"])).casefold()
    samples = [row for row in samples if re.sub(r"\s+", "", normalize(row["description"])).casefold() != fingerprint]
    def tokens(row):
        return {(x["category"], x["requirement"]) for x in extract_requirements(row["description"])
                if x["category"] != "学历与经验"}
    target_tokens = tokens(target)
    corpus = [(row, tokens(row)) for row in samples]
    frequency = Counter(token for _, values in corpus for token in values)
    def weight(token):
        return SIMILARITY_WEIGHTS[token[0]] * (1 + math.log((len(corpus) + 1) / (frequency[token] + 1)))
    items = []
    for candidate, values in corpus:
        shared = values & target_tokens
        if len(shared) < 2:
            continue
        union = values | target_tokens
        similarity = sum(weight(x) for x in shared) / sum(weight(x) for x in union)
        if similarity < 0.12:
            continue
        candidate_family = role_family(candidate)
        same = candidate_family == family and family != "unclassified"
        score = round(100 * similarity, 1)
        ranked = sorted(shared, key=lambda x: (-weight(x), x))
        shared_signals = [{"section": section, "name": name} for section, name in ranked]
        reasons = ([f"同属{ROLE_FAMILY_LABELS[family]}"] if same else ["跨方向参考，共有能力相近"])
        reasons += [f"同提到{name}（{section}）" for section, name in ranked[:4]]
        items.append({"id": candidate["id"], "title": candidate["title"], "score": score,
                      "family": candidate_family, "family_label": ROLE_FAMILY_LABELS[candidate_family],
                      "same_family": same, "shared_signals": shared_signals, "reasons": reasons})
    items.sort(key=lambda item: (not item["same_family"], -item["score"], item["id"]))
    limit = max(1, min(limit, 10))
    return {"status": "ready", "job_id": job_id, "target_family": family,
            "target_family_label": ROLE_FAMILY_LABELS[family], "items": items[:limit],
            "available_candidates": len(items), "excluded_duplicates": duplicates, "excluded_invalid": invalid,
            "score_note": "0–100 的 JD 内容相似分，仅用于选参考；不是个人胜任度或录用概率。",
            "sample_note": "相近样本不足，按实际数量返回。" if len(items) < 3 else "同方向优先，共有能力至少 2 项；低相似内容不凑数。"}
