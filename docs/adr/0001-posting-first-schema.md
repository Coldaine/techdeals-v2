# Posting-first, not product-first

Status: accepted

The center of the v2 schema is the **Posting** — the captured listing as
evidence — not the Product. Every capture lands as a posting with provenance
before anything is identified, decomposed, or priced; products appear only as
confidence-scored, re-runnable **Resolutions** attached to lines.

## Why the trade-off went this way

Product-first (v1: `core.items` as the hub, offers hanging off items) forces
every listing to be identified *before* it can be stored. The consequences are
on record in the old repo: multi-item postings (a 4-item Reddit post, a
configured server, a 50-DIMM lot) get dropped, force-fit, or merged into wrong
identities; auctions needed a whole parallel model because the core could not
hold a lot; unresolved postings are invisible to the deal views, so a discovery
tool only sees what it already understands. Known false merges (SAS/SATA, UPS)
made identity the least trustworthy layer, yet product-first made it the
gatekeeper.

Posting-first flips that: storage never requires understanding. The four
target queries (BRIEF §6) all read *through* postings — cheapest-N needs
decomposition + per-unit prices + identity + availability; price history needs
append-only observations keyed by offer; lot-worth needs the line hierarchy and
honest price basis; "what did we miss" needs every capture accounted for. A
posting that never resolves is still a row in every accounting view, with its
payload intact for re-extraction.

## What is given up

- **Product-level aggregation is derived, not stored.** Grouping by product,
  dedupe, and category rollups happen in views over resolutions — more joins,
  no cheap "join to items" shortcut.
- **Unresolved is the normal state.** Most rows have no product at all; any
  read path that filters unresolved postings by default is a defect.
- **Identity churn is append-only.** Re-running resolution appends new rows
  rather than updating; consumers must take the newest non-superseded row.

## What is deliberately not recorded here

The old identity graph and auction model are not carried over. Categories are
data over line attributes, not schema. Price/availability ledgers and their
reject-mutation guards are settled design (BRIEF §4) and live in the schema
comments, not in this ADR.
