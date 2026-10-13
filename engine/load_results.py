#!/usr/bin/env python3
"""Replay already-extracted results through the current writer.

No LLM call. The saved per-listing results are what the model returned;
build_batch_doc applies the current price-basis rules (lot total vs each)
before the rows hit the database. Requires TDV2_DSN.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Load saved extraction results")
    ap.add_argument("--results", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--parser-version", required=True)
    ap.add_argument("--chunk", type=int, default=40)
    args = ap.parse_args(argv)
    dsn = os.environ.get("TDV2_DSN")
    if not dsn:
        print("TDV2_DSN not set", file=sys.stderr)
        return 2
    with open(args.results) as handle:
        saved = json.load(handle)
    by_id = {str(row["id"]): row for row in saved.get("results") or []}
    paths = sorted(glob.glob(os.path.join(args.raw_dir, "**", "*.json"), recursive=True))
    listings, _dropped = extract.load_listings(paths)
    batch = [listing for listing in listings if listing["client_id"] in by_id]
    missing = sorted(set(by_id) - {listing["client_id"] for listing in batch})
    print(f"loading {len(batch)} saved results from {args.results}; captures missing {len(missing)}", file=sys.stderr)
    if not batch:
        return 1
    wrote = {"extractions": 0, "prices": 0, "lines": 0}
    for start in range(0, len(batch), args.chunk):
        chunk = batch[start:start + args.chunk]
        posting_map = extract.db_upsert_postings(dsn, [extract.postset_payload(listing) for listing in chunk])
        for listing in chunk:
            listing["posting_id"] = posting_map[listing["offer_key"]]
        doc = extract.build_batch_doc(
            chunk, saved.get("model") or extract.DEFAULT_MODEL,
            f"llm_batch:{args.parser_version}", 0.0, by_id, {},
        )
        for note in doc.pop("ledger_notes", []):
            print(f"  engine note: {note}", file=sys.stderr)
        doc, dropped_prices, dropped_avail = extract.db_filter_replayed_observations(dsn, doc)
        if dropped_prices or dropped_avail:
            print(f"  replay dedupe: {len(dropped_prices)} price / {len(dropped_avail)} availability", file=sys.stderr)
        extract.db_write_batch(dsn, doc)
        wrote["extractions"] += len(doc["extractions"])
        wrote["prices"] += len(doc["prices"])
        wrote["lines"] += len(doc["lines"])
        print(f"  chunk {start}: {len(chunk)} listings", file=sys.stderr)
    print(f"wrote {wrote['extractions']} extractions, {wrote['prices']} prices, {wrote['lines']} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
