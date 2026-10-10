import os
import asyncio
import json
import re
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Image as ReportLabImage
from reportlab.platypus import KeepInFrame, Paragraph, Spacer, Table, TableStyle

from app.jd_batch import build_batch_preview, split_batch_jds
from app.fact_matching import build_fact_match_table
from app.candidate_descriptions import build_project_candidate_descriptions
from app.collection_relevance import evaluate_staging_items, read_reference_jobs
from app.collection_discovery import rank_moka_candidates
from app.candidate_fit import load_candidate_fit_profile
from app.collection_gate import DIRECTIONS, assess_batch_job
from app.config import load_local_env
from app.deepseek_client import DeepSeekError, connection_status as deepseek_connection_status, test_connection as test_deepseek_connection
from app.deepseek_candidates import (
    CandidateError,
    apply_candidate_to_draft,
    generate_candidate_descriptions,
    prepare_candidate_context,
)
from collector.batch import BatchBusyError, BatchCollector, read_formal_fingerprints
from collector.scheduler import CollectionScheduler
from app.agent_v1 import build_agent_v1
from app.jd_signals import normalize, requirement_match_count
from app.market_profile import extract_requirements, compare_job_to_market, find_similar_jobs, get_keyword_frequencies, get_role_profiles, suggest_role_family
from app.project_facts import ProjectFactError, confirm_project_fact_card, list_project_fact_cards, save_project_fact_card
from app.storage import find_job_duplicate_candidates, migrate_jd_sample_schema, save_batch_job_samples, save_csv_job_samples
from collector.staging import (
    StagingReadError,
    read_staging,
    resolve_staging_record,
    stage_unique_jobs,
)
from collector.moka_client import (
    MokaRequestError,
    fetch_public_job,
    fetch_public_job_list,
)

LOCAL_CONFIG_ERROR = load_local_env()

@asynccontextmanager
async def lifespan(application):
    COLLECTION_SCHEDULER.start()
    try:
        yield
    finally:
        await asyncio.to_thread(COLLECTION_SCHEDULER.stop)


app = FastAPI(title="Resume Tailor API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
    ).split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2].parent / "resume-tailor-data"
DATA_DIR = Path(os.getenv("DATA_DIR", str(DEFAULT_DATA_DIR))).resolve()
DB_PATH = DATA_DIR / "runtime" / "app.sqlite3"
PROJECT_FACTS_DIR = DATA_DIR / "project-facts"
CANDIDATE_FIT_PROFILE_PATH = DATA_DIR / "candidate-profile" / "fit-profile.json"
BATCH_COLLECTOR = BatchCollector(DATA_DIR, assess_batch_job, DIRECTIONS)
COLLECTION_SCHEDULER = CollectionScheduler(
    BATCH_COLLECTOR,
    lambda: load_candidate_fit_profile(CANDIDATE_FIT_PROFILE_PATH),
    lambda: read_formal_fingerprints(DB_PATH),
)
KEYWORD_CATALOG = (
    "Vibe Coding", "AI Coding", "Agent", "RPA", "自动化", "数据处理", "Excel", "CSV",
    "Python", "JavaScript", "TypeScript", "HTML/CSS", "React", "FastAPI", "API", "命令行",
    "Git", "全栈", "部署", "调试", "Prompt", "LangChain", "LangGraph", "产品运营",
    "内容运营", "抖音", "小红书", "文旅营销",
)
KEYWORD_CATEGORIES = {
    "工具": {"Cursor", "Claude Code", "Codex", "OpenClaw", "Trae", "Windsurf", "Copilot", "Excel", "CSV"},
    "技术": {"Python", "JavaScript", "TypeScript", "HTML/CSS", "React", "FastAPI", "API", "Git", "LangChain", "LangGraph"},
    "能力": {"自动化", "数据处理", "命令行", "调试", "部署", "Prompt", "全栈", "RPA"},
    "岗位方向": {"Vibe Coding", "AI Coding", "Agent", "产品运营", "内容运营", "抖音", "小红书", "文旅营销"},
}
HIGHLIGHT_KEYWORDS = {
    "核心要求": {"AI Coding", "Agent", "Vibe Coding", "全栈", "Python", "JavaScript", "React", "FastAPI", "Git", "LangChain", "LangGraph"},
    "主要职责": {"自动化", "数据处理", "需求拆解", "调试", "测试", "部署", "产品化", "迭代", "培训", "协作"},
    "加分项": {"RPA", "开源项目", "个人产品", "Demo", "Copilot", "OpenClaw"},
    "基础要求": {"学历", "经验", "沟通", "表达", "学习", "自驱"},
}
RESUME_SECTION_NAMES = ("个人简介", "教育背景", "工作经历", "项目经历", "技术与工具", "开发方式")


def _docx_paragraph(
    text: str,
    style: str,
    bullet: bool = False,
    alignment: str | None = None,
    bold: bool = False,
) -> str:
    paragraph_properties = [f'<w:pStyle w:val="{style}"/>']
    if bullet:
        paragraph_properties.append('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
    if alignment:
        paragraph_properties.append(f'<w:jc w:val="{alignment}"/>')
    run_properties = '<w:rPr><w:b/></w:rPr>' if bold else ''
    return (
        '<w:p><w:pPr>' + ''.join(paragraph_properties) + '</w:pPr>'
        '<w:r>' + run_properties + '<w:t xml:space="preserve">' + escape(text) + '</w:t></w:r></w:p>'
    )


def _docx_labeled_paragraph(label: str, value: str) -> str:
    return (
        '<w:p><w:pPr><w:pStyle w:val="ResumeInfo"/></w:pPr>'
        '<w:r><w:rPr><w:b/></w:rPr><w:t>' + escape(f'{label}：') + '</w:t></w:r>'
        '<w:r><w:t xml:space="preserve">' + escape(value or '[待补充]') + '</w:t></w:r></w:p>'
    )


def _docx_table(
    rows: list[list[str]],
    widths: list[int],
    bottom_border: int = 0,
    cell_top: int = 20,
    cell_bottom: int = 20,
) -> str:
    total_width = sum(widths)
    border_value = (
        f'<w:bottom w:val="single" w:sz="{bottom_border}" w:space="0" w:color="111111"/>'
        if bottom_border
        else '<w:bottom w:val="nil"/>'
    )
    table_properties = (
        f'<w:tblPr><w:tblW w:w="{total_width}" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
        '<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/>'
        + border_value
        + '<w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
        '<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
        '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar></w:tblPr>'
    )
    grid = '<w:tblGrid>' + ''.join(f'<w:gridCol w:w="{width}"/>' for width in widths) + '</w:tblGrid>'
    row_xml: list[str] = []
    for row in rows:
        cells = []
        for index, paragraph in enumerate(row):
            width = widths[index]
            cells.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>'
                f'<w:tcMar><w:top w:w="{cell_top}" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
                f'<w:bottom w:w="{cell_bottom}" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tcMar>'
                '</w:tcPr>' + paragraph + '</w:tc>'
            )
        row_xml.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>' + ''.join(cells) + '</w:tr>')
    return '<w:tbl>' + table_properties + grid + ''.join(row_xml) + '</w:tbl>'


