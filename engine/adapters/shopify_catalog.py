#!/usr/bin/env python3
"""Thin Shopify-catalog → listing-JSON capture adapter (fixture cell a).

The committed packer consumes JSON captures whose top-level fields it maps by
synonym (FIELD_SYNONYMS in engine/extract.py). Cell (a)'s witnesses are
collection-page wrappers — {"products": [ ... ]} — whose per-product fields
(id/title/body_html/variants/price) the packer cannot see from the wrapper
top (measured dry-run on the committed engine: the wrapper condenses to `{}`).
This adapter is the THIN fix inside the JSON-only boundary: split the wrapper
into one capture per product and project each product's fields onto the
synonyms the packer already maps. NO prompt edits, NO engine edits, and no
economics invented — only verbatim per-product facts.

Projection (all verbatim):
  title      <- name | title
  price      <- price | variants[0].price
  currency   <- currency | "USD" only when a dollar price is present is NOT
                claimed — currency stays null and the engine records it as
                unstated (its existing rule)
  description<- body_html stripped to plain text
  specs      <- attributes ([{name, value}] — the packer's spec shape)
  variants   <- one packer-shaped group per variant option
                ({"variant_type": ..., "options": [{"name","price","in_stock"}]})
  availability/quantity_available
  url        <- "file://<fixture path>#<handle>" (honest local provenance; the
                fixture carries no product URL)
  timestamp  <- updated_at
  brand/mpn/category/item_id
Everything else (listPrice, quantity, leadTimeDays, productStatus, ...) is
passed through untouched — the packer's unknown-scalar budget keeps it as
extra_* fields.

Usage:
  python3 engine/adapters/shopify_catalog.py --catalog path.json \
      --out-dir corpus/cell-a-shopify/captures --source waterpanther
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re

TAG_RE = re.compile(r"<[^>]+>")
HTML_ENTITY_RE = re.compile(r"&[a-z#0-9]+;")


def html_to_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = TAG_RE.sub(" ", text)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(ln for ln in lines if ln)).strip()


def product_to_capture(product: dict, source: str, fixture_path: str) -> dict:
    variants = product.get("variants") or []
    v0 = variants[0] if variants else {}
    price = product.get("price", v0.get("price"))
    title = product.get("name") or product.get("title") or ""
    capture = {
        "item_id": str(product.get("productId") or product.get("id") or ""),
        "title": title,
        "brand": (product.get("manufacturer") or {}).get("name") or product.get("vendor"),
        "mpn": product.get("mpn"),
        "category": product.get("category") or product.get("product_type"),
        "price": price,
        "quantity_available": product.get("quantity")
                              if isinstance(product.get("quantity"), int) else None,
        "availability": ("available" if v0.get("available") is True
                         else "unavailable" if v0.get("available") is False else None),
        "description": html_to_text(product.get("body_html") or ""),
        "url": f"file://{fixture_path}#{product.get('handle') or capture_id(product)}",
        "timestamp": product.get("updated_at"),
        "domain": source,
    }
    attrs = product.get("attributes")
    if attrs:
        capture["specs"] = attrs
    if variants:
        capture["variants"] = [{
            "variant_type": "Variant",
            "options": [{
                "name": v.get("title") or v.get("option1") or title,
                "price": v.get("price"),
                "in_stock": v.get("available"),
            } for v in variants],
        }]
    # pass-through facts the prompt may legitimately read, untouched
    for k in ("listPrice", "totalAvailableQuantity", "leadTimeDays", "productStatus", "isActive"):
        if k in product and product[k] is not None:
            capture[f"_{k}"] = product[k]
    return capture


def capture_id(product: dict) -> str:
    return str(product.get("productId") or product.get("id") or "unnamed")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Shopify catalog JSON → per-product captures")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--source", required=True)
    args = ap.parse_args(argv)

    with open(args.catalog) as f:
        data = json.load(f)
    products = data.get("products") if isinstance(data, dict) else data
    if not isinstance(products, list):
        ap.error("catalog has no products array")

    os.makedirs(args.out_dir, exist_ok=True)
    count = 0
    for product in products:
        capture = product_to_capture(product, args.source, os.path.abspath(args.catalog))
        iid = capture["item_id"] or capture_id(product)
        capture["item_id"] = iid
        with open(os.path.join(args.out_dir, f"{iid}.json"), "w") as f:
            json.dump(capture, f, ensure_ascii=False, indent=1)
        count += 1
    print(f"wrote {count} captures to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
