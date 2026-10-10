"""Validate previously accepted synthetic outputs and prepare a local recording replay."""

import argparse
import json
import sqlite3
import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    target = args.data_dir.resolve()
    database = target / "runtime" / "app.sqlite3"
    fixture = json.loads((ROOT / "backend/tests/fixtures/deepseek_agent_demo_cases.json").read_text(encoding="utf-8"))
    saved = json.loads((ROOT / "examples/deepseek-live-demo-results.json").read_text(encoding="utf-8"))
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT id,title,description,source FROM jobs ORDER BY id").fetchall()
    expected = fixture["cases"]
    if len(rows) != len(expected) or any(
        row[1:] != (case["title"], case["jd"], "synthetic-demo") for row, case in zip(rows, expected)
    ):
        raise SystemExit("Replay accepts only the exact two synthetic demo jobs; no personal database was changed.")
    sys.path.insert(0, str(ROOT / "backend"))
    from app.deepseek_candidates import generate_candidate_descriptions, prepare_candidate_context

    entries = []
    for row, case, result in zip(rows, expected, saved["cases"]):
        if result["id"] != case["id"]:
            raise SystemExit("Saved replay case order does not match the fixture.")
        preview = prepare_candidate_context(database, target / "project-facts", row[0])

        def replay_completion(_messages, _config_error, record=result):
            return deepcopy({key: record[key] for key in ("candidates", "gaps", "risks")}), {
                "provider": "DeepSeek", "model": record["model"], "usage": record["usage"],
            }

        candidate = generate_candidate_descriptions(
            database, target / "project-facts", row[0], preview["context_hash"], complete=replay_completion,
        )
        candidate["note"] = "2026-09-24 已验收模型输出回放；本次没有调用 API。" + candidate["note"]
        entries.append({"id": case["id"], "job_id": row[0], "title": row[1], "result": candidate})
    manifest = target / "replay-manifest.json"
    manifest.write_text(json.dumps({"replay": True, "cases": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Validated synthetic replay prepared: {manifest}")
    print("No API call was made; only candidate previews were created, no draft was applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