def build_resume_docx(job_title: str, draft: dict[str, object]) -> bytes:
    sections = draft.get("sections", {})
    if not isinstance(sections, dict):
        sections = {}
    personal = [str(item) for item in sections.get("个人简介", []) if str(item).strip()]
    name = next((item for item in personal if item == "[姓名]" or "姓名" in item), "[姓名]")
    contact = next((item for item in personal if "电话" in item or "邮箱" in item), "")
    role = next((item for item in personal if ("|" in item or "｜" in item) and item not in {name, contact}), job_title)
    personal_body = [item for item in personal if item not in {name, role, contact}]
    page_width = 10206

    def section_header(chinese: str, english: str) -> str:
        return _docx_table(
            [[
                _docx_paragraph(chinese, "ResumeSectionCN", alignment="left"),
                _docx_paragraph(english, "ResumeSectionEN", alignment="right"),
            ]],
            [5800, page_width - 5800],
            bottom_border=8,
            cell_top=70,
            cell_bottom=25,
        )

    def detail_row(left_text: str, center_text: str, right_text: str, emphasize_center: bool = False) -> str:
        return _docx_table(
            [[
                _docx_paragraph(left_text, "ResumeRow", alignment="left"),
                _docx_paragraph(center_text, "ResumeRow", alignment="center", bold=emphasize_center),
                _docx_paragraph(right_text, "ResumeRow", alignment="right"),
            ]],
            [3160, 4080, page_width - 7240],
            cell_top=20,
            cell_bottom=15,
        )

    education_lines = [str(item) for item in sections.get("教育背景", []) if str(item).strip()]
    education_parts = _split_resume_line(education_lines[0] if education_lines else "", 3)
    school, major, education_time = education_parts

    def contact_value(pattern: str) -> str:
        match = re.search(rf"(?:{pattern})[：:]\s*(.*?)(?=\s*[｜|·]\s*|$)", contact, re.IGNORECASE)
        return match.group(1).strip() if match else "[待补充]"

    phone = contact_value("电话|手机")
    email = contact_value("邮箱")
    github = contact_value("GitHub/Gitee|GitHub|Gitee")

    body = [
        _docx_table(
            [[
                _docx_paragraph("个人简历", "ResumeTitleCN", alignment="left"),
                _docx_paragraph(f"求职意向：{job_title}", "ResumeTitleRole", alignment="left"),
                _docx_paragraph("PERSONAL RESUME", "ResumeTitleEN", alignment="right"),
            ]],
            [2300, 4000, page_width - 6300],
            bottom_border=18,
            cell_top=0,
            cell_bottom=115,
        ),
        section_header("个人信息", "Personal information"),
        _docx_table(
            [
                [_docx_labeled_paragraph("姓名", name), _docx_labeled_paragraph("学校", school)],
                [_docx_labeled_paragraph("手机", phone), _docx_labeled_paragraph("专业", major)],
                [_docx_labeled_paragraph("邮箱", email), _docx_labeled_paragraph("GitHub/Gitee", github)],
            ],
            [page_width // 2, page_width - page_width // 2],
            cell_top=25,
            cell_bottom=25,
        ),
    ]

    if education_lines:
        body.extend([
            section_header("教育背景", "Educational background"),
            detail_row(education_time, school, major),
        ])
        body.extend(_docx_paragraph(item, "ResumeBody") for item in education_lines[1:])

    work_lines = [str(item) for item in sections.get("工作经历", []) if str(item).strip()]
    if work_lines:
        company, position, work_time = _split_resume_line(work_lines[0], 3)
        body.extend([
            section_header("工作经历", "Work experience"),
            detail_row(work_time, company, position),
        ])
        body.extend(_docx_paragraph(item, "ResumeBullet", bullet=True) for item in work_lines[1:])

    project_lines = [str(item) for item in sections.get("项目经历", []) if str(item).strip()]
    if project_lines:
        body.append(section_header("项目经历", "Project experience"))
        for paragraph in project_lines:
            if "｜个人项目" in paragraph:
                first, second, third = _split_resume_line(paragraph, 3)
                body.append(detail_row(first, second, third, emphasize_center=True))
            else:
                body.append(_docx_paragraph(paragraph, "ResumeBullet", bullet=True))

    tool_lines = [str(item) for item in sections.get("技术与工具", []) if str(item).strip()]
    workflow_lines = [str(item) for item in sections.get("开发方式", []) if str(item).strip()]
    if tool_lines or workflow_lines:
        body.append(section_header("技术与工具", "Skills and tools"))
        body.extend(_docx_paragraph(item, "ResumeBody") for item in tool_lines + workflow_lines)

    if personal_body:
        body.append(section_header("个人简介", "Self-evaluation"))
        body.extend(_docx_paragraph(item, "ResumeBody") for item in personal_body)

    document_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>''' + ''.join(body) + '''<w:sectPr>
<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="520" w:right="850" w:bottom="520" w:left="850" w:header="250" w:footer="250" w:gutter="0"/>
</w:sectPr></w:body></w:document>'''
    styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:hAnsi="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="17"/><w:szCs w:val="17"/><w:color w:val="252525"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="220" w:lineRule="auto"/><w:widowControl/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="ResumeTitleCN"><w:name w:val="Resume Title CN"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/><w:keepNext/></w:pPr><w:rPr><w:b/><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ResumeTitleRole"><w:name w:val="Resume Title Role"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/><w:keepNext/></w:pPr><w:rPr><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ResumeTitleEN"><w:name w:val="Resume Title EN"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/><w:keepNext/></w:pPr><w:rPr><w:b/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ResumeSectionCN"><w:name w:val="Resume Section CN"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/><w:keepNext/></w:pPr><w:rPr><w:b/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ResumeSectionEN"><w:name w:val="Resume Section EN"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/><w:keepNext/></w:pPr><w:rPr><w:b/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ResumeInfo"><w:name w:val="Resume Info"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="210" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ResumeRow"><w:name w:val="Resume Row"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="220" w:lineRule="auto"/><w:keepNext/></w:pPr><w:rPr><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ResumeBody"><w:name w:val="Resume Body"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="12" w:line="220" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ResumeBullet"><w:name w:val="Resume Bullet"/><w:basedOn w:val="ResumeBody"/><w:pPr><w:spacing w:after="6" w:line="220" w:lineRule="auto"/><w:ind w:left="300" w:hanging="190"/></w:pPr></w:style>
</w:styles>'''
    numbering_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:tabs><w:tab w:val="num" w:pos="300"/></w:tabs><w:ind w:left="300" w:hanging="190"/></w:pPr><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:hAnsi="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>'''
    package_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'''
    document_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/></Relationships>'''
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/styles.xml", styles_xml)
        archive.writestr("word/numbering.xml", numbering_xml)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
    return output.getvalue()


def _register_pdf_fonts() -> tuple[str, str]:
    regular_candidates = (
        Path(os.getenv("RESUME_PDF_FONT", "")),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf"),
        Path("C:/Windows/Fonts/Deng.ttf"),
    )
    bold_candidates = (
        Path(os.getenv("RESUME_PDF_FONT_BOLD", "")),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansSC-Bold.otf"),
        Path("C:/Windows/Fonts/Dengb.ttf"),
    )
    regular_path = next((path for path in regular_candidates if str(path) and path.is_file()), None)
    bold_path = next((path for path in bold_candidates if str(path) and path.is_file()), None)
    if regular_path is not None:
        try:
            pdfmetrics.registerFont(TTFont("ResumePDF", str(regular_path), subfontIndex=0))
            if bold_path is not None:
                pdfmetrics.registerFont(TTFont("ResumePDFBold", str(bold_path), subfontIndex=0))
                pdfmetrics.registerFontFamily("ResumePDF", normal="ResumePDF", bold="ResumePDFBold")
                return "ResumePDF", "ResumePDFBold"
            pdfmetrics.registerFontFamily("ResumePDF", normal="ResumePDF", bold="ResumePDF")
            return "ResumePDF", "ResumePDF"
        except Exception:
            pass
    if "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light", "STSong-Light"


def _split_resume_line(text: str, expected: int = 3) -> list[str]:
    parts = [part.strip() for part in re.split(r"[｜|]", text) if part.strip()]
    return (parts + [""] * expected)[:expected]


def build_resume_pdf(job_title: str, draft: dict[str, object]) -> bytes:
    sections = draft.get("sections", {})
    if not isinstance(sections, dict):
        sections = {}
    personal = [str(item) for item in sections.get("个人简介", []) if str(item).strip()]
    name = next((item for item in personal if item == "[姓名]" or "姓名" in item), "[姓名]")
    contact = next((item for item in personal if "电话" in item or "邮箱" in item), "")
    role = next((item for item in personal if ("|" in item or "｜" in item) and item not in {name, contact}), job_title)
    personal_body = [item for item in personal if item not in {name, role, contact}]
    regular_font, bold_font = _register_pdf_fonts()

    page_width, page_height = A4
    left = 17 * mm
    right = 17 * mm
    bottom = 10 * mm
    content_top = page_height - 34 * mm
    available_width = page_width - left - right
    available_height = content_top - bottom

    styles = {
        "section_cn": ParagraphStyle("ResumeSectionCN", fontName=bold_font, fontSize=12.5, leading=15, textColor=HexColor("#1B1B1B")),
        "section_en": ParagraphStyle("ResumeSectionEN", fontName=bold_font, fontSize=10, leading=13, alignment=2, textColor=HexColor("#242424")),
        "info": ParagraphStyle("ResumeInfo", fontName=regular_font, fontSize=9.2, leading=11.8, textColor=HexColor("#252525")),
        "photo": ParagraphStyle("ResumePhoto", fontName=regular_font, fontSize=8.6, leading=10.8, alignment=TA_CENTER, textColor=HexColor("#777777")),
        "row_left": ParagraphStyle("ResumeRowLeft", fontName=regular_font, fontSize=10.4, leading=13.2, textColor=HexColor("#202020")),
        "row_center": ParagraphStyle("ResumeRowCenter", fontName=regular_font, fontSize=10.4, leading=13.2, alignment=TA_CENTER, textColor=HexColor("#202020")),
        "project_center": ParagraphStyle("ResumeProjectCenter", fontName=bold_font, fontSize=10.4, leading=13.2, alignment=TA_CENTER, textColor=HexColor("#202020")),
        "row_right": ParagraphStyle("ResumeRowRight", fontName=regular_font, fontSize=10.4, leading=13.2, alignment=2, textColor=HexColor("#202020")),
        "body": ParagraphStyle("ResumeBody", fontName=regular_font, fontSize=9.2, leading=11.9, textColor=HexColor("#252525"), spaceAfter=0.7 * mm),
        "bullet": ParagraphStyle("ResumeBullet", fontName=regular_font, fontSize=9.2, leading=11.9, textColor=HexColor("#252525"), leftIndent=4.2 * mm, firstLineIndent=-2.8 * mm, bulletIndent=0, spaceAfter=0.35 * mm),
    }

    def section_header(chinese: str, english: str) -> Table:
        table = Table(
            [[Paragraph(escape(chinese), styles["section_cn"]), Paragraph(escape(english), styles["section_en"])]],
            colWidths=[available_width * 0.58, available_width * 0.42],
        )
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.7 * mm),
            ("LINEBELOW", (0, 0), (-1, -1), 1.1, HexColor("#111111")),
        ]))
        return table

    def labeled(label: str, value: str) -> Paragraph:
        return Paragraph(
            f'<font name="{bold_font}">{escape(label)}：</font>{escape(value or "[待补充]")}',
            styles["info"],
        )

    education_lines = [str(item) for item in sections.get("教育背景", []) if str(item).strip()]
    education_parts = _split_resume_line(education_lines[0] if education_lines else "", 3)
    school, major, education_time = education_parts
    def contact_value(pattern: str) -> str:
        match = re.search(rf"(?:{pattern})[：:]\s*(.*?)(?=\s*[｜|·]\s*|$)", contact, re.IGNORECASE)
        return match.group(1).strip() if match else "[待补充]"

    phone = contact_value("电话|手机")
    email = contact_value("邮箱")
    github = contact_value("GitHub/Gitee|GitHub|Gitee")

    photo_value = draft.get("photoPath", "")
    photo_path = Path(str(photo_value)).expanduser() if str(photo_value).strip() else None
    if photo_path is not None and photo_path.is_file():
        photo = ReportLabImage(str(photo_path), width=24 * mm, height=29 * mm, kind="proportional")
        info_table = Table(
            [
                [labeled("姓名", name), labeled("学校", school), photo],
                [labeled("手机", phone), labeled("专业", major), ""],
                [labeled("邮箱", email), labeled("GitHub/Gitee", github), ""],
            ],
            colWidths=[available_width * 0.39, available_width * 0.43, available_width * 0.18],
            rowHeights=[9.7 * mm, 9.7 * mm, 9.7 * mm],
        )
        info_table_style = [
            ("SPAN", (2, 0), (2, 2)),
            ("ALIGN", (2, 0), (2, 2), "RIGHT"),
        ]
    else:
        info_table = Table(
            [
                [labeled("姓名", name), labeled("学校", school)],
                [labeled("手机", phone), labeled("专业", major)],
                [labeled("邮箱", email), labeled("GitHub/Gitee", github)],
            ],
            colWidths=[available_width * 0.5, available_width * 0.5],
            rowHeights=[8.6 * mm, 8.6 * mm, 8.6 * mm],
        )
        info_table_style = []
    info_table.setStyle(TableStyle(info_table_style + [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    def three_column_row(left_text: str, center_text: str, right_text: str, emphasize_center: bool = False) -> Table:
        center_style = styles["project_center"] if emphasize_center else styles["row_center"]
        table = Table(
            [[
                Paragraph(escape(left_text), styles["row_left"]),
                Paragraph(escape(center_text), center_style),
                Paragraph(escape(right_text), styles["row_right"]),
            ]],
            colWidths=[available_width * 0.31, available_width * 0.40, available_width * 0.29],
        )
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.7 * mm),
        ]))
        return table

    story = [section_header("个人信息", "Personal information"), info_table, Spacer(1, 2.2 * mm)]

    if education_lines:
        story.extend([
            section_header("教育背景", "Educational background"),
            three_column_row(education_time, school, major),
        ])
        for extra in education_lines[1:]:
            story.append(Paragraph(escape(extra), styles["body"]))
        story.append(Spacer(1, 2 * mm))

    work_lines = [str(item) for item in sections.get("工作经历", []) if str(item).strip()]
    if work_lines:
        company, position, work_time = _split_resume_line(work_lines[0], 3)
        story.extend([
            section_header("工作经历", "Work experience"),
            three_column_row(work_time, company, position),
        ])
        for paragraph in work_lines[1:]:
            story.append(Paragraph(escape(paragraph), styles["bullet"], bulletText="•"))
        story.append(Spacer(1, 2 * mm))

    project_lines = [str(item) for item in sections.get("项目经历", []) if str(item).strip()]
    if project_lines:
        story.append(section_header("项目经历", "Project experience"))
        for paragraph in project_lines:
            if "｜个人项目" in paragraph:
                first, second, third = _split_resume_line(paragraph, 3)
                story.append(three_column_row(first, second, third, emphasize_center=True))
            else:
                story.append(Paragraph(escape(paragraph), styles["bullet"], bulletText="•"))
        story.append(Spacer(1, 2 * mm))

    tool_lines = [str(item) for item in sections.get("技术与工具", []) if str(item).strip()]
    workflow_lines = [str(item) for item in sections.get("开发方式", []) if str(item).strip()]
    if tool_lines or workflow_lines:
        story.append(section_header("技术与工具", "Skills and tools"))
        for paragraph in tool_lines + workflow_lines:
            story.append(Paragraph(escape(paragraph), styles["body"]))
        story.append(Spacer(1, 2 * mm))

    if personal_body:
        story.append(section_header("个人简介", "Self-evaluation"))
        for paragraph in personal_body:
            story.append(Paragraph(escape(paragraph), styles["body"]))

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    pdf.setTitle(f"简历-{job_title}")

    pdf.setFillColor(HexColor("#191919"))
    pdf.setFont(bold_font, 23)
    pdf.drawString(left, page_height - 18.5 * mm, "个人简历")
    pdf.setFont(regular_font, 11.5)
    pdf.drawString(left + 47 * mm, page_height - 18.2 * mm, f"求职意向：{job_title}")
    pdf.setFont(bold_font, 17)
    english_title = "PERSONAL RESUME"
    pdf.drawRightString(page_width - right, page_height - 18.4 * mm, english_title)
    pdf.setStrokeColor(HexColor("#111111"))
    pdf.setLineWidth(2.2)
    pdf.line(0, page_height - 27 * mm, page_width, page_height - 27 * mm)

    page_content = KeepInFrame(available_width, available_height, story, mode="shrink", mergeSpace=True)
    _, content_height = page_content.wrapOn(pdf, available_width, available_height)
    page_content.drawOn(pdf, left, content_top - content_height)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


