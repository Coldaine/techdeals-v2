from __future__ import annotations

import json
from datetime import datetime, timezone

from techdeals.cli import _posting_offer_key, _stored_payload
from techdeals.ingestion.contract import RawCapture
from techdeals.ingestion.loaders import load_rackrat_fixtures, load_shopify_fixtures


def test_posting_key_uses_source_url_and_timestamp_not_payload() -> None:
    fetched_at = datetime(2026, 10, 15, tzinfo=timezone.utc)
    same_capture = _posting_offer_key("reddit", "https://example.test/post", fetched_at, "p1")

    assert same_capture == _posting_offer_key(
        "reddit", "https://example.test/post", fetched_at, "p1"
    )
    assert same_capture != _posting_offer_key(
        "reddit", "https://example.test/other", fetched_at, "p1"
    )
    assert same_capture != _posting_offer_key(
        "reddit", "https://example.test/post", datetime(2026, 10, 16, tzinfo=timezone.utc), "p1"
    )
    assert same_capture != _posting_offer_key(
        "govdeals", "https://example.test/post", fetched_at, "p1"
    )
    assert _posting_offer_key("shopify", "", fetched_at, "product-1") != _posting_offer_key(
        "shopify", "", fetched_at, "product-2"
    )


def test_stored_payload_preserves_non_json_raw_text_and_provenance() -> None:
    raw_html = "<html><body>seller listing</body></html>"
    capture = RawCapture(
        source="liquidation_com",
        source_listing_id="lot-1",
        url="https://example.test/lot-1",
        fetched_at=datetime(2026, 10, 15, tzinfo=timezone.utc),
        checksum="a" * 64,
        raw_payload=raw_html,
        payload_format="html",
        metadata={"timestamp_provenance": "fixture_mtime_fallback"},
    )

    stored = json.loads(_stored_payload(capture))
    assert stored == {
        "payload_format": "html",
        "raw_payload": raw_html,
        "metadata": {
            "timestamp_provenance": "fixture_mtime_fallback",
            "source_listing_id": "lot-1",
        },
    }


def test_waterpanther_artifact_locator_is_not_reported_as_source_url() -> None:
    capture = next(
        item
        for item in load_shopify_fixtures("waterpanther")
        if item.source_listing_id == "5079089938565"
    )

    assert capture.url == ""
    assert capture.metadata["source_url_status"] == "incomplete"
    assert capture.metadata["artifact_locator"].startswith("file://")
    assert capture.metadata["timestamp_provenance"] == "source_capture"


def test_captures_without_source_timestamp_are_skipped_with_disposition(capsys) -> None:
    assert list(load_shopify_fixtures("fusionww")) == []

    warning = capsys.readouterr().err
    assert "Skipping fusionww/fww-prod-001" in warning
    assert "raw artifact is preserved but not ingested" in warning


def test_human_verified_fixture_zero_rows_are_not_ingested_as_captures(capsys) -> None:
    assert list(load_rackrat_fixtures()) == []

    warning = capsys.readouterr().err
    assert "human-verified scoring records" in warning
    assert "original raw artifacts remain in corpus/fixture-zero/raw/" in warning
