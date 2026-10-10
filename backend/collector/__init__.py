"""Isolated job collection primitives.

This package does not run as part of the FastAPI application and does not
perform network requests in stage 7.2.
"""

from .models import CollectedJob
from .policy import SourcePolicy, get_source_policy
from .staging import append_to_staging, read_staging, resolve_staging_record

__all__ = [
    "CollectedJob",
    "SourcePolicy",
    "append_to_staging",
    "get_source_policy",
    "read_staging",
    "resolve_staging_record",
]