class JobPreviewRequest(BaseModel):
    title: str
    description: str


class BatchJobPreviewRequest(BaseModel):
    text: str
    positions: list[int] | None = None


class CsvJobItem(BaseModel):
    title: str
    description: str
    company: str = ""
    source: str = ""
    source_url: str = ""


class CsvJobSaveRequest(BaseModel):
    jobs: list[CsvJobItem]


class DuplicateCheckRequest(BaseModel):
    jobs: list[CsvJobItem]


class ClassificationConfirmRequest(BaseModel):
    role_family: str


class ResumeDraftRequest(BaseModel):
    job_title: str
    sections: dict[str, list[str]]
    changes: list[str]
    source: str = ""


class CandidateGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context_hash: StrictStr = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


class CandidateApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: StrictStr = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]{32}$")
    candidate_index: StrictInt = Field(ge=0, le=1)


def initialize_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                source TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS resume_drafts (
                job_id INTEGER PRIMARY KEY,
                content_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
            """
        )
        connection.commit()

    migrate_jd_sample_schema(
        DB_PATH,
        DATA_DIR / "backups" / "database-migrations",
    )


initialize_database()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/ai/deepseek/status")
def get_deepseek_status() -> dict[str, object]:
    return deepseek_connection_status(LOCAL_CONFIG_ERROR)


@app.post("/api/ai/deepseek/test", response_model=None)
def test_deepseek_status() -> dict[str, object] | JSONResponse:
    try:
        return test_deepseek_connection(LOCAL_CONFIG_ERROR)
    except DeepSeekError as error:
        return JSONResponse(
            status_code=error.status_code,
            content={"status": "error", "code": error.code, "message": error.safe_message},
        )


@app.get("/health/storage")
def storage_health() -> dict[str, object]:
    with sqlite3.connect(DB_PATH) as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
        ).fetchone() is not None
    return {"status": "ok", "database": str(DB_PATH), "jobs_table": table_exists}


@app.post("/api/resumes")
async def upload_resume(request: Request) -> dict[str, object]:
    filename = Path(request.headers.get("x-filename", "resume")).name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".docx", ".pdf"}:
        return {"status": "error", "message": "只支持 DOCX 或 PDF 文件"}

    content = await request.body()
    if len(content) > 20 * 1024 * 1024:
        return {"status": "error", "message": "文件不能超过 20MB"}

    resume_dir = DATA_DIR / "resumes"
    resume_dir.mkdir(parents=True, exist_ok=True)
    target = resume_dir / filename
    target.write_bytes(content)
    return {"status": "saved", "filename": filename, "path": str(target), "size": len(content)}


@app.get("/api/resumes/preview")
def preview_latest_resume() -> dict[str, object]:
    resume_dir = DATA_DIR / "resumes"
    files = sorted(resume_dir.glob("*.docx"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        return {"status": "empty", "paragraphs": []}

    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(files[0]) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in root.iter(namespace + "p"):
        text = "".join(node.text or "" for node in paragraph.iter(namespace + "t")).strip()
        if text:
            paragraphs.append(text)
    sections = {name: [] for name in RESUME_SECTION_NAMES}
    current_section = "个人简介"
    for paragraph in paragraphs:
        if paragraph in sections:
            current_section = paragraph
        else:
            sections[current_section].append(paragraph)
    return {"status": "ready", "filename": files[0].name, "paragraphs": paragraphs, "sections": sections}


@app.get("/api/market/keyword-frequency")
def market_keyword_frequency() -> dict[str, object]:
    return get_keyword_frequencies(DB_PATH)


@app.get("/api/market/role-profiles")
def market_role_profiles() -> dict[str, object]:
    return get_role_profiles(DB_PATH)


class BatchCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_keys: list[str] = Field(min_length=1, max_length=5)
    directions: list[str] = Field(min_length=1, max_length=3)
    per_source_limit: StrictInt = Field(default=30, ge=1, le=100)
    staging_limit: StrictInt = Field(default=10, ge=1, le=20)
    include_uncertain: StrictBool = False


class CollectionScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_minutes: StrictInt
    options: BatchCollectionRequest


@app.get("/api/collector/schedule")
def collector_schedule_state():
    try:
        return COLLECTION_SCHEDULER.state()
    except (OSError, ValueError, TypeError) as error:
        raise HTTPException(status_code=503, detail="定时配置无法读取，原文件未覆盖；请先检查本地配置") from error


@app.put("/api/collector/schedule")
def configure_collector_schedule(payload: CollectionScheduleRequest):
    try:
        return COLLECTION_SCHEDULER.configure(payload.interval_minutes, payload.options.model_dump())
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=503, detail="无法保存定时配置，本次更改没有生效") from error


@app.post("/api/collector/schedule/pause")
def pause_collector_schedule():
    try:
        return COLLECTION_SCHEDULER.pause()
    except (OSError, ValueError, TypeError) as error:
        raise HTTPException(status_code=503, detail="暂停状态保存失败；如需立即停用，请关闭本项目后端") from error


@app.get("/api/collector/batch")
def collector_batch_state():
    try:
        return BATCH_COLLECTOR.state()
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=500, detail="读取采集任务记录失败，原文件未被覆盖") from error


@app.get("/api/collector/batch/runs/{run_id}")
def collector_batch_run(run_id: str):
    try:
        return BATCH_COLLECTOR.get_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="采集任务不存在") from error


@app.post("/api/collector/batch/runs", status_code=202)
def start_collector_batch(payload: BatchCollectionRequest, background_tasks: BackgroundTasks):
    try:
        profile = load_candidate_fit_profile(CANDIDATE_FIT_PROFILE_PATH)
        fingerprints = read_formal_fingerprints(DB_PATH)
        run = BATCH_COLLECTOR.create(payload.model_dump(), profile)
    except BatchBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise HTTPException(status_code=503, detail="无法读取本地资料或保存任务，本次没有开始采集") from error
    background_tasks.add_task(BATCH_COLLECTOR.execute, run["id"], profile, fingerprints)
    return run


@app.get("/api/collector/staging")
def collector_staging() -> dict[str, object]:
    """Preview isolated collector records without importing them."""
    try:
        items = [
            item
            for item in read_staging(data_directory=DATA_DIR)
            if item.get("review_status") == "pending"
        ]
    except StagingReadError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    evaluated_items = evaluate_staging_items(DB_PATH, items)
    return {
        "status": "ready",
        "count": len(evaluated_items),
        "items": evaluated_items,
    }


@app.post("/api/collector/moka/deeproute/discover")
def discover_deeproute_moka_jobs() -> dict[str, object]:
    """Preview likely relevant open jobs without staging any of them."""

    try:
        total, raw_jobs = fetch_public_job_list(
            organization_id="deeproute",
            limit=100,
        )
        staged_ids = {
            str(item.get("source_job_id"))
            for item in read_staging(data_directory=DATA_DIR)
            if item.get("source_id") == "moka_recruitment_api"
            and item.get("source_job_id")
        }
        candidate_profile = load_candidate_fit_profile(
            CANDIDATE_FIT_PROFILE_PATH
        )
    except (MokaRequestError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except StagingReadError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    candidates = rank_moka_candidates(
        raw_jobs,
        read_reference_jobs(DB_PATH),
        staged_job_ids=staged_ids,
        candidate_profile=candidate_profile,
    )
    return {
        "status": "preview_only",
        "organization": "深圳元戎启行科技有限公司",
        "open_job_count": total,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "note": "这里只展示候选岗位，不会自动写入待确认区。",
    }


@app.get("/api/collector/moka/deeproute/jobs/{posting_id}")
def preview_deeproute_moka_job(posting_id: str) -> dict[str, object]:
    """Read one full public JD for preview without staging it."""

    try:
        job = fetch_public_job(
            organization_id="deeproute",
            posting_id=posting_id,
        )
    except (MokaRequestError, ValueError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {
        "status": "preview_only",
        "item": {
            "title": job.title,
            "company": job.company,
            "description": job.description,
            "source_url": job.source_url,
            "source_job_id": job.source_job_id,
            "published_at": job.published_at,
            "source_updated_at": job.source_updated_at,
            "city": job.city,
            "salary": job.salary,
        },
        "note": "完整 JD 仅供查看，尚未写入待确认区。",
    }


@app.post("/api/collector/moka/deeproute/jobs/{posting_id}/stage")
def stage_deeproute_moka_job(posting_id: str) -> dict[str, object]:
    """Add one explicitly selected public job to the review queue."""

    try:
        job = fetch_public_job(
            organization_id="deeproute",
            posting_id=posting_id,
        )
        summary = stage_unique_jobs([job], data_directory=DATA_DIR)
    except (MokaRequestError, ValueError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except StagingReadError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    if summary.added_count or summary.updated_count:
        status = "staged"
    else:
        status = "already_collected"
    return {
        "status": status,
        "title": job.title,
        "added_count": summary.added_count,
        "updated_count": summary.updated_count,
        "skipped_count": summary.skipped_count,
        "messages": list(summary.messages),
        "note": "岗位仅进入待确认区，尚未写入正式岗位库。",
    }


@app.post("/api/collector/staging/{content_hash}/import", response_model=None)
def import_collector_staging_job(
    content_hash: str,
) -> dict[str, object] | JSONResponse:
    items = [
        item
        for item in read_staging(data_directory=DATA_DIR)
        if item.get("content_hash") == content_hash
        and item.get("review_status") == "pending"
    ]
    if not items:
        raise HTTPException(status_code=404, detail="待确认采集记录不存在或已经处理。")
    item = evaluate_staging_items(DB_PATH, items)[0]
    if not item["relevance"]["allow_market_profile"]:
        return JSONResponse(
            status_code=409,
            content={
                "error": "relevance_not_confirmed",
                "message": "这条岗位不符合当前核心画像准入条件，不能直接导入。",
            },
        )

    result = save_csv_job_samples(
        DB_PATH,
        [
            {
                "title": str(item.get("title", "")),
                "description": str(item.get("description", "")),
                "source": str(item.get("source_id", "collector")),
                "company": str(item.get("company") or ""),
                "source_url": str(item.get("source_url") or ""),
                "published_at": str(item.get("published_at") or ""),
                "city": str(item.get("city") or ""),
                "salary": str(item.get("salary") or ""),
            }
        ],
    )
    saved_item = result["items"][0]
    decision = "imported" if saved_item["status"] == "saved" else "duplicate"
    resolve_staging_record(
        content_hash,
        decision=decision,
        details={
            "database_job_id": saved_item.get("id") or saved_item.get("duplicate_of"),
            "allow_market_profile": True,
        },
        data_directory=DATA_DIR,
    )
    return {"status": decision, "result": saved_item}


@app.post("/api/collector/staging/{content_hash}/discard")
def discard_collector_staging_job(content_hash: str) -> dict[str, object]:
    try:
        item = resolve_staging_record(
            content_hash,
            decision="discarded",
            details={"reason": "user_discarded"},
            data_directory=DATA_DIR,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"status": "discarded", "title": item.get("title")}


@app.get("/api/project-facts")
def list_project_facts() -> dict[str, object]:
    """Read local project fact cards only; cards are deliberately outside the repository."""
    return {"items": list_project_fact_cards(PROJECT_FACTS_DIR)}


@app.put("/api/project-facts/{project_id}")
async def update_project_fact(project_id: str, request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
        item = save_project_fact_card(PROJECT_FACTS_DIR, project_id, payload)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="项目事实卡不存在。") from error
    except (ProjectFactError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"status": "saved", "item": item}


@app.post("/api/project-facts/{project_id}/confirm")
def confirm_project_fact(project_id: str) -> dict[str, object]:
    try:
        item = confirm_project_fact_card(PROJECT_FACTS_DIR, project_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="项目事实卡不存在。") from error
    except ProjectFactError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"status": "confirmed", "item": item}


@app.get("/api/project-facts/{project_id}/candidate-descriptions")
def project_candidate_descriptions(project_id: str) -> dict[str, object]:
    return build_project_candidate_descriptions(PROJECT_FACTS_DIR, project_id)


@app.get("/api/jobs/{job_id}/agent-v1")
def run_agent_v1(job_id: int) -> dict[str, object]:
    return build_agent_v1(DB_PATH, PROJECT_FACTS_DIR, job_id, preview_latest_resume())


@app.get("/api/jobs/{job_id}/agent-v1/candidate-context", response_model=None)
def preview_deepseek_candidate_context(job_id: int) -> dict[str, object] | JSONResponse:
    try:
        return prepare_candidate_context(DB_PATH, PROJECT_FACTS_DIR, job_id)
    except CandidateError as error:
        return JSONResponse(status_code=error.status_code,
                            content={"status": "error", "code": error.code, "message": error.safe_message})


@app.post("/api/jobs/{job_id}/agent-v1/candidates", response_model=None)
def create_deepseek_candidates(job_id: int, request: CandidateGenerateRequest) -> dict[str, object] | JSONResponse:
    try:
        return generate_candidate_descriptions(
            DB_PATH, PROJECT_FACTS_DIR, job_id, request.context_hash, config_error=LOCAL_CONFIG_ERROR
        )
    except (CandidateError, DeepSeekError) as error:
        return JSONResponse(status_code=error.status_code,
                            content={"status": "error", "code": error.code, "message": error.safe_message})


@app.post("/api/jobs/{job_id}/agent-v1/candidates/apply", response_model=None)
def apply_deepseek_candidate(job_id: int, request: CandidateApplyRequest) -> dict[str, object] | JSONResponse:
    try:
        return apply_candidate_to_draft(
            DB_PATH, PROJECT_FACTS_DIR, job_id, request.preview_id,
            request.candidate_index, preview_latest_resume(),
        )
    except CandidateError as error:
        return JSONResponse(status_code=error.status_code,
                            content={"status": "error", "code": error.code, "message": error.safe_message})


@app.get("/api/jobs/{job_id}/market-comparison")
def compare_job_with_market(job_id: int) -> dict[str, object]:
    return compare_job_to_market(DB_PATH, job_id)


@app.get("/api/jobs/{job_id}/similar-samples")
def similar_job_samples(job_id: int, limit: int = 5) -> dict[str, object]:
    return find_similar_jobs(DB_PATH, job_id, limit)


@app.get("/api/jobs/{job_id}/fact-match")
def match_job_to_project_facts(job_id: int) -> dict[str, object]:
    return build_fact_match_table(DB_PATH, PROJECT_FACTS_DIR, job_id)


@app.get("/api/jobs")
def list_jobs() -> dict[str, object]:
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT jobs.id, jobs.title, jobs.description, length(jobs.description) AS description_length, jobs.source, jobs.created_at,
                   job_analyses.role_family, job_analyses.analysis_status AS classification_status,
                   COUNT(*) OVER (PARTITION BY title, description) AS duplicate_count
            FROM jobs
            LEFT JOIN job_analyses ON job_analyses.job_id = jobs.id AND job_analyses.is_current = 1
            ORDER BY jobs.id DESC
            """
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["suggested_family"] = suggest_role_family(item["title"], item.pop("description"))["family"]
        items.append(item)
    return {"items": items}

@app.post("/api/jobs/duplicate-check")
def check_job_duplicates(request: DuplicateCheckRequest) -> dict[str, object]:
    return {"status": "ready", "duplicates": find_job_duplicate_candidates(DB_PATH, [job.model_dump() for job in request.jobs])}


@app.post("/api/jobs/{job_id}/classification", response_model=None)
def confirm_job_classification(job_id: int, request: ClassificationConfirmRequest) -> dict[str, object] | JSONResponse:
    if request.role_family not in {"ai_tool_automation", "vibe_coding_fullstack", "agent_application", "ai_product_operations", "internal_intelligence", "indie_ai_developer"}:
        return JSONResponse(status_code=400, content={"message": "不是有效的岗位方向。"})
    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.execute("UPDATE job_analyses SET role_family = ?, analysis_status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE job_id = ? AND is_current = 1", (request.role_family, job_id))
        connection.commit()
    if cursor.rowcount == 0:
        return JSONResponse(status_code=404, content={"message": "岗位分析记录不存在。"})
    return {"status": "confirmed", "job_id": job_id, "role_family": request.role_family}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int) -> dict[str, object]:
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT id, title, description, source, created_at, company, source_url,
                   published_at, city, salary, content_hash, duplicate_of,
                   sample_status, updated_at
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
        analysis_row = connection.execute(
            """
            SELECT id, role_family, content_json, analysis_status, analyzer_version,
                   created_at, updated_at, confirmed_at
            FROM job_analyses
            WHERE job_id = ? AND is_current = 1
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        return {"error": "job_not_found"}

    job = dict(row)
    job["classification_suggestion"] = suggest_role_family(job["title"], job["description"])
    analysis = None
    if analysis_row is not None:
        analysis = dict(analysis_row)
        analysis["content"] = json.loads(analysis.pop("content_json"))

    job["sample_card"] = {
        "raw": {
            "id": job["id"],
            "title_raw": job["title"],
            "company_raw": job["company"],
            "description_raw": job["description"],
            "source": job["source"],
            "source_url": job["source_url"],
            "published_at": job["published_at"],
            "collected_at": job["created_at"],
            "city_raw": job["city"],
            "salary_raw": job["salary"],
            "content_hash": job["content_hash"],
            "duplicate_of": job["duplicate_of"],
            "sample_status": job["sample_status"],
            "updated_at": job["updated_at"],
        },
        "analysis": analysis,
    }
    return job


@app.get("/api/jobs/{job_id}/draft")
def get_resume_draft(job_id: int) -> dict[str, object]:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            "SELECT content_json, updated_at FROM resume_drafts WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        return {"status": "empty", "job_id": job_id}
    draft = json.loads(row[0])
    if draft.get("source") not in {"agent-v1-confirmed-facts", "agent-v1-deepseek-confirmed"}:
        return {"status": "legacy", "job_id": job_id, "message": "旧版草稿未使用已确认事实，请重新生成。", "updated_at": row[1]}
    return {"status": "ready", "job_id": job_id, "draft": draft, "updated_at": row[1]}


@app.post("/api/jobs/{job_id}/draft")
def save_resume_draft(job_id: int, request: ResumeDraftRequest) -> dict[str, object]:
    draft = {
        "jobTitle": request.job_title,
        "sections": request.sections,
        "changes": request.changes,
        "source": request.source,
    }
    with sqlite3.connect(DB_PATH) as connection:
        job_exists = connection.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job_exists is None:
            return {"status": "error", "message": "岗位不存在"}
        connection.execute(
            """
            INSERT INTO resume_drafts (job_id, content_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(job_id) DO UPDATE SET
                content_json = excluded.content_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (job_id, json.dumps(draft, ensure_ascii=False)),
        )
        connection.commit()
        updated_at = connection.execute(
            "SELECT updated_at FROM resume_drafts WHERE job_id = ?",
            (job_id,),
        ).fetchone()[0]
    return {"status": "saved", "job_id": job_id, "draft": draft, "updated_at": updated_at}


@app.get("/api/jobs/{job_id}/draft.docx")
def export_resume_draft(job_id: int) -> Response:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            """
            SELECT jobs.title, resume_drafts.content_json
            FROM resume_drafts
            JOIN jobs ON jobs.id = resume_drafts.job_id
            WHERE resume_drafts.job_id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"status": "empty", "message": "请先生成并保存该岗位的简历草稿"},
        )

    draft = json.loads(row[1])
    content = build_resume_docx(row[0], draft)
    safe_title = re.sub(r'[\\/:*?"<>|]+', "-", row[0]).strip(" .") or f"job-{job_id}"
    filename = f"简历-{safe_title}.docx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=resume-job-{job_id}.docx; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/jobs/{job_id}/draft.pdf")
def export_resume_draft_pdf(job_id: int) -> Response:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            """
            SELECT jobs.title, resume_drafts.content_json
            FROM resume_drafts
            JOIN jobs ON jobs.id = resume_drafts.job_id
            WHERE resume_drafts.job_id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"status": "empty", "message": "请先生成并保存该岗位的简历草稿"},
        )

    draft = json.loads(row[1])
    content = build_resume_pdf(row[0], draft)
    safe_title = re.sub(r'[\\/:*?"<>|]+', "-", row[0]).strip(" .") or f"job-{job_id}"
    filename = f"简历-{safe_title}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=resume-job-{job_id}.pdf; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/jobs/{job_id}/keywords")
