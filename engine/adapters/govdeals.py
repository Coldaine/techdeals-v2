#!/usr/bin/env python3
"""GovDeals asset JSON + bidbox JSON → one listing capture.

The two files are one auction. The asset text is the listing; the bidbox is
the current bid observation. Nothing here is a price judgment: all_in_estimate
and watch notes are left out.
"""

from __future__ import annotations

import argparse
import json
import os
import re


def _text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def project(asset: dict, bidbox: dict) -> dict:
    account = asset["accountId"]
    asset_id = asset["assetId"]
    bid = bidbox.get("currentBid")
    description = _text(asset.get("assetLongDesc") or "")
    if bid is not None:
        description = f"{description} Current bid ${bid}. Bid count {bidbox.get('bidCount')}.".strip()
    return {
        "item_id": f"govdeals-{account}-{asset_id}",
        "title": asset.get("assetShortDesc") or "",
        "description": description,
        "url": f"https://www.govdeals.com/asset/{account}/{asset_id}",
        "timestamp": bidbox.get("assetAuctionEndDateUTC"),
        "domain": "govdeals",
        "currency": asset.get("currencyCode"),
        "current_bid": bid,
        "bid_count": bidbox.get("bidCount"),
        "condition": asset.get("assetConditionCd"),
        "item_location": ", ".join(str(asset.get(k) or "") for k in ("city", "state") if asset.get(k)),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Project a GovDeals asset and bidbox into one capture")
    ap.add_argument("--asset", required=True)
    ap.add_argument("--bidbox", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    with open(args.asset) as handle:
        asset = json.load(handle)
    with open(args.bidbox) as handle:
        bidbox = json.load(handle)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as handle:
        json.dump(project(asset, bidbox), handle, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
