from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class FailureMode(StrEnum):
    """Known failure modes during ingestion."""

    missed_url = "missed_url"
    partial_parse = "partial_parse"
    price_ambiguous = "price_ambiguous"
    out_of_scope = "out_of_scope"
    quarantine = "quarantine"
    parse_failed = "parse_failed"


class FailureRecord(BaseModel):
    """Record of a capture that failed processing."""

    capture_id: UUID
    failure_mode: FailureMode
    details: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