def extract_job_keywords(job_id: int) -> dict[str, object]:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            "SELECT title, description FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        return {"error": "job_not_found", "keywords": []}

    description = row[1].lower()
    keywords = [keyword for keyword in KEYWORD_CATALOG if keyword.lower() in description]
    categories = {
        category: [keyword for keyword in keywords if keyword in category_keywords]
        for category, category_keywords in KEYWORD_CATEGORIES.items()
    }
    return {"job_id": job_id, "title": row[0], "keywords": keywords, "categories": categories}


@app.get("/api/jobs/{job_id}/highlights")
def identify_job_highlights(job_id: int) -> dict[str, object]:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            "SELECT title, description FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        return {"error": "job_not_found", "sections": {}}

    description = row[1].lower()
    sections = {
        section: [keyword for keyword in keywords if keyword.lower() in description]
        for section, keywords in HIGHLIGHT_KEYWORDS.items()
    }
    return {"job_id": job_id, "title": row[0], "sections": sections}


@app.get("/api/jobs/{job_id}/keyword-match")
def match_job_keywords(job_id: int) -> dict[str, object]:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            "SELECT title, description FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        return {"status": "error", "message": "岗位不存在"}

    resume = preview_latest_resume()
    if resume.get("status") != "ready":
        return {"status": "no_resume", "matched": [], "missing": [], "coverage": 0}

    resume_text = normalize(" ".join(resume["paragraphs"]))
    requirements = [x for x in extract_requirements(row[1], collapse_alternatives=True)
                    if x["category"] != "学历与经验" and x["kind"] != "加分项"]
    # Text coverage is intentionally separate from the evidence-checked project score.
    unique = {x["requirement"]: x for x in requirements}
    matched = [name for name, item in unique.items() if requirement_match_count(item, [resume_text]) >= item.get("minimum_options", 1)]
    missing = [name for name in unique if name not in matched]
    return {
        "status": "ready", "job_id": job_id, "matched": matched, "missing": missing,
        "coverage": round(100 * len(matched) / len(unique)) if unique else None,
        "note": "简历文字覆盖率，不代表能力已验证；加分项和学历条件不计入。真实性请看岗位级事实分析。",
    }


