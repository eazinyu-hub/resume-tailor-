import argparse

from .moka_client import fetch_public_job
from .staging import stage_unique_jobs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch one reviewed public Moka posting into staging."
    )
    parser.add_argument("--organization", required=True)
    parser.add_argument("--job-id", required=True)
    arguments = parser.parse_args()

    job = fetch_public_job(
        organization_id=arguments.organization,
        posting_id=arguments.job_id,
    )
    result = stage_unique_jobs([job])
    for message in result.messages:
        print(message)
    print(f"暂存文件：{result.path}")


if __name__ == "__main__":
    main()
