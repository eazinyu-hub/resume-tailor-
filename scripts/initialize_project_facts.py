"""Create an editable, unconfirmed fact card without overwriting personal data."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    target = args.data_dir.resolve() / "project-facts" / "project-resume-tailor.json"
    template = json.loads((ROOT / "examples" / "project-fact-template.json").read_text(encoding="utf-8"))
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as handle:
            json.dump(template, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError:
        print("Fact card already exists; kept the existing file unchanged.")
        return 0
    print(f"Created unconfirmed fact card: {target}")
    print("Edit it in the project facts page, then confirm only your actual experience.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