@app.get("/api/jobs/{job_id}/core-match")
def match_core_requirements(job_id: int) -> dict[str, object]:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            "SELECT title, description FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        return {"status": "error", "message": "岗位不存在", "items": []}

    resume = preview_latest_resume()
    if resume.get("status") != "ready":
        return {"status": "no_resume", "items": []}

    result = build_fact_match_table(DB_PATH, PROJECT_FACTS_DIR, job_id)
    items = []
    for item in result["items"]:
        if item["kind"] == "加分项" or item["category"] == "学历与经验":
            continue
        verified = [fact for fact in item["matched_facts"] if fact["allowed_in_resume"]] if item["allowed_in_resume"] else []
        items.append({
            "requirement": item["requirement"], "matched": bool(verified),
            "projects": list(dict.fromkeys(fact["project_name"] for fact in verified)),
            "evidence": [f"JD 原文：{item['jd_evidence']}"] +
                        ([fact["fact"] for fact in verified[:2]] or [item["gap"]]),
        })
    return {"status": "ready", "job_id": job_id, "items": items}


@app.get("/api/jobs/{job_id}/recommendations")
def recommend_resume_adjustments(job_id: int) -> dict[str, object]:
    core_result = match_core_requirements(job_id)
    keyword_result = match_job_keywords(job_id)
    if core_result.get("status") == "no_resume" or keyword_result.get("status") == "no_resume":
        return {"status": "no_resume", "items": []}
    if core_result.get("status") != "ready" or keyword_result.get("status") != "ready":
        return {"status": "error", "items": []}

    items: list[dict[str, str]] = []
    core_items = core_result["items"]
    missing_core = [item for item in core_items if not item["matched"]]
    matched_core = [item for item in core_items if item["matched"]]
    missing_keywords = keyword_result["missing"]

    if matched_core:
        project_names = sorted({project for item in matched_core for project in item["projects"]})
        items.append({
            "type": "突出",
            "title": "把已有匹配项目提前",
            "content": f"优先展示与核心要求相关的项目：{'、'.join(project_names)}。" if project_names else "优先展示已经出现核心要求证据的项目。",
            "reason": "这些经历已经能证明岗位关注的能力，放在前面更容易被快速看见。",
        })
    if missing_core:
        items.append({
            "type": "补充",
            "title": "核实未匹配的核心要求",
            "content": "请确认是否有真实经历可以补充：" + "、".join(item["requirement"] for item in missing_core) + "。",
            "reason": "当前简历没有找到直接证据，只建议补充真实经历，不建议直接写成已掌握。",
        })
    if missing_keywords:
        items.append({
            "type": "补充",
            "title": "自然补充岗位关键词",
            "content": "如果项目确实涉及，可在项目描述或技术栈中补充：" + "、".join(missing_keywords[:8]) + "。",
            "reason": "这些词出现在 JD 中，但当前简历未覆盖，补充真实上下文有助于提高检索命中。",
        })
    items.append({
        "type": "谨慎",
        "title": "保留可验证的项目细节",
        "content": "为每个重点项目补充真实的输入、输出、调试或验证过程；暂不填写没有依据的指标。",
        "reason": "Vibe Coding 岗位通常会追问开发闭环，具体过程比泛泛而谈更可信。",
    })
    return {"status": "ready", "job_id": job_id, "items": items}


