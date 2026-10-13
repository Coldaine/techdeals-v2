"""Persistence: extraction results (and raw captures) -> Postgres.

This is the layer the scaffold was missing entirely. `engine.extract_batch()`
returned Pydantic objects and stopped: nothing wrote a `postings`/`lines` row, so
all four acceptance views returned empty by construction.

Design rules enforced here (BRIEF §6 guardrails):
- **No silent allocation**: a lot total is never divided into unit prices. A line
  only gets a price when the extraction said so, and it always reaches the DB
  through a `sale_groups` row carrying an explicit `price_basis`.
- **Unresolved is visible**: a posting is written with status `extracted` (or
  `quarantined`/`failed`) regardless of whether any resolution exists, so read
  views see it immediately.
- **Replay safety**: `postings` is unique on `(capture_id, parser_version)`. Re-running
  the same parser is a no-op; a new parser version adds a new posting and never
  mutates history.
- **Categories are data**: a category not already in `categories` is inserted, not
  migrated into DDL.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from techdeals.ingestion.contract import RawCapture
from techdeals.parser.models import (
    ExtractionResult,
    compute_offer_key,
)

# How a free-text quarantine reason maps onto the schema's CHECK-constrained
# failure_mode. Wanted-posts and consumer items are out-of-scope, not parse errors.
_FAILURE_MODE_MAP = {
    "wanted_post": "out_of_scope",
    "wanted": "out_of_scope",
    "out_of_scope": "out_of_scope",
    "out_of_scope_consumer": "out_of_scope",
    "consumer": "out_of_scope",
    "price_ambiguous": "price_ambiguous",
    "partial_parse": "partial_parse",
    "parse_failed": "parse_failed",
    "missed_url": "missed_url",
}
_VALID_FAILURE_MODES = {
    "missed_url", "partial_parse", "price_ambiguous",
    "out_of_scope", "quarantine", "parse_failed",
}
_VALID_FORMATS = {"fixed", "auction", "lot", "bundle", "unknown"}


# Out-of-scope/wanted items are deliberately set aside -> `quarantined`.
# Mechanical breakage (LLM error, partial parse, ambiguous price) -> `failed`.
# They are different things and must stay separately countable (BRIEF §3.9 / §6).
_FAILED_MODES = {"parse_failed", "missed_url", "partial_parse", "price_ambiguous"}


def _failure_mode(reason: str | None) -> tuple[str, str, str] | None:
    """Map a free-text reason to (status, failure_mode, details)."""
    if not reason:
        return None
    key = reason.strip().lower().replace(" ", "_").replace("-", "_")
    mode = _FAILURE_MODE_MAP.get(key, "quarantine")
    if mode not in _VALID_FAILURE_MODES:
        mode = "quarantine"
    status = "failed" if mode in _FAILED_MODES else "quarantined"
    return status, mode, reason


def _observed_at(value: str | None, fallback: datetime) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return fallback


def ensure_category(conn: psycopg.Connection, name: str) -> None:
    """Categories are data, not DDL (BRIEF §3.7): insert on first sight."""
    if not name:
        return
    conn.execute(
        "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
        (name,),
    )


def insert_capture(conn: psycopg.Connection, capture: RawCapture) -> UUID:
    """Idempotently persist a raw capture; returns its row id.

    Deduplicated on (source, source_listing_id, checksum) — re-ingesting the same
    bytes never creates a second row (AC8 / total-capture accounting).
    """
    row = conn.execute(
        """
        INSERT INTO raw_captures
            (id, source, source_listing_id, url, fetched_at, checksum,
             raw_payload, payload_format, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_listing_id, checksum) DO NOTHING
        RETURNING id
        """,
        (
            capture.id,
            capture.source,
            capture.source_listing_id,
            capture.url,
            capture.fetched_at,
            capture.checksum,
            capture.raw_payload,
            capture.payload_format,
            Jsonb(capture.metadata),
        ),
    ).fetchone()
    if row:
        return row[0]
    return conn.execute(
        """
        SELECT id FROM raw_captures
        WHERE source = %s AND source_listing_id = %s AND checksum = %s
        """,
        (capture.source, capture.source_listing_id, capture.checksum),
    ).fetchone()[0]


def posting_exists(conn: psycopg.Connection, capture_id: UUID, parser_version: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM postings WHERE capture_id = %s AND parser_version = %s",
            (capture_id, parser_version),
        ).fetchone()
        is not None
    )


def persist_result(
    conn: psycopg.Connection,
    *,
    capture: RawCapture,
    capture_id: UUID,
    result: ExtractionResult,
    parser_version: str = "v1",
) -> UUID | None:
    """Write one `ExtractionResult` as a posting + lines + groups + observations.

    Returns the posting id, or `None` if this (capture, parser_version) already
    exists (replay-safe no-op). Runs inside the caller's transaction.
    """
    failure = _failure_mode(result.quarantine_reason)
    if failure is not None:
        status, failure_mode, failure_details = failure
    else:
        status, failure_mode, failure_details = "extracted", None, None

    listing_format = result.listing_format.value
    if listing_format not in _VALID_FORMATS:
        listing_format = "unknown"

    row = conn.execute(
        """
        INSERT INTO postings
            (capture_id, source, source_listing_id, url, title, description, seller,
             location, currency, listing_format, status, failure_mode, failure_details,
             parser_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (capture_id, parser_version) DO NOTHING
        RETURNING id
        """,
        (
            capture_id,
            capture.source,
            capture.source_listing_id,
            capture.url,
            result.title,
            result.description,
            result.seller,
            result.location,
            result.currency,
            listing_format,
            status,
            failure_mode,
            failure_details,
            parser_version,
        ),
    ).fetchone()
    if row is None:
        return None  # already extracted with this parser version
    posting_id: UUID = row[0]

    # --- lines -----------------------------------------------------------------
    line_ids: dict[int, UUID] = {}
    for line in sorted(result.lines, key=lambda ln: ln.line_number):
        if line.category:
            ensure_category(conn, line.category)
        parent_id = (
            line_ids.get(line.parent_line_number)
            if line.parent_line_number is not None
            else None
        )
        line_id = conn.execute(
            """
            INSERT INTO lines
                (posting_id, parent_line_id, line_number, label, category, quantity,
                 separately_purchasable, raw_text, manufacturer, model_code,
                 capacity_gb, speed_mhz, interface, form_factor)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                posting_id,
                parent_id,
                line.line_number,
                line.label,
                line.category,
                line.quantity,
                line.separately_purchasable,
                line.raw_text,
                line.manufacturer,
                line.model_code,
                line.capacity_gb,
                line.speed_mhz,
                line.interface,
                line.form_factor,
            ),
        ).fetchone()[0]
        line_ids[line.line_number] = line_id

    # --- sale groups + membership ---------------------------------------------
    group_ids: dict[str | None, UUID] = {}
    line_to_group: dict[int, UUID] = {}
    for group in result.sale_groups:
        group_id = conn.execute(
            """
            INSERT INTO sale_groups
                (posting_id, label, price_basis, total_price_cents, total_currency,
                 quantity_in_group, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                posting_id,
                group.label,
                group.price_basis.value,
                group.total_price_cents,
                group.total_currency,
                group.quantity_in_group,
                group.notes,
            ),
        ).fetchone()[0]
        group_ids[group.label] = group_id
        for line_number in group.line_numbers:
            line_id = line_ids.get(line_number)
            if line_id is None:
                continue
            conn.execute(
                """
                INSERT INTO sale_group_lines (sale_group_id, line_id, quantity_in_group)
                VALUES (%s, %s, %s)
                ON CONFLICT (sale_group_id, line_id) DO NOTHING
                """,
                (group_id, line_id, group.quantity_in_group),
            )
            line_to_group.setdefault(line_number, group_id)

    # --- observations ----------------------------------------------------------
    # Guardrail (AC3b): a priced line must reach the DB through a sale group.
    # If the model priced a line but gave no group, wrap it in an explicit_unit
    # group rather than writing a naked price (which the AC3b query would flag).
    for obs in result.observations:
        if obs.line_number is None or obs.price_cents is None:
            continue
        if obs.line_number in line_ids and obs.line_number not in line_to_group:
            group_id = conn.execute(
                """
                INSERT INTO sale_groups
                    (posting_id, label, price_basis, total_price_cents,
                     quantity_in_group, notes)
                VALUES (%s, %s, 'explicit_unit', %s, %s, %s)
                RETURNING id
                """,
                (
                    posting_id,
                    f"line {obs.line_number}",
                    obs.price_cents,
                    max(1, _quantity_of(result, obs.line_number)),
                    "auto-grouped: explicit per-line price with no stated sale group",
                ),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO sale_group_lines (sale_group_id, line_id, quantity_in_group)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (
                    group_id,
                    line_ids[obs.line_number],
                    max(1, _quantity_of(result, obs.line_number)),
                ),
            )
            line_to_group[obs.line_number] = group_id

    for obs in result.observations:
        line_id = line_ids.get(obs.line_number) if obs.line_number is not None else None
        group_id = (
            group_ids.get(obs.sale_group_label)
            if obs.sale_group_label is not None
            else None
        )
        if group_id is None and obs.line_number is not None:
            group_id = line_to_group.get(obs.line_number)

        if obs.available is not None:
            available = obs.available
        else:
            available = True if obs.price_kind.value in {"ask", "bid"} else None

        offer_key = compute_offer_key(
            capture.source,
            capture.source_listing_id,
            obs.line_number or 0,
            obs.sale_group_label,
        )
        conn.execute(
            """
            INSERT INTO observations
                (posting_id, line_id, sale_group_id, offer_key, observed_at,
                 price_cents, price_kind, available, source, raw_evidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                posting_id,
                line_id,
                group_id,
                offer_key,
                _observed_at(obs.observed_at, capture.fetched_at),
                obs.price_cents,
                obs.price_kind.value,
                available,
                capture.source,
                Jsonb({"price_kind": obs.price_kind.value, "capture_id": str(capture.id)}),
            ),
        )

    return posting_id


