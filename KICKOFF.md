# TechDeals v2 — Greenfield Kickoff Brief

This repo is the greenfield rebuild of the TechDeals ingestion + market-data store.
It was seeded from a long design session in the old repo; everything below is the
carry-over context. Read it before planning.

## Objective

Build the posting-first market-data system:

1. **Schema (Postgres, Neon scratch first)** — everything is a *Posting*: something
   posted for sale, observed at a place and time. Postings decompose into lines
   (nested contents), terms/sale groups (how it can be bought, price basis),
   append-only price/availability observations (time series), and lazy optional
   identity resolution that is never a write gate. Categories are projections,
   built dynamically, not hard-coded tables.
2. **Batched LLM extraction engine** — parsing is the hard part, not scraping.
   Listings are heterogeneous and regex parsers are not accurate enough. Use a
   cheap/small LLM, **batched** (many listings per call, never one at a time);
   free endpoints are acceptable (check Doppler for keys: OpenRouter/Gemini/etc.).
3. **Golden matrix acceptance harness** — prove ingestion across source shapes,
   not one overfit fixture.

## Owner's own words (verbatim intent — do not lose)

- "the problem is a huge amount of heterogenous items, that need to eventually be
  sorted, and queried and tallied for analysis, the fricking data has time series,
  has pricing, has hard to parse items (AGAIN YOU DEFINITELY NEED SOME SORT OF
  BATCHED CHEAP LLM TO PARSE THESE LISTINGS. DONT FRICKING DO ONE AT A TIME PLEASE,
  AND YOU CAN USE THE FREE ENDPOINTS)"
- "think about a typical server listing, 8-10 items, all the same url, you have to
  break them apart you have to apportion the part of the amount it costs, where did
  you see it when did you see it.... again, the scraping is the easy part."
- "trace what happens and you get missed urls, mis-parsed items, wrong pricing"
- "there's a ton of categories that often have to be built dynamically"
- "you're never going to have a parser accurate enough, you'll likely have to have
  a small llm — what are you going to do when the item in question is a server with
  like 10 items inside it listed"
- "I would be happiest if you tore down the whole schema and built it from scratch"
- "don't literally remove the database — redesign it. You can use neon (api key in
  doppler) to work on it in the meantime"
- Old corpus: "we don't have to worry about the old at all though until the new
  works… any amount of the old corpus will be trivial to ingest" → old data is a
  migration input only, imported as raw evidence with re-extraction, never trusted
  identity.
- "don't prove it on parked epyc listings — you'll overfit" → acceptance is a
  golden matrix across source shapes.
- "the fricking scrapers are already built and work fine…. its the ingestion that's
  broken"

## Settled design decisions (do not reopen)

- **Posting** is the center (not product/item). Layers: posting → lines
  (parent_line_id nesting, stated qty, separately_purchasable) → sale groups/terms
  (price_basis: explicit_unit | homogeneous_division | bound_only | allocated;
  price kind: ask | bid | sold | cost_basis | reference — never conflate) →
  append-only observations with replay-stable `offer_key` (sha256 of natural key)
  + supersessions → lazy confidence-scored candidate resolutions → category
  projections and derived metrics in views (never stored columns).
- Never fabricate unit prices by dividing a lot price across components unless the
  basis is recorded as such.
- Unresolved postings must still be visible in read views; identity resolution is
  a separate, re-runnable pass.
- Keep from the old design: append-only ledgers, run→fetch→parse→artifact
  provenance, derived values in views, DB-enforced guards (reject-mutation
  triggers), judgments separate from facts.
- uuidv7 PKs, timestamptz everywhere, text + CHECK constraints (no enum types).

## Source material in the old repo (/home/coldaine/TechdealsHandoff)

- `NORTH_STAR.md`, `GLOSSARY.md`, `docs/decisions/0001–0009` (ADR 0001: derived
  values in views; ADR 0007: price-kind non-conflation; ADR 0009: intake model).
- `docs/plans/posting-centric-intake-model.md` + `sql/postgres/techdeals_work_intake.sql`
  (open PR #228, branch `agent/posting-centric-intake-model` — prior draft of this
  direction; absorb, don't copy blindly).
- PR #222 (branch `codex/llm-purchase-ingestion`): working two-call small-LLM
  extraction engine — options/nodes/memberships graph, quantities on edges, "never
  allocate lot price to components". Best existing engine semantics; reconcile into
  v2. Has `semantic_cases.json` fixtures.
- Issue #223: owner's own pivot sketch (raw_records / source_items / readings /
  reading_lines / price_observations / products).
- Issues #131 (Reddit multi-item rules), #204 (price-kind / cost-basis), #224
  (parked EPYC server lane), #172 (agent shortlist workspace).
- Scraper fixtures: `scripts/ingest/*/fixtures/`.
- Golden matrix cells to cover: clean single-item retail (DiskPrices-style), one
  configured server (EPYC — one cell only), Reddit multi-item post, liquidation /
  GovDeals lot with manifest, lot_total vs per-unit ambiguity, out-of-scope
  consumer item, cost-basis record.

## Environment

- Neon: API key in Doppler (never print secret values; `doppler secrets
  --only-names` to locate the project/config). Create a scratch project/branch
  for v2; production stays untouched.
- Old production cluster exists but is irrelevant to v2 until migration time.

## Process

- Domain-modeling discipline is active: root `GLOSSARY.md` (no implementation
  details — terms only) and `docs/adr/NNNN-*.md` (only when hard-to-reverse +
  surprising + real trade-off). Formats:
  `/home/coldaine/.agents/skills/domain-modeling/GLOSSARY-FORMAT.md` and
  `ADR-FORMAT.md`.
- Tower mode: plan missions with disjoint scopes, spawn workers, review, merge.