@app.post("/api/jobs/batch-preview", response_model=None)
def preview_batch_jobs(request: BatchJobPreviewRequest) -> dict[str, object] | JSONResponse:
    try:
        preview = build_batch_preview(request.text)
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_batch_format", "message": str(error)},
        )
    return {"status": "ready", **preview, "duplicates": find_job_duplicate_candidates(DB_PATH, jobs=split_batch_jds(request.text))}


@app.post("/api/jobs/batch", response_model=None)
def save_batch_jobs(request: BatchJobPreviewRequest) -> dict[str, object] | JSONResponse:
    try:
        jobs = split_batch_jds(request.text)
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_batch_format", "message": str(error)},
        )
    if request.positions is not None:
        selected_positions = set(request.positions)
        jobs = [job for position, job in enumerate(jobs, start=1) if position in selected_positions]
    if not jobs:
        return JSONResponse(status_code=400, content={"error": "no_selected_jobs", "message": "请至少保留一条岗位。"})
    result = save_batch_job_samples(DB_PATH, jobs)
    return {"status": "saved", **result}


@app.post("/api/jobs/csv", response_model=None)
def save_csv_jobs(request: CsvJobSaveRequest) -> dict[str, object] | JSONResponse:
    jobs = [job.model_dump() for job in request.jobs if job.title.strip() and job.description.strip()]
    if not jobs:
        return JSONResponse(status_code=400, content={"error": "invalid_csv_rows", "message": "没有可保存的 CSV 岗位，请检查岗位名称和 JD 列。"})
    result = save_csv_job_samples(DB_PATH, jobs)
    return {"status": "saved", **result}


@app.post("/api/jobs/preview")
def preview_job(request: JobPreviewRequest) -> dict[str, object]:
    title = request.title.strip() or "未命名岗位"
    description = request.description.strip()
    with sqlite3.connect(DB_PATH) as connection:
        existing = connection.execute(
            "SELECT id FROM jobs WHERE title = ? AND description = ? ORDER BY id LIMIT 1",
            (title, description),
        ).fetchone()
        if existing:
            return {
                "status": "exists",
                "id": existing[0],
                "title": title,
                "description_length": len(description),
            }

        cursor = connection.execute(
            "INSERT INTO jobs (title, description, source) VALUES (?, ?, ?)",
            (title, description, "manual"),
        )
        connection.commit()
        job_id = cursor.lastrowid

    return {
        "status": "saved",
        "id": job_id,
        "title": title,
        "description_length": len(description),
    }
