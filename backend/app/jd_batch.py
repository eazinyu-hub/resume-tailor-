import re


JOB_MARKER_PATTERN = re.compile(
    r"^\s*岗位(?P<index>[一二三四五六七八九十百\d]+)"
    r"\s*[、，,:：.．-]?\s*(?P<title>\S.*?)\s*$"
)


def split_batch_jds(text: str) -> list[dict[str, str]]:
    """Split explicitly numbered Chinese JD blocks without changing their bodies."""
    if not text.strip():
        return []

    lines = text.splitlines()
    markers: list[tuple[int, str]] = []
    for line_number, line in enumerate(lines):
        match = JOB_MARKER_PATTERN.fullmatch(line)
        if match:
            markers.append((line_number, match.group("title").strip()))

    if not markers:
        raise ValueError("未识别到“岗位一，岗位名称”格式的岗位标题")
    if any(line.strip() for line in lines[: markers[0][0]]):
        raise ValueError("第一条岗位标题前存在无法归属的文本")

    jobs: list[dict[str, str]] = []
    for marker_index, (line_number, title) in enumerate(markers):
        next_line_number = (
            markers[marker_index + 1][0]
            if marker_index + 1 < len(markers)
            else len(lines)
        )
        description = "\n".join(lines[line_number + 1 : next_line_number]).strip()
        if not description:
            raise ValueError(f"岗位“{title}”缺少 JD 正文")
        jobs.append({"title": title, "description": description})

    return jobs


def build_batch_preview(text: str) -> dict[str, object]:
    """Build a save-free summary so users can verify a batch split first."""
    jobs = split_batch_jds(text)
    return {
        "count": len(jobs),
        "items": [
            {
                "position": position,
                "title": job["title"],
                "description_length": len(job["description"]),
            }
            for position, job in enumerate(jobs, start=1)
        ],
    }
