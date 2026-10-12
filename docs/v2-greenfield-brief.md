# TechDeals v2 — Greenfield Brief

This is the authoritative briefing for the v2 rebuild. It exists so that any agent
(or human) can start cold and understand: what is broken, where we are going, how
we will know we arrived, and where to find the raw material. Read this before
planning anything.

---

## 1. The Problem

**The scrapers work. Ingestion is broken.** Pages get fetched fine. Everything
between "page fetched" and "query result you can trust" is where value dies:

- **Missed URLs** — sources yield links that never become captures.
- **Mis-parsed items** — regex/hand parsers cannot cope with heterogeneous,
  free-text listing language. A server listing is 8–10 distinct items sharing one
  URL and one price.
- **Wrong pricing** — lot totals get divided across components to invent unit
  prices that never existed; asks, bids, sold prices, and cost basis get treated
  as interchangeable.

**The old schema is the wrong shape.** It is product-first (`core.items` is the
hub, offers hang off items): a posting must be identified *before* it fits.
Consequences observed in the old repo:

- Multi-item postings (a Reddit post with 4 items, a configured server, a 50-DIMM
  liquidation lot) get dropped, force-fit, or merged into wrong identities.
- Auctions needed a whole parallel model (`auction_watch.*`) because the core
  could not hold a lot.
- Unresolved postings are invisible to the deal views — the system only sees what
  it already understands, which is backwards for a discovery tool.
