import argparse

from .lever_client import fetch_public_posting
from .staging import stage_unique_jobs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch one reviewed public Lever posting into staging."
    )
    parser.add_argument("--site", required=True)
    parser.add_argument("--posting-id", required=True)
    arguments = parser.parse_args()

    job = fetch_public_posting(
        site_id=arguments.site,
        posting_id=arguments.posting_id,
    )
    result = stage_unique_jobs([job])
    for message in result.messages:
        print(message)
    print(f"暂存文件：{result.path}")


if __name__ == "__main__":
    main()
