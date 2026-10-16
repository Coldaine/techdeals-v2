from __future__ import annotations

from datetime import datetime, timezone

from techdeals.cli import _posting_offer_key


def test_posting_key_uses_source_url_and_timestamp_not_payload() -> None:
    fetched_at = datetime(2026, 10, 15, tzinfo=timezone.utc)
    same_capture = _posting_offer_key("reddit", "https://example.test/post", fetched_at)

    assert same_capture == _posting_offer_key("reddit", "https://example.test/post", fetched_at)
    assert same_capture != _posting_offer_key("reddit", "https://example.test/other", fetched_at)
    assert same_capture != _posting_offer_key(
        "reddit", "https://example.test/post", datetime(2026, 10, 16, tzinfo=timezone.utc)
    )
    assert same_capture != _posting_offer_key("govdeals", "https://example.test/post", fetched_at)
