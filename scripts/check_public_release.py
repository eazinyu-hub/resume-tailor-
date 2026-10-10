"""Fail when public candidate files contain common secret or private-data markers."""

import argparse
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", ".md", ".txt", ".css", ".html", ".toml", ".yaml", ".yml"}
FORBIDDEN_FILES = {".env", ".docx", ".pdf", ".sqlite3", ".db"}
PATTERNS = {
    "DeepSeek/OpenAI-style key": re.compile(r"\b(?:sk|ds)-[A-Za-z0-9_-]{16,}\b"),
    "local Windows user path": re.compile(r"C:[/\\]Users[/\\](?!example(?:[/\\]|$))", re.IGNORECASE),
    "WeChat private path or id": re.compile(r"(?:xwechat_files|wxid_)", re.IGNORECASE),
    "private API assignment": re.compile(r"^[ \t]*(?:export[ \t]+)?DEEPSEEK_API_KEY[ \t]*=[ \t]*(?!$|your_key_here\b|file-key\b)(\S+)", re.IGNORECASE | re.MULTILINE),
}


def git_command() -> list[str]:
    command = ["git", "-c", "core.quotepath=false"]
    if (ROOT / "work" / "git-meta").exists():
        command.extend([
            f"--git-dir={ROOT / 'work' / 'git-meta'}",
            f"--work-tree={ROOT}",
        ])
    return command


def git_output(*arguments: str) -> bytes:
    return subprocess.run([*git_command(), *arguments], cwd=ROOT, check=True, capture_output=True).stdout


def inspect_content(relative: str, content: bytes, issues: list[str]) -> None:
    path = Path(relative)
    if path.name == ".env" or path.suffix.lower() in FORBIDDEN_FILES:
        issues.append(f"forbidden tracked artifact: {relative}")
        return
    if relative == "scripts/check_public_release.py":
        return
    if path.suffix.lower() not in TEXT_SUFFIXES and not path.name.endswith(".env.example"):
        return
    text = content.decode("utf-8", errors="replace")
    for label, pattern in PATTERNS.items():
        if pattern.search(text):
            issues.append(f"{label}: {relative}")


def inspect_history(issues: list[str]) -> int:
    seen = set()
    for line in git_output("rev-list", "--objects", "--all").decode("utf-8").splitlines():
        oid, separator, relative = line.partition(" ")
        if not separator or oid in seen:
            continue
        path = Path(relative)
        if path.suffix.lower() not in TEXT_SUFFIXES | FORBIDDEN_FILES and path.name not in {".env", ".env.example"}:
            continue
        if git_output("cat-file", "-t", oid).strip() != b"blob":
            continue
        seen.add(oid)
        inspect_content(relative, git_output("cat-file", "blob", oid), issues)
    return len(seen)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Scan the exact Git index blobs, not the working copy.")
    parser.add_argument("--history", action="store_true", help="Also scan text blobs reachable from local Git refs.")
    args = parser.parse_args()
    issues = []
    arguments = ("ls-files", "-z", "--cached") if args.staged else ("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    candidates = git_output(*arguments).decode("utf-8").split("\0")
    count = 0
    for relative in dict.fromkeys(item for item in candidates if item):
        path = ROOT / relative
        if not args.staged and not path.is_file():
            continue
        inspect_content(relative, git_output("show", f":{relative}") if args.staged else path.read_bytes(), issues)
        count += 1
    history_count = inspect_history(issues) if args.history else 0
    if issues:
        print("Public release scan failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print(f"Public release scan passed: {count} files, {history_count} historical text blobs; no common secret or private-data markers found.")
    print("Pattern scanning does not replace review of personal text, screenshots or videos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
