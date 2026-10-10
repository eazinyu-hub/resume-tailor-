"""Create an isolated, synthetic DATA_DIR for screenshots and demonstrations."""

import argparse
import json
import os
import sqlite3
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FIXTURE = BACKEND / "tests" / "fixtures" / "deepseek_agent_demo_cases.json"
DEFAULT_TARGET = ROOT / "work" / "public-demo-data"


def write_demo_resume(path: Path) -> None:
    paragraphs = [
        "个人简介", "脱敏候选人", "求职方向：Vibe Coding", "邮箱：example@example.com",
        "教育背景", "示例大学｜示例专业",
        "工作经历", "示例公司｜示例职位",
        "项目经历", "AI 简历适配工作台｜个人项目",
        "技术与工具", "React、FastAPI、SQLite、Codex",
    ]
    body = "".join(
        f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    target = args.target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty demo directory: {target}")

    suite = json.loads(FIXTURE.read_text(encoding="utf-8"))
    os.environ["DATA_DIR"] = str(target)
    sys.path.insert(0, str(BACKEND))
    from app import main as application

    facts_dir = target / "project-facts"
    facts_dir.mkdir(parents=True, exist_ok=True)
    template = json.loads((ROOT / "examples" / "project-fact-template.json").read_text(encoding="utf-8"))
    template.update(suite["project"])
    template["completion"] = {
        "status": "脱敏演示案例",
        "last_verified_at": "2026-09-24",
        **suite["project"].get("completion", {}),
    }
    (facts_dir / "project-resume-tailor.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_demo_resume(target / "resumes" / "demo-resume.docx")
    with sqlite3.connect(application.DB_PATH) as connection:
        for case in suite["cases"]:
            connection.execute(
                "INSERT INTO jobs(title, description, source) VALUES (?, ?, ?)",
                (case["title"], case["jd"], "synthetic-demo"),
            )
        connection.commit()

    print(f"Demo DATA_DIR created: {target}")
    print("Contains only synthetic jobs, project facts and resume data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
