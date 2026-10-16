"""Fixture loaders for the TechDeals v2 ingestion pipeline.

Each loader reads real fixture files from the corpus and produces
RawCapture objects ready for database insertion.

The corpus is READ-ONLY. We never modify fixture files.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from techdeals.ingestion.contract import RawCapture

REPO_ROOT = Path(__file__).resolve().parents[3]


def load_all_fixtures(max_per_source: int | None = None) -> Iterator[RawCapture]:
    """Load fixtures from all available sources.

    Yields RawCapture objects from all fixture locations.
    Stops gracefully if a source directory doesn't exist.
    """
    loaders = [
        ("waterpanther", load_shopify_fixtures),
        ("serverpartdeals", load_shopify_fixtures),
        ("fusionww", load_shopify_fixtures),
        ("govdeals", load_govdeals_fixtures),
        ("reddit_homelabsales", load_reddit_fixtures),
        ("liquidation_com", load_liquidation_fixtures),
        ("rackrat", load_rackrat_fixtures),
    ]

    for source, loader_func in loaders:
        try:
            source_count = 0
            for capture in loader_func(source=source):
                yield capture
                source_count += 1
                if max_per_source is not None and source_count >= max_per_source:
                    break
        except FileNotFoundError:
            continue
        except Exception as e:
            print(f"Warning: Error loading {source}: {e}")
            continue


def load_shopify_fixtures(source: str) -> Iterator[RawCapture]:
    """Load Shopify-style product JSON fixtures."""
    candidate_bases = [
        REPO_ROOT / "corpus" / "cell-a-shopify" / "captures" / source,
        REPO_ROOT / "corpus" / source,
        REPO_ROOT / "fixtures" / source,
    ]
    base = next((p for p in candidate_bases if p.exists()), None)
    if not base:
        raise FileNotFoundError(f"Fixture directory not found for shopify source: {source}")

    for json_file in sorted(base.glob("*.json")):
        raw_bytes = json_file.read_bytes()
        raw_payload = raw_bytes.decode("utf-8")
        data = json.loads(raw_payload)

        # Handle both single objects and arrays
        products = data if isinstance(data, list) else [data]

        # Handle Shopify collection format: {"products": [...]}
        if isinstance(data, dict) and "products" in data:
            products = data["products"]

        for index, product in enumerate(products):
            if not isinstance(product, dict):
                continue

            product_id = str(product.get("id", json_file.stem))
            fetched_at = _capture_time(product, data if isinstance(data, dict) else None)
            if fetched_at is None:
                _warn_missing_timestamp(source, product_id, json_file)
                continue
            source_url, url_metadata = _source_url_fields(
                product.get("url", product.get("handle", ""))
            )
            selector = (
                f"/products/{index}"
                if isinstance(data, dict) and "products" in data
                else f"/{index}"
                if isinstance(data, list)
                else ""
            )

            yield RawCapture(
                source=source,
                source_listing_id=product_id,
                url=source_url,
                fetched_at=fetched_at,
                checksum=hashlib.sha256(raw_bytes).hexdigest(),
                raw_payload=raw_payload,
                payload_format="json",
                metadata={
                    "file": str(json_file),
                    "payload_selector": selector,
                    "timestamp_provenance": "capture_metadata.fetched_at",
                    **url_metadata,
                },
            )


def load_govdeals_fixtures(source: str = "govdeals") -> Iterator[RawCapture]:
    """Load GovDeals JSON fixtures (asset + bidbox pairs)."""
    candidate_bases = [
        REPO_ROOT / "corpus" / "cell-d-govdeals" / "captures",
        REPO_ROOT / "corpus" / "govdeals",
        REPO_ROOT / "fixtures" / "govdeals",
    ]
    base = next((p for p in candidate_bases if p.exists()), None)
    if not base:
        raise FileNotFoundError(f"Fixture directory not found for govdeals: {source}")

    for json_file in sorted(base.glob("*.json")):
        raw_bytes = json_file.read_bytes()
        raw_payload = raw_bytes.decode("utf-8")
        data = json.loads(raw_payload)

        # Extract identifiers
        account_id = data.get("accountId", "unknown")
        asset_id = data.get("assetId", json_file.stem)
        source_listing_id = str(data.get("item_id") or f"{account_id}_{asset_id}")
        fetched_at = _capture_time(data)
        if fetched_at is None:
            _warn_missing_timestamp(source, source_listing_id, json_file)
            continue
        source_url, url_metadata = _source_url_fields(data.get("url", ""))

        yield RawCapture(
            source=source,
            source_listing_id=source_listing_id,
            url=source_url,
            fetched_at=fetched_at,
            checksum=hashlib.sha256(raw_bytes).hexdigest(),
            raw_payload=raw_payload,
            payload_format="json",
            metadata={
                "file": str(json_file),
                "type": json_file.stem.split("_")[0],
                "timestamp_provenance": "capture_metadata.fetched_at",
                **url_metadata,
            },
        )


def load_reddit_fixtures(source: str = "reddit_homelabsales") -> Iterator[RawCapture]:
    """Load Reddit Atom feed or JSON fixtures."""
    candidate_bases = [
        REPO_ROOT / "corpus" / "cell-c-reddit" / "captures",
        REPO_ROOT / "corpus" / "reddit_homelabsales",
        REPO_ROOT / "fixtures" / "reddit_homelabsales",
    ]
    base = next((p for p in candidate_bases if p.exists()), None)
    if not base:
        raise FileNotFoundError(f"Fixture directory not found for reddit: {source}")

    import xml.etree.ElementTree as ET

    for file_path in sorted(base.glob("*")):
        if file_path.suffix == ".json":
            raw_bytes = file_path.read_bytes()
            raw_payload = raw_bytes.decode("utf-8")
            data = json.loads(raw_payload)
            entry_id = str(data.get("id", file_path.stem))
            fetched_at = _capture_time(data)
            if fetched_at is None:
                _warn_missing_timestamp(source, entry_id, file_path)
                continue
            url, url_metadata = _source_url_fields(data.get("url", ""))
            title = data.get("title", "")

            yield RawCapture(
                source=source,
                source_listing_id=entry_id,
                url=url,
                fetched_at=fetched_at,
                checksum=hashlib.sha256(raw_bytes).hexdigest(),
                raw_payload=raw_payload,
                payload_format="json",
                metadata={
                    "file": str(file_path),
                    "title": title,
                    "timestamp_provenance": "capture_metadata.fetched_at",
                    **url_metadata,
                },
            )
        elif file_path.suffix == ".xml":
            raw_bytes = file_path.read_bytes()
            raw_payload = raw_bytes.decode("utf-8")
            root = ET.fromstring(raw_payload)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            fetch_node = root.find(".//{*}capture_metadata/{*}fetched_at")
            fetched_value = fetch_node.text if fetch_node is not None else None
            fetched_at = _capture_time({"capture_metadata": {"fetched_at": fetched_value}})

            for entry in root.findall("atom:entry", ns):
                entry_id = entry.findtext("atom:id", "", ns)
                link_elem = entry.find("atom:link", ns)
                link = link_elem.get("href", "") if link_elem is not None else ""
                title = entry.findtext("atom:title", "", ns)
                entry_selector = entry_id
                if fetched_at is None:
                    _warn_missing_timestamp(source, entry_id, file_path)
                    continue

                source_url, url_metadata = _source_url_fields(link)
                yield RawCapture(
                    source=source,
                    source_listing_id=entry_id,
                    url=source_url,
                    fetched_at=fetched_at,
                    checksum=hashlib.sha256(raw_bytes).hexdigest(),
                    raw_payload=raw_payload,
                    payload_format="atom",
                    metadata={
                        "file": str(file_path),
                        "title": title,
                        "payload_selector": entry_selector,
                        "timestamp_provenance": "capture_metadata.fetched_at",
                        **url_metadata,
                    },
                )


def load_liquidation_fixtures(source: str = "liquidation_com") -> Iterator[RawCapture]:
    """Load Liquidation.com HTML fixtures (listing card, manifest, auction detail)."""
    candidate_bases = [
        REPO_ROOT / "corpus" / "liquidation_com",
        REPO_ROOT / "fixtures" / "liquidation_com",
    ]
    base = next((p for p in candidate_bases if p.exists()), None)
    if not base:
        return iter(())

    # Group files by lot ID
    lot_files: dict[str, list[Path]] = {}
    for html_file in sorted(base.glob("*.html")):
        parts = html_file.stem.rsplit("_", 1)
        if len(parts) == 2:
            lot_id = parts[1]
            lot_files.setdefault(lot_id, []).append(html_file)

    for lot_id, files in lot_files.items():
        _warn_missing_timestamp(source, lot_id, files[0])
    return iter(())


def load_rackrat_fixtures(source: str = "rackrat") -> Iterator[RawCapture]:
    """Load RackRat snapshot fixtures."""
    candidate_paths = [
        REPO_ROOT / "corpus" / "fixture-zero" / "servers_read_v2.jsonl",
        REPO_ROOT / "corpus" / "rackrat" / "captures.jsonl",
        REPO_ROOT / "corpus" / "rackrat" / "snapshot.json",
        REPO_ROOT / "fixtures" / "rackrat.json",
    ]
    path = next((p for p in candidate_paths if p.exists()), None)
    if not path:
        return

    if path.suffix == ".jsonl":
        jsonl_text = path.read_bytes().decode("utf-8")
        lines = jsonl_text.splitlines(keepends=True)
        if path.name == "servers_read_v2.jsonl":
            print(
                f"Skipping {source}: {len(lines)} human-verified scoring records in {path} "
                "have no capture timestamps; original raw artifacts remain in "
                "corpus/fixture-zero/raw/.",
                file=sys.stderr,
            )
            return
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            raw_bytes = line.encode("utf-8")
            listing = json.loads(line)
            listing_id = str(listing.get("id", listing.get("client_id", "unknown")))
            raw_payload = line
            fetched_at = _capture_time(listing)
            if fetched_at is None:
                _warn_missing_timestamp(source, listing_id or str(line_number), path)
                continue

            source_url, url_metadata = _source_url_fields(listing.get("url", ""))
            yield RawCapture(
                source=source,
                source_listing_id=listing_id,
                url=source_url,
                fetched_at=fetched_at,
                checksum=hashlib.sha256(raw_bytes).hexdigest(),
                raw_payload=raw_payload,
                payload_format="json",
                metadata={
                    "format": "fixture_zero_jsonl",
                    "timestamp_provenance": "capture_metadata.fetched_at",
                    **url_metadata,
                },
            )
    else:
        raw_bytes = path.read_bytes()
        raw_payload = raw_bytes.decode("utf-8")
        data = json.loads(raw_payload)
        listings = data.get("listings", []) if isinstance(data, dict) else data
        for index, listing in enumerate(listings):
            if not isinstance(listing, dict):
                continue
            listing_id = str(listing.get("id", listing.get("ebay_item", "unknown")))
            fetched_at = _capture_time(listing, data if isinstance(data, dict) else None)
            if fetched_at is None:
                _warn_missing_timestamp(source, listing_id, path)
                continue

            source_url, url_metadata = _source_url_fields(listing.get("url", ""))
            yield RawCapture(
                source=source,
                source_listing_id=listing_id,
                url=source_url,
                fetched_at=fetched_at,
                checksum=hashlib.sha256(raw_bytes).hexdigest(),
                raw_payload=raw_payload,
                payload_format="json",
                metadata={
                    "format": "rackrat_hit",
                    "timestamp_provenance": "capture_metadata.fetched_at",
                    "payload_selector": (
                        f"/listings/{index}" if isinstance(data, dict) else f"/{index}"
                    ),
                    **url_metadata,
                },
            )


def _capture_time(
    record: dict[str, Any], inherited_record: dict[str, Any] | None = None
) -> datetime | None:
    """Read only an explicit fetch timestamp from capture metadata."""
    metadata = record.get("capture_metadata")
    if not isinstance(metadata, dict) and inherited_record is not None:
        metadata = inherited_record.get("capture_metadata")
    value = metadata.get("fetched_at") if isinstance(metadata, dict) else None
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _source_url_fields(reported_url: Any) -> tuple[str, dict[str, str]]:
    """Keep only observed HTTP(S) URLs as source links; retain other evidence as metadata."""
    reported = reported_url if isinstance(reported_url, str) else ""
    parsed = urlparse(reported)
    has_source_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    metadata = {"source_url_status": "present" if has_source_url else "incomplete"}
    if parsed.scheme == "file" and reported:
        metadata["artifact_locator"] = reported
    elif reported and not has_source_url:
        metadata["reported_url_value"] = reported
    return (reported if has_source_url else ""), metadata


def _warn_missing_timestamp(source: str, listing_id: str, path: Path) -> None:
    print(
        f"Skipping {source}/{listing_id}: no explicit capture_metadata.fetched_at in {path}; "
        "product updated_at, post updated/published, auction end, and file mtime do not "
        "establish fetch time. Raw artifact is preserved but not ingested.",
        file=sys.stderr,
    )
