from __future__ import annotations

from datetime import datetime, timezone

from techdeals.ingestion.contract import IngestionStatus, RawCapture


def test_raw_capture_creation() -> None:
    cap = RawCapture(
        source="ebay",
        source_listing_id="12345",
        url="https://ebay.com/itm/12345",
        fetched_at=datetime.now(timezone.utc),
        checksum="abc123def456",
        raw_payload="<html>listing</html>",
        payload_format="html",
    )
    assert cap.source == "ebay"
    assert cap.status == IngestionStatus.raw
    assert cap.id is not None


def test_raw_capture_with_metadata() -> None:
    cap = RawCapture(
        source="reddit_homelabsales",
        source_listing_id="t3_abc123",
        url="https://reddit.com/r/homelabsales/comments/abc123/fs_32gb_ddr4",
        fetched_at=datetime.now(timezone.utc),
        checksum="deadbeef",
        raw_payload="<entry>...</entry>",
        payload_format="atom",
        metadata={"status_code": 200, "content_type": "application/atom+xml"},
    )
    assert cap.metadata["status_code"] == 200
    assert cap.payload_format == "atom"


def test_ingestion_status_values() -> None:
    assert IngestionStatus.raw == "raw"
    assert IngestionStatus.extracting == "extracting"
    assert IngestionStatus.extracted == "extracted"
    assert IngestionStatus.failed == "failed"
    assert IngestionStatus.quarantined == "quarantined"


def test_raw_capture_serialization() -> None:
    cap = RawCapture(
        source="govdeals",
        source_listing_id="30467-94",
        url="https://govdeals.com/asset/30467/94",
        fetched_at=datetime(2026, 10, 12, 10, 0, 0, tzinfo=timezone.utc),
        checksum="aabbccdd",
        raw_payload='{"asset_id": 30467}',
        payload_format="json",
    )
    data = cap.model_dump()
    assert data["source"] == "govdeals"
    assert data["status"] == "raw"
    assert data["payload_format"] == "json"

    roundtrip = RawCapture.model_validate(data)
    assert roundtrip.id == cap.id
    assert roundtrip.source == cap.source


def test_payload_format_validation() -> None:
    cap = RawCapture(
        source="liquidation_com",
        source_listing_id="21256289",
        url="https://liquidation.com/lot/21256289",
        fetched_at=datetime.now(timezone.utc),
        checksum="112233",
        raw_payload="<div>lot</div>",
        payload_format="html",
    )
    assert cap.payload_format == "html"


def test_uuid7_ids_are_unique() -> None:
    a = RawCapture(
        source="ebay",
        source_listing_id="1",
        url="https://ebay.com/1",
        fetched_at=datetime.now(timezone.utc),
        checksum="a",
        raw_payload="a",
        payload_format="html",
    )
    b = RawCapture(
        source="ebay",
        source_listing_id="2",
        url="https://ebay.com/2",
        fetched_at=datetime.now(timezone.utc),
        checksum="b",
        raw_payload="b",
        payload_format="html",
    )
    assert a.id != b.id


def test_failure_mode_enum() -> None:
    from techdeals.ingestion.failure_modes import FailureMode

    assert FailureMode.missed_url == "missed_url"
    assert FailureMode.partial_parse == "partial_parse"
    assert FailureMode.price_ambiguous == "price_ambiguous"
    assert FailureMode.out_of_scope == "out_of_scope"
    assert FailureMode.quarantine == "quarantine"
    assert FailureMode.parse_failed == "parse_failed"


def test_failure_record_creation() -> None:
    from uuid import uuid4

    from techdeals.ingestion.failure_modes import FailureMode, FailureRecord

    rec = FailureRecord(
        capture_id=uuid4(),
        failure_mode=FailureMode.parse_failed,
        details="LLM returned empty extraction",
    )
    assert rec.failure_mode == FailureMode.parse_failed
    assert rec.timestamp is not None