- Concrete defects on record: SAS/SATA identity merge, UPS merge,
  `Decimal.normalize()` producing keys like `2E+1tb`, a dead out-of-stock filter
  in `api.current_deals`, the EPYC/server lane parked (issue #224) for lack of
  anywhere to put server contents.

**The domain itself is hostile to neat schemas:** thousands of heterogeneous
hardware items, free-text seller descriptions, prices as time series, and
categories that emerge dynamically (U.3 drives, rackmounted inference servers,
enterprise HDDs, DIMMs…) rather than arriving as a fixed taxonomy.

Nothing in v1 ever reaches the actual goal — **analysis**: sorted, queried,
tallied market data you can trust.

## 2. The Way

Direction is settled; sequencing matters. Each phase feeds the next.

0. **Research** — scan what exists before building: LLM batch/structured
   extraction frameworks, Postgres time-series options (plain partitioning vs
   TimescaleDB vs external analytics), any OSS that already parses marketplace
   listings. Deliverable: a short decision memo.
1. **Ingestion contract** — the canonical shape every scraper's output maps into,
   with the failure modes (missed URL, partial parse, price ambiguity,
   out-of-scope item) written down as requirements, not discovered as bugs.
2. **Posting-first schema on Neon scratch** — everything is a *Posting* (see §4).
   Build and iterate on Neon; production and the existing cluster are untouched.
3. **Batched LLM extraction engine** — small/cheap model, many listings per call.
   NEVER one listing per call. Free endpoints are fine (see §6).
4. **Acceptance is folded in, not a separate harness** — there is NO standalone
   test-framework mission. Phases 2–3 are verified by running a small set of real
   captured listings across source shapes (§5) through the pipeline and checking
   results with plain SQL. Fixtures + a few queries, nothing more.
5. **(Later, not now)** old-corpus migration — imported as raw evidence with
   re-extraction, never trusted identity. Trivial once 1–4 work; ignore until then.

## 3. What Success Looks Like

Falsifiable acceptance criteria — running the fixture set (§5) through the
pipeline and querying the result must show ALL of these:

1. **Total capture**: every fixture posting lands as raw evidence with provenance
   (source, URL, fetched-at, checksum). Nothing silently dropped.
2. **Decomposition**: every fixture produces its expected line count — including
   the configured server (8–10 lines, one URL) and the 50-DIMM lot.
3. **No fabricated prices**: a lot total is never divided into unit prices unless
   the row records `price_basis = homogeneous_division` (or `allocated`); ambiguous
   cases land as `bound_only`. Ask/bid/sold/cost_basis/reference never conflated.
4. **Time series**: price and availability history queryable per posting/line;
   "cheapest 32GB DDR4 available right now" is a simple indexed query.
5. **Lazy identity**: unresolved postings appear in read views immediately;
   resolution is a separate, re-runnable, confidence-scored pass that never
   rewrites history (`offer_key` stable across parser replays).
6. **Batch economics**: the engine consumes listings in configurable batches per
   LLM call (target: dozens per call), runs on free/cheap endpoints, and records
   model + prompt version + cost per batch.
7. **Dynamic categories**: adding a category is inserting data, not migrating
   schema.
8. **Replay safety**: re-ingesting the same capture with a new parser creates a
   new extraction version — never duplicate postings, never mutated history.
9. **Honest quarantine**: out-of-scope/consumer items are marked as such, visible
   in counts, not force-fit into categories.

## 4. Settled Design Decisions (do not reopen)

- **Posting is the center.** Layers:
  `posting → lines → sale groups/terms → observations → resolutions → projections`.
  - *Lines*: nested contents (`parent_line_id`), stated quantity,
    `separately_purchasable` flag.
  - *Sale groups/terms*: what can actually be bought together;
    `price_basis ∈ {explicit_unit, homogeneous_division, bound_only, allocated}`.
  - *Observations*: append-only price/availability events; replay-stable
    `offer_key = sha256(natural key)`; corrections via supersession, never UPDATE.
  - *Resolutions*: candidate product matches, confidence-scored, re-runnable,
    never a write gate.
  - *Categories*: projections/views over line attributes — data, not DDL.
- Carry over from v1 (these were right): append-only ledgers, run→fetch→parse→
  artifact provenance chain, derived values in views not stored columns,
  DB-enforced guards (reject-mutation triggers), judgments separate from facts.
- Physical facts, economic observations, and subjective judgments are three
  different things and live in three different places.
- Conventions: uuidv7 PKs, timestamptz everywhere, text + CHECK (no enum types).

## 5. Where the Patterns Come From

The fixture set is a handful of real captures, not a framework. Sources of truth
for shapes:

- **Old repo fixtures**: `/home/coldaine/TechdealsHandoff/scripts/ingest/*/fixtures/`
  — per-source captured pages/payloads.
- **PR #222** (branch `codex/llm-purchase-ingestion` in TechdealsHandoff): a
  working two-call small-LLM extraction engine with `semantic_cases.json`
  fixtures. Best existing engine semantics (options/nodes/memberships, quantities
  on edges, "never allocate lot price to components") — absorb into v2.
- **Issue corpus** (TechdealsHandoff): #131 Reddit multi-item rules, #204 price
  kinds & cost basis, #224 parked EPYC server lane, #172 agent shortlist needs,
  #223 the owner's own pivot sketch.
- **Old databases** (`market_live`, `techdeals_work`): a mine of real messy raw
  text. Use as *evidence* to replay through the new engine — identity from the
  old store is never trusted (known false merges).
- **Live sources for fresh fixtures**: r/homelabsales, GovDeals/liquidation
  manifests, ServerPartDeals, GoHardDrive, Slickdeals, DiskPrices (the
  clean-single-item control lane).

**Fixture cells** (minimum): (a) clean single-item retail listing;
(b) configured server, 8–10 components, one URL — exactly one cell, do NOT
overfit the suite to it; (c) Reddit multi-item post; (d) liquidation/GovDeals lot
with manifest; (e) lot-total vs per-unit price ambiguity; (f) out-of-scope
consumer item (quarantine path); (g) cost-basis record (internal purchase, not a
market ask).

## 6. Environment & Credentials

- **Neon** (scratch DB host): `NEON_API_KEY` + `NEON_DATABASE_KEY` in Doppler
  `apps-data/dev`. No `neonctl` installed — use the Neon API via `curl`. Never
  print secret values; `--only-names` to locate, `doppler run` to inject.
- **LLM endpoints**: Doppler `ai-automation/dev` has OpenRouter, Kilo
  (`KILO_CODE_API_KEY`, `KILO_GATEWAY_API`), Gemini, Groq, DeepSeek, Mistral,
  Anthropic, OpenAI. `homelab/dev` additionally has LiteLLM gateway keys — a
  self-hosted proxy that may be the cheapest batch path. Prefer free/cheap tiers;
  record cost per batch regardless.
- **Local tooling**: `psql` 18.6, `jq`, `curl`, `python3`, `uv` present.
- **Hard constraint**: do NOT touch the existing production cluster or the old
  databases. Neon is the sandbox.

## 7. Owner's Verbatim Words (intent — do not paraphrase away)

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
- "I would be happiest if you tore down the whole schema and built it from scratch"
- "don't literally remove the database — redesign it. You can use neon (api key in
  doppler) to work on it in the meantime"
- "don't prove it on parked epyc listings — you'll overfit"
- "the fricking scrapers are already built and work fine…. its the ingestion
  that's broken"
- "we don't have to worry about the old [corpus] at all though until the new works"
- "constraints, do not break the existing cluster"

## 8. Process Rules

- **Domain modeling is active**: root `GLOSSARY.md` holds canonical terms only
  (zero implementation details); `docs/adr/NNNN-*.md` records a decision only when
  it is hard to reverse, surprising without context, AND the result of a real
  trade-off. Formats: `/home/coldaine/.agents/skills/domain-modeling/`.
- **Tower mode**: the control tower plans missions with disjoint scopes, spawns
  workers into git worktrees, routes reviews, and merges. Mission briefings carry
  this document plus the owner's verbatim quotes relevant to the mission.
- Old-repo process constraints (PR templates, docs-coupling rules) do NOT apply
  here; this repo starts clean.
