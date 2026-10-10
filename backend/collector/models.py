import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


STAGING_SCHEMA_VERSION = 2


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def calculate_content_hash(
    title: str,
    company: str | None,
    description: str,
) -> str:
    content = "\n".join(
        (
            _normalized_text(title),
            _normalized_text(company or ""),
            _normalized_text(description),
        )
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CollectedJob:
    """One normalized job waiting for human review."""

    title: str
    description: str
    source_id: str
    company: str | None = None
    source_url: str | None = None
    source_job_id: str | None = None
    published_at: str | None = None
    source_updated_at: str | None = None
    city: str | None = None
    salary: str | None = None
    collected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def content_hash(self) -> str:
        return calculate_content_hash(
            self.title,
            self.company,
            self.description,
        )

    def to_staging_record(self) -> dict[str, Any]:
        record = asdict(self)
        record.update(
            {
                "schema_version": STAGING_SCHEMA_VERSION,
                "content_hash": self.content_hash,
                "review_status": "pending",
            }
        )
        return record
