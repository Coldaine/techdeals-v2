"""End-to-end orchestration: fixtures -> raw_captures -> extraction -> postings.

This closes the loop the scaffold left open. Two extraction providers:

- ``llm``     — the real batched engine (`parser.engine.extract_batches`). Requires
                an endpoint + key; records model/prompt/cost per batch (AC6).
- ``offline`` — replays the recorded responses in `fixtures/expected/extractions.json`
                through the *same* persistence path. Zero LLM calls, fully
                deterministic; used to verify the plumbing, SQL and acceptance
                queries without credentials.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import psycopg

from techdeals.db.persistence import (
    insert_capture,
    persist_result,
    posting_exists,
    record_batch,
)
from techdeals.ingestion.contract import RawCapture
from techdeals.parser.models import ExtractionResult

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
CASSETTE_PATH = REPO_ROOT / "fixtures" / "expected" / "extractions.json"


@dataclass
class IngestSummary:
    captures_written: int
    captures_in_db: int


@dataclass
class ExtractSummary:
    listings: int = 0
    postings: int = 0
    quarantined: int = 0
    skipped_replay: int = 0
    batches: int = 0
    single_listing_calls: int = 0


def load_cassette(path: Path | None = None) -> dict[str, ExtractionResult]:
    path = path or CASSETTE_PATH
    data = json.loads(path.read_text())
    out: dict[str, ExtractionResult] = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        out[key] = ExtractionResult.model_validate(value)
    return out


def cassette_key(capture: RawCapture) -> str:
    return f"{capture.source}:{capture.source_listing_id}"


def ingest(conn: psycopg.Connection, captures: list[RawCapture]) -> IngestSummary:
    """Persist captures into `raw_captures` (idempotent on checksum)."""
    for capture in captures:
        insert_capture(conn, capture)
    conn.commit()
    total = conn.execute("SELECT count(*) FROM raw_captures").fetchone()[0]
    return IngestSummary(captures_written=len(captures), captures_in_db=total)


async def extract(
    conn: psycopg.Connection,
    captures: list[RawCapture],
    *,
    parser_version: str = "v1",
    batch_size: int = 20,
    provider: str = "llm",
    model: str | None = None,
    prompt_version: str = "v1",
    max_concurrent: int = 5,
) -> ExtractSummary:
    """Extract a set of captures and persist the results.

    Batched by construction: listings are grouped `batch_size` per LLM call, and
    one row per call lands in `extraction_batches` (AC6).
    """
    summary = ExtractSummary()

    pairs: list[tuple[RawCapture, object]] = [
        (capture, insert_capture(conn, capture)) for capture in captures
    ]
    conn.commit()

    pending: list[tuple[RawCapture, object]] = []
    seen_capture_ids: set = set()
    for capture, capture_id in pairs:
        if capture_id in seen_capture_ids:
            continue
        seen_capture_ids.add(capture_id)
        if posting_exists(conn, capture_id, parser_version):
            summary.skipped_replay += 1
            continue
        pending.append((capture, capture_id))

    summary.listings = len(pending)
    if not pending:
        return summary

    results: dict[int, ExtractionResult] = {}

    if provider == "offline":
        cassette = load_cassette()
        for start in range(0, len(pending), batch_size):
            chunk = pending[start : start + batch_size]
            for offset, (capture, _) in enumerate(chunk):
                results[start + offset] = cassette.get(
                    cassette_key(capture),
                    ExtractionResult(
                        notes="no recorded extraction for capture",
                        quarantine_reason="parse_failed",
                    ),
                )
            record_batch(
                conn,
                batch_key=f"offline_{start // batch_size}",
                model="recorded",
                prompt_version=prompt_version,
                listing_count=len(chunk),
                provider="offline",
            )
            summary.batches += 1
            if len(chunk) == 1:
                summary.single_listing_calls += 1
    else:
        from techdeals.parser.engine import extract_batches
        from techdeals.parser.prepare import capture_to_listing

        listings = [capture_to_listing(capture) for capture, _ in pending]
        responses = await extract_batches(
            listings,
            batch_size=batch_size,
            model=model,
            prompt_version=prompt_version,
            max_concurrent=max_concurrent,
        )
        index = 0
        for response in responses:
            record_batch(
                conn,
                batch_key=response.batch_id,
                model=response.model,
                prompt_version=response.prompt_version,
                listing_count=len(response.results),
                provider="llm",
                tokens_used=response.tokens_used,
                cost_cents=response.cost_cents,
            )
            summary.batches += 1
            if len(response.results) == 1:
                summary.single_listing_calls += 1
            for result in response.results:
                if index < len(pending):
                    results[index] = result
                index += 1

    for index, (capture, capture_id) in enumerate(pending):
        result = results.get(index)
        if result is None:
            continue
        posting_id = persist_result(
            conn,
            capture=capture,
            capture_id=capture_id,  # type: ignore[arg-type]
            result=result,
            parser_version=parser_version,
        )
        if posting_id is None:
            summary.skipped_replay += 1
            continue
        summary.postings += 1
        if result.quarantine_reason:
            summary.quarantined += 1

    conn.commit()
    return summary
