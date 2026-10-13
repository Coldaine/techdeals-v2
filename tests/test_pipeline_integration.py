"""End-to-end DB test: fixtures -> raw_captures -> postings -> acceptance views.

Requires a scratch Postgres. Set TECHDEALS_TEST_DATABASE_URL to enable; the suite
SKIPS otherwise (so the default unit run needs no database). It RESETS that scratch
database, so never point it at anything you care about:

    TECHDEALS_TEST_DATABASE_URL=postgresql://user@host:port/scratch uv run pytest
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TECHDEALS_TEST_DATABASE_URL"),
    reason="set TECHDEALS_TEST_DATABASE_URL to a scratch Postgres to run DB tests",
)


@pytest.fixture()
def conn():
    os.environ["NEON_DATABASE_URL"] = os.environ["TECHDEALS_TEST_DATABASE_URL"]
    from techdeals.db.connection import get_connection
    from techdeals.db.migrations import reset_database

    reset_database()
    connection = get_connection()
    yield connection
    connection.close()


def _one(conn, sql: str):
    return conn.execute(sql).fetchone()[0]


@pytest.mark.asyncio
async def test_fixture_corpus_runs_end_to_end(conn) -> None:
    from techdeals.ingestion.loaders import load_all_fixtures
    from techdeals.pipeline import extract, ingest

    captures = list(load_all_fixtures())
    assert len(captures) == 14, "fixture corpus changed; update the cassette if intended"

    ingest(conn, captures)
    summary = await extract(conn, captures, provider="offline", batch_size=20)

    # AC1 total capture
    assert _one(conn, "SELECT count(*) FROM raw_captures") == 14
    assert _one(conn, "SELECT count(DISTINCT source) FROM raw_captures") >= 5
    assert summary.postings == 14
    assert summary.quarantined == 2

    # AC2 decomposition: the configured server is 8 lines behind one URL
    assert _one(
        conn,
        "SELECT count(*) FROM lines l JOIN postings p ON p.id = l.posting_id "
        "WHERE p.source_listing_id = '295817364221'",
    ) == 8
    assert _one(
        conn, "SELECT max(c) FROM (SELECT count(*) c FROM lines GROUP BY posting_id) t"
    ) >= 8

    # AC3 no fabricated prices: every group carries an explicit basis, and
    # quantity-ambiguous lots are labelled bound_only rather than divided.
    assert _one(conn, "SELECT count(*) FROM sale_groups WHERE price_basis IS NULL") == 0
    assert _one(conn, "SELECT count(*) FROM sale_groups WHERE price_basis = 'bound_only'") >= 5

    # AC3b + the naked-line-price guardrail
    assert _one(
        conn,
        "SELECT count(*) FROM observations o "
        "LEFT JOIN sale_group_lines sgl ON sgl.line_id = o.line_id "
        "WHERE o.line_id IS NOT NULL AND o.price_cents IS NOT NULL "
        "AND sgl.sale_group_id IS NULL",
    ) == 0

    # AC4 time series, AC5 lazy identity, AC9 honest quarantine
    assert _one(conn, "SELECT count(*) FROM observations WHERE superseded_by IS NULL") > 0
    assert _one(conn, "SELECT count(*) FROM postings WHERE status = 'extracted'") == 12
    assert _one(conn, "SELECT count(*) FROM resolutions") == 0  # unresolved is still visible
    quarantined = dict(
        conn.execute(
            "SELECT failure_mode, count(*) FROM postings "
            "WHERE status = 'quarantined' GROUP BY failure_mode"
        ).fetchall()
    )
    assert quarantined.get("out_of_scope") == 2

    # AC6 batch economics: one batched call, never one listing at a time
    assert _one(conn, "SELECT count(*) FROM extraction_batches") == 1
    assert _one(conn, "SELECT max(listing_count) FROM extraction_batches") == 14
    assert _one(conn, "SELECT COALESCE(sum(listing_count) FILTER (WHERE listing_count = 1), 0) "
                      "FROM extraction_batches") == 0

    # AC7 dynamic categories, AC8 replay safety
    assert _one(conn, "SELECT count(*) FROM categories") >= 11
    assert _one(
        conn,
        "SELECT count(*) FROM (SELECT 1 FROM raw_captures "
        "GROUP BY source, source_listing_id, checksum HAVING count(*) > 1) d",
    ) == 0

    # Spec attribute query (BRIEF 6 target query 1)
    assert _one(
        conn,
        "SELECT count(*) FROM lines WHERE category = 'ram' "
        "AND interface = 'DDR4' AND capacity_gb = 32",
    ) >= 1


@pytest.mark.asyncio
async def test_replay_is_idempotent_and_versioned(conn) -> None:
    from techdeals.ingestion.loaders import load_all_fixtures
    from techdeals.pipeline import extract

    captures = list(load_all_fixtures())
    await extract(conn, captures, provider="offline")

    again = await extract(conn, captures, provider="offline")
    assert again.postings == 0
    assert again.skipped_replay == 14

    versioned = await extract(conn, captures, provider="offline", parser_version="v2")
    assert versioned.postings == 14
    counts = dict(
        conn.execute(
            "SELECT parser_version, count(*) FROM postings GROUP BY parser_version"
        ).fetchall()
    )
    assert counts == {"v1": 14, "v2": 14}  # new version, never mutated history


@pytest.mark.asyncio
async def test_priced_line_without_sale_group_is_not_written_naked(conn) -> None:
    """The AC3b guardrail: an explicit per-line price gets wrapped, not written bare."""
    from datetime import datetime, timezone

    from techdeals.db.persistence import insert_capture, persist_result
    from techdeals.ingestion.contract import RawCapture
    from techdeals.parser.models import (
        ExtractedLine,
        ExtractedObservation,
        ExtractionResult,
        PriceKind,
    )

    capture = RawCapture(
        source="synthetic",
        source_listing_id="naked-price-1",
        url="https://example.com/naked",
        fetched_at=datetime.now(timezone.utc),
        checksum="cafebabe",
        raw_payload="{}",
        payload_format="json",
    )
    capture_id = insert_capture(conn, capture)
    result = ExtractionResult(
        title="Single DIMM",
        lines=[
            ExtractedLine(
                line_number=1, label="32GB DDR4 RDIMM", category="ram", capacity_gb=32
            )
        ],
        sale_groups=[],  # model priced the line but stated no sale group
        observations=[
            ExtractedObservation(line_number=1, price_cents=4500, price_kind=PriceKind.ASK)
        ],
    )
    persist_result(conn, capture=capture, capture_id=capture_id, result=result)
    conn.commit()

    assert _one(
        conn,
        "SELECT count(*) FROM observations o "
        "LEFT JOIN sale_group_lines sgl ON sgl.line_id = o.line_id "
        "WHERE o.line_id IS NOT NULL AND o.price_cents IS NOT NULL "
        "AND sgl.sale_group_id IS NULL",
    ) == 0
    basis = _one(
        conn,
        "SELECT sg.price_basis FROM sale_groups sg "
        "JOIN sale_group_lines sgl ON sgl.sale_group_id = sg.id "
        "JOIN lines l ON l.id = sgl.line_id "
        "WHERE l.posting_id = (SELECT id FROM postings WHERE source_listing_id = 'naked-price-1')",
    )
    assert basis == "explicit_unit"
