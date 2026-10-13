"""Fixture loaders for the TechDeals v2 ingestion pipeline.

Each loader reads a real capture from the committed fixture corpus and produces a
`RawCapture` — the pipeline's only input boundary.

Fix vs. the original scaffold: fixture paths are **repo-relative** (default
`<repo>/fixtures`), overridable with `TECHDEALS_FIXTURES_DIR`. The old hardcoded
`/home/coldaine/...` paths meant ingestion could not run in CI, in a container, or
on any machine but the owner's laptop (BRIEF §3.1 "total capture" was unverifiable).
Set the env var to point at the on-disk corpus in BRIEF §5.1.

The corpus is READ-ONLY: we never modify fixture files.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from techdeals.ingestion.contract import RawCapture

# src/techdeals/ingestion/loaders.py -> parents[3] == repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURES_DIR = _REPO_ROOT / "fixtures"

# Deterministic fallback when a capture carries no timestamp of its own, so repeated
# runs produce byte-identical rows (dedup is on checksum, but determinism is nice).
FALLBACK_FETCHED_AT = datetime(2026, 10, 13, 0, 0, 0, tzinfo=timezone.utc)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def fixtures_dir() -> Path:
    """Root of the fixture corpus (env override wins)."""
    env = os.environ.get("TECHDEALS_FIXTURES_DIR")
    return Path(env) if env else DEFAULT_FIXTURES_DIR


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _ts(value: object) -> datetime:
    """Parse an ISO-8601-ish timestamp, falling back to the fixture constant."""
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return FALLBACK_FETCHED_AT


def _item_id_from_url(url: str, default: str) -> str:
    """Pull a stable id out of a marketplace URL (e.g. /itm/295817364221)."""
    clean = url.rstrip("/")
    tail = clean.rsplit("/", 1)[-1]
    return tail or default


def _subdir(name: str) -> Path:
    """Return fixtures/<name>, raising FileNotFoundError if it is absent.

    Loaders keep the original "missing dir -> FileNotFoundError -> skip"
    contract so a partial corpus still runs.
    """
    base = fixtures_dir() / name
    if not base.exists():
        raise FileNotFoundError(f"Fixture directory not found: {base}")
    return base


# --------------------------------------------------------------------------- shopify


def load_shopify_fixtures(subdir: str = "shopify") -> Iterator[RawCapture]:
    """Load Shopify product JSON (clean single-item retail shape, cell (a))."""
    base = _subdir(subdir)
    for json_file in sorted(base.glob("*.json")):
        source = json_file.stem.split("_")[0]  # serverpartdeals_products.json -> serverpartdeals
        data = json.loads(json_file.read_text())

        if isinstance(data, dict) and "products" in data:
            products = data["products"]
        elif isinstance(data, list):
            products = data
        else:
            products = [data]

        for product in products:
            if not isinstance(product, dict):
                continue
            product_id = str(product.get("id", json_file.stem))
            raw_payload = json.dumps(product, sort_keys=True)
            handle = product.get("handle", product_id)
            yield RawCapture(
                source=source,
                source_listing_id=product_id,
                url=product.get("url") or f"https://{source}.example.com/products/{handle}",
                fetched_at=_ts(product.get("updated_at") or product.get("published_at")),
                checksum=_sha256(raw_payload),
                raw_payload=raw_payload,
                payload_format="json",
                metadata={"file": str(json_file), "shape": "shopify_product"},
            )


# ---------------------------------------------------------------------------- reddit


def load_reddit_fixtures(subdir: str = "reddit") -> Iterator[RawCapture]:
    """Load a Reddit Atom feed: multi-line [FS] posts and [W] wanted posts (cell (c))."""
    import xml.etree.ElementTree as ET

    base = _subdir(subdir)
    for xml_file in sorted(base.glob("*.xml")):
        raw_payload = xml_file.read_text()
        root = ET.fromstring(raw_payload)

        for entry in root.findall("atom:entry", ATOM_NS):
            entry_id = entry.findtext("atom:id", "", ATOM_NS)
            link_elem = entry.find("atom:link", ATOM_NS)
            link = link_elem.get("href", "") if link_elem is not None else ""
            title = entry.findtext("atom:title", "", ATOM_NS)
            updated = entry.findtext("atom:updated", "", ATOM_NS)

            entry_xml = ET.tostring(entry, encoding="unicode")
            yield RawCapture(
                source="reddit_homelabsales",
                source_listing_id=entry_id,
                url=link,
                fetched_at=_ts(updated),
                checksum=_sha256(entry_xml),
                raw_payload=entry_xml,
                payload_format="atom",
                metadata={"file": str(xml_file), "title": title},
            )


# -------------------------------------------------------------------------- govdeals


def load_govdeals_fixtures(subdir: str = "govdeals") -> Iterator[RawCapture]:
    """Load GovDeals asset + bidbox pairs as a single capture (cells (d)+(e)).

    One capture per lot: the asset description and the live bidbox belong to the
    same posting, so joining a live bid to a description across two files is part
    of ingestion, not a downstream job.
    """
    base = _subdir(subdir)
    assets: dict[str, Path] = {}
    bidboxes: dict[str, Path] = {}
    for path in sorted(base.glob("*.json")):
        kind, _, lot_id = path.stem.partition("_")
        (assets if kind == "asset" else bidboxes).setdefault(lot_id, path)

    for lot_id, asset_path in sorted(assets.items()):
        asset = json.loads(asset_path.read_text())
        bidbox = json.loads(bidboxes[lot_id].read_text()) if lot_id in bidboxes else {}
        payload = {"asset": asset, "bidbox": bidbox}
        raw_payload = json.dumps(payload, sort_keys=True)
        account_id = asset.get("accountId", "unknown")
        asset_id = asset.get("assetId", lot_id)

        yield RawCapture(
            source="govdeals",
            source_listing_id=f"{account_id}_{asset_id}",
            url=asset.get("assetUrl") or f"https://www.govdeals.com/asset/{account_id}/{asset_id}",
            fetched_at=_ts(bidbox.get("capturedAt") or asset.get("auctionEndDate")),
            checksum=_sha256(raw_payload),
            raw_payload=raw_payload,
            payload_format="json",
            metadata={"file": str(asset_path), "shape": "govdeals_asset_bidbox"},
        )


# ------------------------------------------------------------------- configured server


def load_configserver_fixtures(subdir: str = "configserver") -> Iterator[RawCapture]:
    """Load a single-URL configured-server capture (cell (b): 8-10 components)."""
    base = _subdir(subdir)
    for json_file in sorted(base.glob("*.json")):
        data = json.loads(json_file.read_text())
        raw_payload = json.dumps(data, sort_keys=True)
        url = data.get("source_url", "")
        yield RawCapture(
            source="ebay",
            source_listing_id=_item_id_from_url(url, json_file.stem),
            url=url,
            fetched_at=_ts(data.get("captured_at")),
            checksum=_sha256(raw_payload),
            raw_payload=raw_payload,
            payload_format="json",
            metadata={"file": str(json_file), "shape": "configured_server"},
        )


# ----------------------------------------------------------------------- liquidation


def load_liquidation_fixtures(subdir: str = "liquidation") -> Iterator[RawCapture]:
    """Load liquidation.com triples (listing card + manifest + auction detail)."""
    base = _subdir(subdir)
    lot_files: dict[str, list[Path]] = {}
    for html_file in sorted(base.glob("*.html")):
        parts = html_file.stem.rsplit("_", 1)
        lot_id = parts[1] if len(parts) == 2 else html_file.stem
        lot_files.setdefault(lot_id, []).append(html_file)

    for lot_id, files in sorted(lot_files.items()):
        combined_html = "".join(f"<!-- {f.name} -->\n{f.read_text()}\n\n" for f in sorted(files))
        yield RawCapture(
            source="liquidation_com",
            source_listing_id=lot_id,
            url=f"https://www.liquidation.com/auction/view?id={lot_id}",
            fetched_at=FALLBACK_FETCHED_AT,
            checksum=_sha256(combined_html),
            raw_payload=combined_html,
            payload_format="html",
            metadata={"lot_id": lot_id, "files": [str(f) for f in files]},
        )


# ------------------------------------------------------------------------ quarantine


def load_quarantine_fixtures(subdir: str = "quarantine") -> Iterator[RawCapture]:
    """Load out-of-scope / consumer captures that must land in quarantine (cell (f))."""
    base = _subdir(subdir)
    for json_file in sorted(base.glob("*.json")):
        data = json.loads(json_file.read_text())
        raw_payload = json.dumps(data, sort_keys=True)
        url = data.get("source_url", "")
        yield RawCapture(
            source="ebay",
            source_listing_id=_item_id_from_url(url, json_file.stem),
            url=url,
            fetched_at=_ts(data.get("captured_at")),
            checksum=_sha256(raw_payload),
            raw_payload=raw_payload,
            payload_format="json",
            metadata={"file": str(json_file), "shape": "consumer_item"},
        )


LOADERS = [
    ("shopify", load_shopify_fixtures),
    ("reddit", load_reddit_fixtures),
    ("govdeals", load_govdeals_fixtures),
    ("configserver", load_configserver_fixtures),
    ("liquidation", load_liquidation_fixtures),
    ("quarantine", load_quarantine_fixtures),
]


def load_all_fixtures(max_per_source: int | None = None) -> Iterator[RawCapture]:
    """Yield every capture in the corpus, skipping absent sub-directories."""
    for name, loader_func in LOADERS:
        try:
            count = 0
            for capture in loader_func():
                yield capture
                count += 1
                if max_per_source is not None and count >= max_per_source:
                    break
        except FileNotFoundError:
            continue
        except Exception as exc:  # surface, don't hide: a broken fixture is a defect
            print(f"Warning: Error loading {name}: {exc}")
            continue
