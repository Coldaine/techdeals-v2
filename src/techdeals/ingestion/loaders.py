"""Fixture loaders for the TechDeals v2 ingestion pipeline.

Each loader reads real fixture files from the corpus and produces
RawCapture objects ready for database insertion.

The corpus is READ-ONLY. We never modify fixture files.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

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
        data = json.loads(json_file.read_text())

        # Handle both single objects and arrays
        products = data if isinstance(data, list) else [data]

        # Handle Shopify collection format: {"products": [...]}
        if isinstance(data, dict) and "products" in data:
            products = data["products"]

        for product in products:
            if not isinstance(product, dict):
                continue

            product_id = str(product.get("id", json_file.stem))
            raw_payload = json.dumps(product)
            fetched_at = _capture_time(product.get("timestamp"), json_file)

            yield RawCapture(
                source=source,
                source_listing_id=product_id,
                url=product.get("url", product.get("handle", f"file://{json_file}")),
                fetched_at=fetched_at,
                checksum=hashlib.sha256(raw_payload.encode()).hexdigest(),
                raw_payload=raw_payload,
                payload_format="json",
                metadata={
                    "file": str(json_file),
                    "timestamp_provenance": (
                        "source_capture" if product.get("timestamp") else "fixture_mtime_fallback"
                    ),
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
        data = json.loads(json_file.read_text())
        raw_payload = json.dumps(data)

        # Extract identifiers
        account_id = data.get("accountId", "unknown")
        asset_id = data.get("assetId", json_file.stem)
        source_listing_id = f"{account_id}_{asset_id}"

        yield RawCapture(
            source=source,
            source_listing_id=source_listing_id,
            url=f"https://www.govdeals.com/asset/{asset_id}",
            fetched_at=_capture_time(data.get("timestamp"), json_file),
            checksum=hashlib.sha256(raw_payload.encode()).hexdigest(),
            raw_payload=raw_payload,
            payload_format="json",
            metadata={
                "file": str(json_file),
                "type": json_file.stem.split("_")[0],
                "timestamp_provenance": (
                    "source_capture" if data.get("timestamp") else "fixture_mtime_fallback"
                ),
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
            data = json.loads(file_path.read_text())
            raw_payload = json.dumps(data)
            entry_id = str(data.get("id", file_path.stem))
            url = data.get("url", f"https://reddit.com/comments/{entry_id}")
            title = data.get("title", "")

            yield RawCapture(
                source=source,
                source_listing_id=entry_id,
                url=url,
                fetched_at=_capture_time(data.get("timestamp"), file_path),
                checksum=hashlib.sha256(raw_payload.encode()).hexdigest(),
                raw_payload=raw_payload,
                payload_format="json",
                metadata={
                    "file": str(file_path),
                    "title": title,
                    "timestamp_provenance": (
                        "source_capture" if data.get("timestamp") else "fixture_mtime_fallback"
                    ),
                },
            )
        elif file_path.suffix == ".xml":
            raw_payload = file_path.read_text()
            root = ET.fromstring(raw_payload)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall("atom:entry", ns):
                entry_id = entry.findtext("atom:id", "", ns)
                link_elem = entry.find("atom:link", ns)
                link = link_elem.get("href", "") if link_elem is not None else ""
                title = entry.findtext("atom:title", "", ns)
                updated = entry.findtext("atom:updated", "", ns)

                entry_xml = ET.tostring(entry, encoding="unicode")
                fetched_at = datetime.now(timezone.utc)
                if updated:
                    try:
                        fetched_at = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    except ValueError:
                        pass

                yield RawCapture(
                    source=source,
                    source_listing_id=entry_id,
                    url=link,
                    fetched_at=fetched_at,
                    checksum=hashlib.sha256(entry_xml.encode()).hexdigest(),
                    raw_payload=entry_xml,
                    payload_format="atom",
                    metadata={"file": str(file_path), "title": title},
                )


def load_liquidation_fixtures(source: str = "liquidation_com") -> Iterator[RawCapture]:
    """Load Liquidation.com HTML fixtures (listing card, manifest, auction detail)."""
    candidate_bases = [
        REPO_ROOT / "corpus" / "liquidation_com",
        REPO_ROOT / "fixtures" / "liquidation_com",
    ]
    base = next((p for p in candidate_bases if p.exists()), None)
    if not base:
        return

    # Group files by lot ID
    lot_files: dict[str, list[Path]] = {}
    for html_file in sorted(base.glob("*.html")):
        parts = html_file.stem.rsplit("_", 1)
        if len(parts) == 2:
            lot_id = parts[1]
            lot_files.setdefault(lot_id, []).append(html_file)

    for lot_id, files in lot_files.items():
        combined_html = ""
        for f in sorted(files):
            combined_html += f"<!-- {f.name} -->\n{f.read_text()}\n\n"

        yield RawCapture(
            source=source,
            source_listing_id=lot_id,
            url=f"https://www.liquidation.com/auction/view?id={lot_id}",
            fetched_at=_capture_time(None, files[0]),
            checksum=hashlib.sha256(combined_html.encode()).hexdigest(),
            raw_payload=combined_html,
            payload_format="html",
            metadata={
                "lot_id": lot_id,
                "files": [str(f) for f in files],
                "timestamp_provenance": "fixture_mtime_fallback",
            },
        )


def load_rackrat_fixtures(source: str = "rackrat") -> Iterator[RawCapture]:
    """Load RackRat snapshot fixtures."""
    candidate_paths = [
        REPO_ROOT / "corpus" / "fixture-zero" / "servers_read_v2.jsonl",
        REPO_ROOT / "corpus" / "rackrat" / "snapshot.json",
        REPO_ROOT / "fixtures" / "rackrat.json",
    ]
    path = next((p for p in candidate_paths if p.exists()), None)
    if not path:
        return

    if path.suffix == ".jsonl":
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            listing = json.loads(line)
            listing_id = str(listing.get("id", listing.get("client_id", "unknown")))
            raw_payload = json.dumps(listing)

            yield RawCapture(
                source=source,
                source_listing_id=listing_id,
                url=listing.get("url", ""),
                fetched_at=_capture_time(listing.get("timestamp"), path),
                checksum=hashlib.sha256(raw_payload.encode()).hexdigest(),
                raw_payload=raw_payload,
                payload_format="json",
                metadata={
                    "format": "fixture_zero_jsonl",
                    "timestamp_provenance": "fixture_mtime_fallback",
                },
            )
    else:
        data = json.loads(path.read_text())
        listings = data.get("listings", []) if isinstance(data, dict) else data
        for listing in listings:
            if not isinstance(listing, dict):
                continue
            listing_id = str(listing.get("id", listing.get("ebay_item", "unknown")))
            raw_payload = json.dumps(listing)

            yield RawCapture(
                source=source,
                source_listing_id=listing_id,
                url=listing.get("url", ""),
                fetched_at=_capture_time(listing.get("timestamp"), path),
                checksum=hashlib.sha256(raw_payload.encode()).hexdigest(),
                raw_payload=raw_payload,
                payload_format="json",
                metadata={
                    "format": "rackrat_hit",
                    "timestamp_provenance": (
                        "source_capture" if listing.get("timestamp") else "fixture_mtime_fallback"
                    ),
                },
            )


def _capture_time(value: str | None, path: Path) -> datetime:
    """Use a recorded capture timestamp or deterministic fixture fallback.

    The fallback is only a stable ingestion key for staged fixtures. It does not
    establish when the source was observed.
    """
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
