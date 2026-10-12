from __future__ import annotations

import os
import time
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

_uuid7_lock = __import__("threading").Lock()
_uuid7_last_ts = 0
_uuid7_seq = 0


def _uuid7() -> UUID:
    """Generate a UUIDv7 (time-ordered, RFC 9562).

    Falls back to a pure-Python implementation for Python < 3.14.
    """
    global _uuid7_last_ts, _uuid7_seq

    try:
        from uuid import uuid7  # type: ignore[attr-defined]

        return uuid7()
    except ImportError:
        pass

    ms = time.time_ns() // 1_000_000

    with _uuid7_lock:
        if ms <= _uuid7_last_ts:
            _uuid7_seq += 1
        else:
            _uuid7_seq = 0
        _uuid7_last_ts = ms
        seq = _uuid7_seq

    ts_hi = (ms >> 16) & 0xFFFFFFFF
    ts_lo = ms & 0xFFFF
    rand_a = seq & 0x0FFF
    rand_b = os.urandom(8)

    b = ts_hi.to_bytes(4, "big")
    b += ts_lo.to_bytes(2, "big")
    b += (0x7000 | rand_a).to_bytes(2, "big")
    b += bytes([(rand_b[0] & 0x3F) | 0x80]) + rand_b[1:]

    return UUID(bytes=b)


class IngestionStatus(StrEnum):
    """Processing state of a captured listing."""

    raw = "raw"
    extracting = "extracting"
    extracted = "extracted"
    failed = "failed"
    quarantined = "quarantined"


class RawCapture(BaseModel):
    """A captured listing as received from a source.

    This is the pipeline's ONLY input boundary. Every scraper's output
    maps into this canonical shape before any processing occurs.
    """

    id: UUID = Field(default_factory=_uuid7)
    source: str
    source_listing_id: str
    url: str
    fetched_at: datetime
    checksum: str = Field(description="SHA-256 of the raw payload")
    raw_payload: str
    payload_format: str = Field(
        pattern=r"^(html|json|xml|atom)$",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: IngestionStatus = Field(default=IngestionStatus.raw)

    model_config = {"frozen": False}
