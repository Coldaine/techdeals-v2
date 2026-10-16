from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from techdeals.cli import _posting_offer_key, _stored_payload
from techdeals.ingestion import loaders
from techdeals.ingestion.contract import RawCapture
from techdeals.ingestion.loaders import (
    load_govdeals_fixtures,
    load_rackrat_fixtures,
    load_reddit_fixtures,
    load_shopify_fixtures,
)


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
        metadata={"timestamp_provenance": "capture_metadata.fetched_at"},
    )

    stored = json.loads(_stored_payload(capture))
    assert stored == {
        "payload_format": "html",
        "raw_payload": raw_html,
        "metadata": {
            "timestamp_provenance": "capture_metadata.fetched_at",
            "source_listing_id": "lot-1",
        },
    }


def test_source_dates_are_not_misrepresented_as_fetch_times(capsys) -> None:
    assert list(load_shopify_fixtures("waterpanther")) == []
    warning = capsys.readouterr().err
    assert "product updated_at" in warning
    assert "Raw artifact is preserved but not ingested" in warning


def test_govdeals_auction_close_is_not_misrepresented_as_fetch_time(capsys) -> None:
    assert list(load_govdeals_fixtures()) == []
    warning = capsys.readouterr().err
    assert "capture_metadata.fetched_at" in warning
    assert "auction end" in warning


def test_explicit_capture_metadata_is_accepted_without_using_source_dates(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(loaders, "REPO_ROOT", tmp_path)
    captures = tmp_path / "corpus/cell-d-govdeals/captures"
    captures.mkdir(parents=True)
    source_text = (
        '{\n  "item_id": "govdeals-30467-94",\n'
        '  "url": "https://www.govdeals.com/asset/30467/94",\n'
        '  "timestamp": "2026-10-08T19:00:00Z",\n'
        '  "capture_metadata": {"fetched_at": "2026-10-01T12:30:00Z"}\n}\n'
    )
    source_bytes = source_text.encode("utf-8")
    (captures / "lot.json").write_bytes(source_bytes)

    capture = next(load_govdeals_fixtures())
    assert capture.source_listing_id == "govdeals-30467-94"
    assert capture.url == "https://www.govdeals.com/asset/30467/94"
    assert capture.fetched_at == datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)
    assert capture.raw_payload == source_text
    assert capture.checksum == hashlib.sha256(source_bytes).hexdigest()
    assert capture.metadata["source_url_status"] == "present"
    assert capture.metadata["timestamp_provenance"] == "capture_metadata.fetched_at"


def test_waterpanther_artifact_locator_is_not_reported_as_source_url(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(loaders, "REPO_ROOT", tmp_path)
    captures = tmp_path / "corpus/cell-a-shopify/captures/waterpanther"
    captures.mkdir(parents=True)
    source_text = (
        '{\n "capture_metadata": {"fetched_at": "2026-10-01T12:30:00Z"},\n'
        ' "products": [{"id":"synthetic-1", "timestamp":"2026-06-24T10:23:29-04:00", '
        '"url":"file:///tmp/products.json#synthetic-1"}]\n}\n'
    )
    (captures / "synthetic.json").write_bytes(source_text.encode("utf-8"))

    capture = next(load_shopify_fixtures("waterpanther"))
    assert capture.url == ""
    assert capture.metadata["source_url_status"] == "incomplete"
    assert capture.metadata["artifact_locator"] == "file:///tmp/products.json#synthetic-1"
    assert capture.fetched_at == datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)
    assert capture.raw_payload == source_text
    assert capture.metadata["payload_selector"] == "/products/0"


def test_reddit_keeps_missing_source_url_incomplete_without_fabricating_link(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(loaders, "REPO_ROOT", tmp_path)
    captures = tmp_path / "corpus/cell-c-reddit/captures"
    captures.mkdir(parents=True)
    source_text = (
        '{"id":"t3_abc123","title":"Sale","capture_metadata":'
        '{"fetched_at":"2026-10-01T12:30:00Z"}}\n'
    )
    source_bytes = source_text.encode("utf-8")
    (captures / "post.json").write_bytes(source_bytes)

    capture = next(load_reddit_fixtures())
    assert capture.source_listing_id == "t3_abc123"
    assert capture.url == ""
    assert capture.metadata["source_url_status"] == "incomplete"
    assert capture.raw_payload == source_text
    assert capture.checksum == hashlib.sha256(source_bytes).hexdigest()


def test_rackrat_jsonl_preserves_exact_line_and_artifact_locator(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(loaders, "REPO_ROOT", tmp_path)
    corpus = tmp_path / "corpus/rackrat"
    corpus.mkdir(parents=True)
    line = (
        '{"id":"rack-7","url":"file:///tmp/listings.json#rack-7",'
        '"capture_metadata":{"fetched_at":"2026-10-01T12:30:00Z"}}\r\n'
    )
    line_bytes = line.encode("utf-8")
    (corpus / "captures.jsonl").write_bytes(line_bytes)

    capture = next(load_rackrat_fixtures())
    assert capture.source_listing_id == "rack-7"
    assert capture.url == ""
    assert capture.metadata["source_url_status"] == "incomplete"
    assert capture.metadata["artifact_locator"] == "file:///tmp/listings.json#rack-7"
    assert capture.raw_payload == line
    assert capture.checksum == hashlib.sha256(line_bytes).hexdigest()


def test_reddit_atom_uses_explicit_fetch_metadata_and_exact_xml_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(loaders, "REPO_ROOT", tmp_path)
    captures = tmp_path / "corpus/cell-c-reddit/captures"
    captures.mkdir(parents=True)
    source_text = (
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        '  <capture_metadata><fetched_at>2026-10-01T12:30:00Z</fetched_at></capture_metadata>\n'
        '  <entry><id>reddit-post-9</id><title>Sale</title>'
        '<updated>2026-10-14T09:00:00Z</updated><link href="file:///tmp/feed.xml" /></entry>\n'
        '</feed>\n'
    )
    source_bytes = source_text.encode("utf-8")
    (captures / "feed.xml").write_bytes(source_bytes)

    capture = next(load_reddit_fixtures())
    assert capture.source_listing_id == "reddit-post-9"
    assert capture.url == ""
    assert capture.metadata["source_url_status"] == "incomplete"
    assert capture.metadata["artifact_locator"] == "file:///tmp/feed.xml"
    assert capture.fetched_at == datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)
    assert capture.raw_payload == source_text
    assert capture.checksum == hashlib.sha256(source_bytes).hexdigest()


def test_captures_without_source_timestamp_are_skipped_with_disposition(capsys) -> None:
    assert list(load_shopify_fixtures("fusionww")) == []

    warning = capsys.readouterr().err
    assert "Skipping fusionww/fww-prod-001" in warning
    assert "Raw artifact is preserved but not ingested" in warning


def test_human_verified_fixture_zero_rows_are_not_ingested_as_captures(capsys) -> None:
    assert list(load_rackrat_fixtures()) == []

    warning = capsys.readouterr().err
    assert "human-verified scoring records" in warning
    assert "original raw artifacts remain in corpus/fixture-zero/raw/" in warning