def _quantity_of(result: ExtractionResult, line_number: int) -> int:
    for line in result.lines:
        if line.line_number == line_number:
            return line.quantity
    return 1


def record_batch(
    conn: psycopg.Connection,
    *,
    batch_key: str,
    model: str,
    prompt_version: str,
    listing_count: int,
    provider: str | None = None,
    tokens_used: int | None = None,
    cost_cents: int | None = None,
    status: str = "succeeded",
    error: str | None = None,
) -> UUID:
    """Record one LLM batch for AC6 (model + prompt version + cost per batch)."""
    if listing_count < 1:
        # extraction_batches has CHECK (listing_count > 0); an empty batch is not a call
        return None  # type: ignore[return-value]
    return conn.execute(
        """
        INSERT INTO extraction_batches
            (batch_key, model, prompt_version, listing_count, tokens_used,
             cost_cents, status, error, provider, finished_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        RETURNING id
        """,
        (
            batch_key, model, prompt_version, listing_count, tokens_used,
            cost_cents, status, error, provider,
        ),
    ).fetchone()[0]


def mark_failed(
    conn: psycopg.Connection,
    posting_id: UUID,
    failure_mode: str,
    details: str,
) -> None:
    """Move a posting to `failed` with an explicit, visible reason."""
    if failure_mode not in _VALID_FAILURE_MODES:
        failure_mode = "quarantine"
    conn.execute(
        "UPDATE postings SET status = 'failed', failure_mode = %s, failure_details = %s,"
        " updated_at = now() WHERE id = %s",
        (failure_mode, details, posting_id),
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
