#!/usr/bin/env python3
"""Thin Atom-feed → listing-JSON capture adapter (fixture cells c + f).

The engine's input boundary is JSON captures only. This adapter projects an
Atom feed (e.g. reddit_homelabsales sample_atom.xml) into one capture JSON per
<entry>, using ONLY field synonyms the committed packer already maps
(FIELD_SYNONYMS in engine/extract.py). No prompt edits, no engine edits.

Projection (all verbatim from the feed, nothing invented):
  item_id     <- <id>          title   <- <title>   (kept verbatim: the [FS]/[W]
                                                   markers are the scope signal)
  description <- <content type="html"> with entities decoded and block tags
                 turned into newlines (plain text, no rewriting)
  url         <- <link href>
  timestamp   <- <updated>
  domain      <- --source (provenance)

Writes one JSON file per entry into --out-dir. The [W] wanted-post entries get
NO special handling here — the unchanged engine prompt owns scope decisions
(quarantine reason wanted_post). Usage:

  python3 engine/adapters/atom.py --atom path.xml --out-dir corpus/cell-c-reddit/captures
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

ATOM_NS = "{http://www.w3.org/2005/Atom}"
BLOCK_TAG_RE = re.compile(r"</?(?:p|div|br|ul|ol|li|h[1-6])[^>]*/?>", re.I)


def html_content_to_text(raw: str) -> str:
    """Decode the HTML-escaped markdown div into plain text lines."""
    text = html.unescape(raw or "")
    text = BLOCK_TAG_RE.sub("\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def entry_to_capture(entry: ET.Element, source: str) -> dict:
    title = (entry.findtext(f"{ATOM_NS}title") or "").strip()
    author = (entry.findtext(f"{ATOM_NS}author/{ATOM_NS}name") or "").strip()
    link_el = entry.find(f"{ATOM_NS}link")
    url = (link_el.get("href") if link_el is not None else "") or ""
    content_raw = entry.findtext(f'{ATOM_NS}content[@type="html"]') or ""
    capture = {
        "item_id": (entry.findtext(f"{ATOM_NS}id") or "").strip(),
        "title": title,
        "description": html_content_to_text(content_raw),
        "url": url,
        "timestamp": (entry.findtext(f"{ATOM_NS}updated") or "").strip(),
        "domain": source,
        "seller_name": author,
    }
    return capture


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Atom feed → listing-JSON captures")
    ap.add_argument("--atom", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--source", default=None, help="domain value (default: feed host)")
    args = ap.parse_args(argv)

    feed = ET.parse(args.atom).getroot()
    default_source = urlparse(feed.findtext(f"{ATOM_NS}id") or "") or ""
    source = args.source or (unquote(urlparse(default_source).netloc) if default_source else "atom")
    entries = feed.findall(f"{ATOM_NS}entry")
    if not entries:
        entries = feed.findall("entry")

    os.makedirs(args.out_dir, exist_ok=True)
    written = []
    for entry in entries:
        capture = entry_to_capture(entry, source)
        if not capture["item_id"]:
            continue
        path = os.path.join(args.out_dir, f"{capture['item_id']}.json")
        with open(path, "w") as f:
            json.dump(capture, f, ensure_ascii=False, indent=2)
        written.append((capture["item_id"], capture["title"], len(capture["description"])))
    for iid, title, dlen in written:
        print(f"  {iid}: {title} ({dlen} chars of content)")
    print(f"wrote {len(written)} captures to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
