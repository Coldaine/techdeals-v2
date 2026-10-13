from __future__ import annotations

import json

from techdeals.ingestion.contract import RawCapture
from techdeals.parser.prepare import (
    atom_entry_to_text,
    capture_to_listing,
    capture_to_text,
    html_to_text,
    json_to_text,
)


def _capture(payload: str, fmt: str, **kw) -> RawCapture:
    from datetime import datetime, timezone

    return RawCapture(
        source=kw.get("source", "test"),
        source_listing_id=kw.get("listing_id", "1"),
        url=kw.get("url", "https://example.com/1"),
        fetched_at=datetime.now(timezone.utc),
        checksum="x",
        raw_payload=payload,
        payload_format=fmt,
        metadata=kw.get("metadata", {}),
    )


def test_html_to_text_strips_tags_and_scripts() -> None:
    html = """
    <html><head><style>.x{}</style><title>T</title></head>
    <body><h1>Dell R740</h1><script>var x=1;</script>
    <table><tr><td>2x Xeon 6132</td><td>$1200</td></tr></table></body></html>
    """
    text = html_to_text(html)
    assert "Dell R740" in text
    assert "2x Xeon 6132" in text
    assert "$1200" in text
    assert "var x" not in text  # script stripped
    assert ".x{}" not in text  # style stripped


def test_shopify_json_renders_title_and_prices() -> None:
    product = {
        "title": "15.36TB NVMe SSD",
        "vendor": "ServerPartDeals",
        "body_html": "<p>Enterprise <b>U.2</b> drive</p>",
        "variants": [{"title": "Default", "price": "4099.00", "available": True, "sku": "SWP_1"}],
    }
    text = json_to_text({"products": [product]})
    assert "15.36TB NVMe SSD" in text
    assert "4099.00" in text
    assert "<b>" not in text  # body_html stripped


def test_govdeals_payload_includes_bid() -> None:
    payload = {
        "asset": {
            "accountId": 30467,
            "assetId": 94,
            "assetShortDescription": "LOT OF 64 DIMMS",
            "quantity": 64,
            "assetLongDescription": "<p>64 modules</p>",
        },
        "bidbox": {"currentBid": 1250.0, "bidCount": 9, "all_in_estimate_usd": 1437.5},
    }
    text = json_to_text(payload)
    assert "LOT OF 64 DIMMS" in text
    assert "1250" in text
    assert "1437.5" in text


def test_ebay_capture_renders_specs_and_description() -> None:
    data = {
        "source_url": "https://www.ebay.com/itm/1",
        "title": "Supermicro H12SSL server",
        "price": {"value": 3150.0, "currency": "USD", "format": "fixed"},
        "item_specifics": {"Model": "H12SSL-i"},
        "description": "<p>4x 32GB DDR4</p>",
    }
    text = json_to_text(data)
    assert "Supermicro H12SSL server" in text
    assert "H12SSL-i" in text
    assert "4x 32GB DDR4" in text


def test_atom_entry_to_text() -> None:
    entry = (
        '<entry xmlns="http://www.w3.org/2005/Atom">'
        "<title>[FS] 4x 8TB Exos</title>"
        '<link href="https://reddit.com/x"/>'
        "<content type=\"html\">&lt;p&gt;4x 8TB Exos $280&lt;/p&gt;</content>"
        "</entry>"
    )
    text = atom_entry_to_text(entry)
    assert "4x 8TB Exos" in text
    assert "$280" in text


def test_unknown_json_is_not_dropped() -> None:
    text = json_to_text({"weird": ["shape", 1]})
    assert "weird" in text


def test_capture_to_listing_shape() -> None:
    capture = _capture(json.dumps({"title": "x", "variants": []}), "json", metadata={"title": "T"})
    listing = capture_to_listing(capture)
    assert listing.capture_id == str(capture.id)
    assert listing.payload_format == "json"
    assert listing.raw_text
    assert listing.title == "T"


def test_capture_to_text_passthrough_for_unknown_format() -> None:
    capture = _capture("plain payload", "xml")
    assert capture_to_text(capture) == "plain payload"
