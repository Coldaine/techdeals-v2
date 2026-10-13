# Fixture set (the pipeline's committed input corpus)

BRIEF §5 requires fixtures to be **in-repo** — the pipeline's only input boundary is a
captured listing, and until captures live here, ingestion/acceptance cannot run anywhere
except the owner's laptop. This directory is that corpus: one small real capture per
structural shape (BRIEF §5.3 "fixture cells").

Nothing here is synthetic junk (cf. the "Indigo hinge" CSVs explicitly excluded in §5.1).

## Provenance

| Path | Cell (§5.3) | Origin |
|------|-------------|--------|
| `shopify/serverpartdeals_products.json` | (a) clean retail product JSON | **Live capture** from `https://www.serverpartdeals.com/products.json?limit=5`, fetched 2026-10-13. Real `products[]` with `id/title/body_html/variants/price`. |
| `reddit/sample_atom.xml` | (c) Reddit multi-item FOR-SALE post + [W] wanted post | **Live capture** from `https://www.reddit.com/r/homelabsales/.rss?limit=50`, fetched 2026-10-13; trimmed to 5 real entries (see below). |
| `govdeals/asset_30467_94.json` + `bidbox_30467_94.json` | (d)+(e) liquidation lot with a *live* bidbox, lot-total vs per-unit | Authored to the exact shape documented in BRIEF §5.3(d) (asset description + separate live bidbox: `currentBid`, `bidCount`, `all_in_estimate_usd`) for the 64×32GB DIMM lot witnessed at `govdeals/fixtures`. GovDeals serves an SPA with no public JSON API, so the real capture cannot be re-fetched here. |
| `configserver/raw_r2_16slot_h12ssl.json` | (b) configured server, 8–10 components, one URL | Authored to the shape in BRIEF §5.3(b)/§5.4(7): eBay-style eBay structured capture of a 16-bay H12SSL EPYC server. Stands in for the unreachable `raw_r2_16slot_h12ssl.json` in the 512GB discovery zip. |
| `liquidation/listing_card_21256289.html` + `manifest_21256289.html` + `auction_detail_21256289.html` | (d) liquidation.com triple (card + manifest + auction detail) | Authored to the shape in BRIEF §5.3(d)/§5.4(6). |
| `quarantine/consumer_item.json` | (f) out-of-scope consumer item | Authored listing (Nintendo Switch) to drive the honest-quarantine path (BRIEF §3.9). |

`fixtures/expected/extractions.json` holds **recorded model responses** (the "cassette") used
to replay the pipeline deterministically without an LLM endpoint. They are *not* the model —
they are what a correct model should return for each fixture, and they exist so the
persistence + SQL + acceptance path can be verified offline. The real engine
(`techdeals extract`) calls the batched LLM instead.

## Reddit entries kept (all real, from the live feed)

| # | Title | Shape exercised |
|---|-------|-----------------|
| `[fs] Server Equipment, Projectors, misc. ancient Electronics` | multi-item, heterogeneous, 13 prices |
| `[FS] 2x Precision 3240, 3x Optiplex 3080 Mini, various other minis, Intel CPUs, DDR4, DDR5 RAM` | multi-item machine lot |
| `[FS][US-XX] 5× 16TB Seagate Exos X16 SAS HDDs, Micron 5200 PRO 1.92TB & assorted SSDs` | multi-item storage lot |
| `[FS][EU] 36x Samsung 32GB DDR4-2400 ECC RDIMM` | homogeneous quantity lot |
| `[W] [US-NJ] 256GB (4 x 64GB) DDR5 Desktop RAM` | **wanted post → quarantine, never an ask** |

## Refreshing

The live captures can be refreshed with:

```bash
curl -sL "https://www.serverpartdeals.com/products.json?limit=5" -o fixtures/shopify/serverpartdeals_products.json
curl -sL "https://www.reddit.com/r/homelabsales/.rss?limit=50"        -o /tmp/r.xml   # then trim as in this dir
```

Point the loaders at the owner's on-disk corpus (BRIEF §5.1) by setting
`TECHDEALS_FIXTURES_DIR=/home/coldaine/...` — see `techdeals/ingestion/loaders.py`.
