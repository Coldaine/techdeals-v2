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
    base = Path(f"/home/coldaine/TechdealsHandoff/scripts/ingest/{source}/fixtures")
    if not base.exists():
        raise FileNotFoundError(f"Fixture directory not found: {base}")

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

            yield RawCapture(
                source=source,
                source_listing_id=product_id,
                url=product.get("url", product.get("handle", f"file://{json_file}")),
                fetched_at=datetime.now(timezone.utc),
                checksum=hashlib.sha256(raw_payload.encode()).hexdigest(),
                raw_payload=raw_payload,
                payload_format="json",
                metadata={"file": str(json_file)},
            )


def load_govdeals_fixtures(source: str = "govdeals") -> Iterator[RawCapture]:
    """Load GovDeals JSON fixtures (asset + bidbox pairs)."""
    base = Path("/home/coldaine/TechdealsHandoff/scripts/ingest/govdeals/fixtures")
    if not base.exists():
        raise FileNotFoundError(f"Fixture directory not found: {base}")

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
            fetched_at=datetime.now(timezone.utc),
            checksum=hashlib.sha256(raw_payload.encode()).hexdigest(),
            raw_payload=raw_payload,
            payload_format="json",
            metadata={"file": str(json_file), "type": json_file.stem.split("_")[0]},
        )


def load_reddit_fixtures(source: str = "reddit_homelabsales") -> Iterator[RawCapture]:
    """Load Reddit Atom feed fixtures."""
    base = Path("/home/coldaine/TechdealsHandoff/scripts/ingest/reddit_homelabsales/fixtures")
    if not base.exists():
        raise FileNotFoundError(f"Fixture directory not found: {base}")

    import xml.etree.ElementTree as ET

    for xml_file in sorted(base.glob("*.xml")):
        raw_payload = xml_file.read_text()
        root = ET.fromstring(raw_payload)

        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", ns):
            entry_id = entry.findtext("atom:id", "", ns)
            link_elem = entry.find("atom:link", ns)
            link = link_elem.get("href", "") if link_elem is not None else ""
            title = entry.findtext("atom:title", "", ns)
            updated = entry.findtext("atom:updated", "", ns)

            # Serialize the entry back to XML for raw storage
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
                metadata={"file": str(xml_file), "title": title},
            )


def load_liquidation_fixtures(source: str = "liquidation_com") -> Iterator[RawCapture]:
    """Load Liquidation.com HTML fixtures (listing card, manifest, auction detail)."""
    base = Path("/home/coldaine/TechdealsHandoff/scripts/ingest/liquidation_com/fixtures")
    if not base.exists():
        raise FileNotFoundError(f"Fixture directory not found: {base}")

    # Group files by lot ID
    lot_files: dict[str, list[Path]] = {}
    for html_file in sorted(base.glob("*.html")):
        # Extract lot ID from filename (e.g., listing_card_21256289.html -> 21256289)
        parts = html_file.stem.rsplit("_", 1)
        if len(parts) == 2:
            lot_id = parts[1]
            lot_files.setdefault(lot_id, []).append(html_file)

    for lot_id, files in lot_files.items():
        # Combine all HTML files for this lot into one capture
        combined_html = ""
        for f in sorted(files):
            combined_html += f"<!-- {f.name} -->\n{f.read_text()}\n\n"

        yield RawCapture(
            source=source,
            source_listing_id=lot_id,
            url=f"https://www.liquidation.com/auction/view?id={lot_id}",
            fetched_at=datetime.now(timezone.utc),
            checksum=hashlib.sha256(combined_html.encode()).hexdigest(),
            raw_payload=combined_html,
            payload_format="html",
            metadata={"lot_id": lot_id, "files": [str(f) for f in files]},
        )


def load_rackrat_fixtures(source: str = "rackrat") -> Iterator[RawCapture]:
    """Load RackRat snapshot fixtures (from big-racks)."""
    # Try the full snapshot first, fall back to sample
    snapshot_path = Path("/home/coldaine/big-racks/web/public/data/snapshot.json")
    sample_path = Path("/home/coldaine/big-racks/pipeline/tests/fixtures/hits_sample.json")

    if snapshot_path.exists():
        data = json.loads(snapshot_path.read_text())
        listings = data.get("listings", [])
    elif sample_path.exists():
        listings = json.loads(sample_path.read_text())
        if isinstance(listings, dict):
            listings = listings.get("hits", [listings])
    else:
        raise FileNotFoundError("No RackRat fixtures found")

    for listing in listings:
        if not isinstance(listing, dict):
            continue

        listing_id = str(listing.get("id", listing.get("ebay_item", "unknown")))
        raw_payload = json.dumps(listing)

        yield RawCapture(
            source=source,
            source_listing_id=listing_id,
            url=listing.get("url", ""),
            fetched_at=datetime.now(timezone.utc),
            checksum=hashlib.sha256(raw_payload.encode()).hexdigest(),
            raw_payload=raw_payload,
            payload_format="json",
            metadata={"format": "rackrat_meilisearch_hit"},
        )