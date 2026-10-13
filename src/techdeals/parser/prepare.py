"""Capture -> extraction-input adapter.

The ingestion contract emits `RawCapture` (the page payload). The engine consumes
`RawListingForExtraction` (text). Nothing in the scaffold bridged the two, so even
with fixtures the engine had no input. This module is that bridge.

It is deliberately dumb and deterministic: it turns heterogeneous payloads into a
faithful *text* rendering and leaves every judgement (decomposition, pricing,
quarantine) to the LLM. No regex parsing of listing semantics happens here — the
brief is explicit that heuristics cannot carry this.

Payloads are never dropped: an unrecognised shape still becomes pretty-printed JSON
or tag-stripped HTML, so "what did we miss" (BRIEF §6) stays answerable.
"""
from __future__ import annotations

import json
from html import unescape
from html.parser import HTMLParser
from typing import Any

from techdeals.ingestion.contract import RawCapture
from techdeals.parser.models import RawListingForExtraction

_SKIP_TAGS = {"script", "style", "noscript", "head"}
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5",
    "table", "ul", "ol", "section", "article",
}


class _TextExtractor(HTMLParser):
    """Strip tags, keep visible text, split on block boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")
        if tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self._parts.append(f"[image: {alt}]")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [unescape(line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


def _fmt_price(price: Any) -> str | None:
    if isinstance(price, dict) and price.get("value") is not None:
        return f"{price.get('currency', 'USD')} {price['value']}"
    if isinstance(price, (int, float)):
        return f"USD {price}"
    return None


def _shopify_product_to_text(product: dict[str, Any]) -> str:
    lines = [f"Product: {product.get('title', '')}"]
    if product.get("vendor"):
        lines.append(f"Vendor: {product['vendor']}")
    body = product.get("body_html")
    if body:
        lines.append(html_to_text(str(body)))
    variants = product.get("variants") or []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        price = variant.get("price")
        bits = [variant.get("title") or "default"]
        if price is not None:
            bits.append(f"price {price} {product.get('currency', 'USD')}")
        if variant.get("available") is False:
            bits.append("OUT OF STOCK")
        if variant.get("sku"):
            bits.append(f"sku {variant['sku']}")
        lines.append("Variant: " + " | ".join(str(b) for b in bits))
    return "\n".join(lines)


def _ebay_capture_to_text(data: dict[str, Any]) -> str:
    lines = []
    if data.get("title"):
        lines.append(f"Title: {data['title']}")
    if data.get("condition"):
        lines.append(f"Condition: {data['condition']}")
    if data.get("seller"):
        lines.append(f"Seller: {data['seller']}")
    price = _fmt_price(data.get("price"))
    if price:
        price_field = data.get("price")
        fmt = price_field.get("format") if isinstance(price_field, dict) else None
        lines.append(f"Price: {price}" + (f" ({fmt})" if fmt else ""))
    shipping = _fmt_price(data.get("shipping"))
    if shipping:
        lines.append(f"Shipping: {shipping}")
    specifics = data.get("item_specifics") or {}
    for key, value in specifics.items():
        lines.append(f"{key}: {value}")
    if data.get("description"):
        lines.append("")
        lines.append("Description:")
        lines.append(html_to_text(str(data["description"])))
    return "\n".join(lines)


def _govdeals_to_text(payload: dict[str, Any]) -> str:
    asset = payload.get("asset") or {}
    bidbox = payload.get("bidbox") or {}
    lines = [
        f"Title: {asset.get('assetShortDescription', '')}",
        f"Category: {asset.get('category', '')}",
        f"Quantity: {asset.get('quantity', '')} {asset.get('unitOfMeasure', '')}".strip(),
        f"Seller: {asset.get('sellerName', '')}",
    ]
    location = asset.get("location") or {}
    if isinstance(location, dict) and location:
        lines.append(f"Location: {location.get('city', '')}, {location.get('state', '')}")
    lines.append(f"Auction ends: {asset.get('auctionEndDate', '')}")
    if bidbox:
        current = bidbox.get("currentBid", "")
        bids = bidbox.get("bidCount", 0)
        lines.append(f"Current bid: USD {current} ({bids} bids)")
        if bidbox.get("all_in_estimate_usd") is not None:
            lines.append(f"All-in estimate: USD {bidbox['all_in_estimate_usd']}")
        if bidbox.get("buyerPremiumPercent") is not None:
            lines.append(f"Buyer's premium: {bidbox['buyerPremiumPercent']}%")
    lines.append("")
    lines.append("Description:")
    lines.append(html_to_text(str(asset.get("assetLongDescription", ""))))
    return "\n".join(lines)


def json_to_text(data: Any) -> str:
    """Render a JSON payload as extraction text, shape-aware where it helps."""
    if isinstance(data, dict):
        if "products" in data or ("variants" in data and "title" in data):
            products = data["products"] if "products" in data else [data]
            return "\n\n".join(
                _shopify_product_to_text(p) for p in products if isinstance(p, dict)
            )
        if "asset" in data and "assetId" in (data.get("asset") or {}):
            return _govdeals_to_text(data)
        if "item_specifics" in data or "source_url" in data:
            return _ebay_capture_to_text(data)
    return json.dumps(data, indent=2, sort_keys=True)


def atom_entry_to_text(entry_xml: str) -> str:
    """Render a single Atom <entry> (Reddit RSS) as text."""
    import xml.etree.ElementTree as ET

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(entry_xml)
    lines = [f"Title: {root.findtext('atom:title', '', ns)}"]
    link = root.find("atom:link", ns)
    if link is not None and link.get("href"):
        lines.append(f"URL: {link.get('href')}")
    if root.findtext("atom:updated", "", ns):
        lines.append(f"Posted: {root.findtext('atom:updated', '', ns)}")
    content = root.findtext("atom:content", "", ns) or root.findtext("atom:summary", "", ns)
    if content:
        lines.append("")
        lines.append(html_to_text(content))
    return "\n".join(lines)


def capture_to_text(capture: RawCapture) -> str:
    """Convert a capture's raw payload to plain text for the LLM."""
    fmt = capture.payload_format
    if fmt == "html":
        return html_to_text(capture.raw_payload)
    if fmt == "atom":
        return atom_entry_to_text(capture.raw_payload)
    if fmt == "json":
        try:
            return json_to_text(json.loads(capture.raw_payload))
        except json.JSONDecodeError:
            return capture.raw_payload
    return capture.raw_payload  # xml / unknown: pass through


def capture_to_listing(capture: RawCapture) -> RawListingForExtraction:
    """Adapt a `RawCapture` into the engine's `RawListingForExtraction`."""
    return RawListingForExtraction(
        capture_id=str(capture.id),
        source=capture.source,
        url=capture.url,
        title=capture.metadata.get("title") if isinstance(capture.metadata, dict) else None,
        raw_text=capture_to_text(capture),
        payload_format=capture.payload_format,
    )
