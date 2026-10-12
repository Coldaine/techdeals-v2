# Phase-0 Research Decision Memo — TechDeals v2

**Status:** decided (research phase, §2 step 0). Read-only study; nothing here is built yet.
**Date:** 2026-10-12.
**Scope of this memo:** three decisions from §2 step 0 — (1) the batched cheap-LLM
structured-extraction pattern, (2) the Postgres time-series approach on Neon,
(3) OSS marketplace-listing parsers worth borrowing ideas from.

**Served target queries (§6):** the target query set is repeated in each section
because §6 requires every choice to name which query it feeds.

---

## 1. Batched cheap-LLM structured extraction

### Decision

A **thin custom batch client calling OpenAI-compatible endpoints with provider
JSON-schema structured outputs** (`response_format: {"type":"json_schema", …,
"strict":true}`), wrapping each batch's listings as an ordered JSON array keyed
by a caller-assigned listing id — not one of the structured-output frameworks
as the engine core. Temperature 0. Per-listing **NLJSON-style chunking
fallback** when a free-tier router endpoint ignores the schema (see below).

### Why not Instructor / BAML / Outlines as the engine core

- **Instructor** is built around one-schema-per-call wrapping. Our unit of
  work is a *batch array of listings inside one schema* (§3.6, §6 batch
  discipline). Instructor can technically do this, but it adds no value over
  Pydantic validation we do anyway, and its retry hooks assume parse failure
  rather than batch-level partial success (one bad listing must not discard
  twenty good ones).
- **BAML** is the most interesting borrowing target: its retry/partial-parse
  story is stronger for weak small models (multiple community comparisons note
  it is more forgiving with smaller models than instructor). Borrow its ideas:
  schema-local-key validation, partial-parse salvage, explicit function-level
  versioning — but not its dependency.
- **Outlines/XGrammar** (local constrained decoding, grammar masks) require
  self-hosting or provider-level support. Local decode means paying GPU
  infrastructure we don't have; provider-level constrained decoding on
  free-tier routers is uneven. Not viable at our cost point.

### JSON mode vs constrained decoding

- OpenRouter supports `response_format` with `json_object` and `json_schema`
  (`strict`) and documents that the router *rejects the request* when the
  chosen model doesn't support it (verified against OpenRouter docs
  2026-10). That rejection behavior is what we want: it converts silent
  schema drift into a loud routing error.
- Constrained decoding (grammar-enforced sampling) is the gold standard for
  *format* validity, but the PR-222 learning stands: **"structured outputs
  constrain format, not truth."** We need JSON-valid, not true — the
  interpretation pass, not the grammar, is where correctness lives.
- The **fallback path** for endpoints that ignore the schema is borrowed
  verbatim in spirit from `big-racks/pipeline/rackrat_pipeline/llmscore.py`:
  accept raw arrays, wrapped objects, bracketed JSON, and NDJSON; per-item
  salvage; retry once with an explicit "reply with ONLY the JSON array"
  nudge. BRIEF §5.1 explicitly tells us to learn from that file and not
  import it; the JSON-repair pattern is the most transferable part.

### Prompt caching

The prompt is architected so the **stable prefix** is: the system prompt +
schema (fixed, versioned) + zero listing content. Listing payloads arrive
last. That ordering is what makes automatic provider caching (OpenAI-style:
automatic ≥1024-token prefixes) and Anthropic-style `cache_control` markers
pay off. Cache reads discount input 0.1–0.5× by provider family on
OpenRouter-routed providers; with a fixed ~1.5–3k-token schema/policy prefix
re-used across every batch in a run, this materially matters for the
near-free endpoints' throughput limits even when the dollar delta is small.

Concretely: write the client to emit the fixed prefix identically every call
(no per-run timestamps or corpus metadata in the prefix), record
`cached_tokens` from the usage block per batch in the cost ledger, and prefer
endpoints whose cache read discount is ≥0.25×.

### Cost logging

Every batch writes an `extraction_run` / `llm_batch` provenance row
(§3.6, §4 run→fetch→parse→artifact chain) with:
model id + base URL, prompt version, batch listing-count, prompt/completion/
cached-token counts from the response `usage`, computed dollar cost at that
model's listed rate, wall-clock latency, HTTP status, retry count, and the
response text checksum. Free endpoints are fine (BRIEF §7 names
`qwen/qwen3.8-omni-flash` at $0.15/MTok prompt and the
`deepseek/deepseek-v4.1-flash` batch tier as catalog-confirmed candidates);
the ledger exists so free-vs-paid is an *evidenced* choice per batch, not a
one-time decision.

### Latency / cost trade-offs (named)

- **Batch size**: dozens per call (BRIEF §3.6 target). Bigger batch = fewer
  calls = better cache amortization and less per-call overhead, but higher
  risk of one malformed listing corrupting the batch, and output-token limits
  bound the batch from above. Pick 25–50 listings as the default and treat
  output-token headroom as the hard constraint, not listing count. The EPYC
  fixture-zero run (376 listings) should land in ~8–15 calls.
- **Reliability vs latency on retries**: temperature 0 + id-keyed verdicts
  means re-asking a *single* missed listing (id-targeted follow-up call) is
  cheap and cache-friendly; avoid re-running whole batches.
- **Free-tier routing instability** (router rotates models mid-tier, some
  ignore `response_format`) is the known operational cost — handled by the
  repair fallback and the per-endpoint failure counters in the ledger.

### Target queries served

- **§6-2** ("what did this cost over time") — extraction must emit
  price-kind and basis fields exactly so the append-only observations are
  kind-separated.
- **§6-4** ("what did we miss") — batch ledger + per-listing id-keyed
  verdicts is the coverage instrument: every capture maps to ≥1 batch record
  or an explicit quarantine.
- **§3.6** batch economics — engine consumes configurable batches per call,
  records model + prompt version + cost per batch.

---

## 2. Postgres time-series approach on Neon

### Decision

**Plain Postgres: append-only `observations` table with declarative
RANGE-partitioning by `observed_at` (monthly partitions, created on demand by
the ingestion step), one btree on `(offer_key, observed_at DESC)` and a BRIN
on `observed_at`, plus thin read views.** No TimescaleDB, no external
analytics store, no pg_partman dependency at this phase.

### Why not TimescaleDB

- Neon ships only the **Apache-2 community edition** of TimescaleDB; the
  proprietary TSL features (notably compression and the full continuous
  aggregates story) are absent, and Neon's own docs treat it as
  enable-on-request rather than core. Compression is the single feature that
  would actually matter for append-only price series at scale — and it is the
  one we would not get.
- Community-edition TimescaleDB at our scale buys little over native
  declarative partitioning: hypertable chunking ≈ our monthly partitions,
  but with an extension dependency, a version/compatibility matrix tied to
  the Postgres major version (it has its own PG-version lags), and a
  management layer that fights with Neon's branch/restore model (extension
  state across branches is exactly where Neon's snapshots get awkward).
- Our schema guardrail (§6: "no stored derivations", replay-supersession,
  not UPDATE) is Postgres-idiomatic already. TimeScaleDB's space-partitioned
  hypertables don't supersede that; they'd just sit alongside.

### Why not external analytics (ClickHouse / DuckDB / similar)

- Nothing in the target query set (§6) needs cross-index analytical scans.
  Query 1 is "cheapest N available **right now**" — an indexed lookup on the
  latest observation per `offer_key`, which is a join/btree problem, not a
  columnar one. Query 2 is "price history for **this** item" — a range scan
  on `(offer_key, observed_at)` with monthly partition pruning. Both are
  cheap on vanilla PG even at 10s of millions of rows.
- An external store creates a second source of truth that the §4 rule
  "derived values in views, not stored columns" would have to fight, plus a
  sync boundary that is precisely the failure mode ("errors compound
  silently") §0 hard part 6 warns about.
- **Revisit trigger:** if the observation table passes ~10M rows *and*
  §6-2-style aggregate scans (distribution of sold prices by category over
  years) become a real analysis need, the right move then is DuckDB reading
  the same tables (read-side only, no second write path), not a migration.

### Partition & index mechanics

- `observations` declared partitioned by RANGE `observed_at`; monthly child
  partitions named `observations_YYYYMM`; the ingestion step creates the
  next month's partition before writing (a two-line `CREATE TABLE … INHERIT`
  — no extension needed).
- Supersession (§4: corrections via supersession, never UPDATE) stays
  row-level: `superseded_by` on the same partition child. Never rewritten
  history means partitions are write-once — which keeps Neon branch-restore
  semantics clean.
- Price-kind separation (§6-2) is a plain column (`price_kind`), no enum
  (§4 convention: text + CHECK).

### Cost / latency trade-offs (named)

- **Neon storage** grows linearly with raw observations; price/availability
  rows are small (tens of bytes), and the corpus scale (20k live listings,
  snapshot pulls at weekly cadence → ~1M observations/yr) is trivially cheap
  on Neon's storage-pricing model. A separate TSDB would not reduce that;
  only retention would.
- **Partition pruning vs retention**: monthly partitions keep the "right
  now" hot path touching a few children; old partitions age into cold
  storage tiers by Neon's own economics. BRIN on `observed_at` keeps the
  time-sorted scans near-free.
- **Compute start/stop cost on Neon**: query-1-style lookups must stay
  small enough to not keep the compute endpoint pinned; partition pruning
  serves that too.

### Target queries served

- **§6-2** — price history per offer_key as separate ask/bid/sold series;
  this is the direct home of the observations table.
- **§6-1** — "cheapest N of spec S available right now": the indexed
  latest-observation join is the availability primitive.
- **§3.4** — "cheapest 32GB DDR4 available right now is a simple indexed
  query" is the literal acceptance criterion.

---

## 3. OSS marketplace-listing parsers worth borrowing ideas from

### Decision (borrow ideas, not code)

Ranked by how much of the BRIEF's problem they actually attack:

1. **`extruct`** (Zyte/ScrapingHub, Apache-2) — embedded structured-data
   extraction (JSON-LD, Microdata, OpenGraph) from HTML. This is the
   **deterministic pre-pass**: most retail fixtures (Shopify-style shapes,
   §5.4 shape 1/3) already carry machine-readable product JSON-LD; pulling
   it first means the LLM never has to re-read HTML boilerplate and the
   batch prompt shrinks to residue + genuinely free text. Cheap, exact, and
   removes a whole class of hallucinated parse from the LLM's plate.
2. **`trafilatura`** (Apache-2) — main-content extraction/boilerplate
   removal for the HTML-only fixtures (§5.4 shape 2 retailer catalog pages,
   shape 3 single-product pages). Borrow as a *capture-preprocessing step*
   that materially reduces tokens per batch (same batch-budget covers more
   listings).
3. **`price-parser`** (Zyte, part of the scraping ecosystem) — battle-tested
   price-string normalization ("US$ 1,234.50", "€1.234,50", ranges, "from")
   into `{currency, value}`. Useful as the deterministic layer that turns
   the LLM's *stated* price text into typed amounts — including refusing
   "from" prices (mirrors the PR-222 rule: never turn 'from' prices into
   exact amounts). Non-goal: currency inference from a dollar symbol is a
   policy decision we keep in the LLM prompt/validator, not in this lib.
4. **Oxylabs `ecommerce-category-scraper`** (open-source, AI-Studio
   pipeline) — reference for the *shape* of an LLM-driven e-commerce
   extraction pipeline (schema → chunked calls → per-item validation), not
   for its scraping layer (BRIEF §0: scrapers are out of scope here).
5. **PR-222's `semantic_cases.json` fixture format** (TechdealsHandoff
   branch `codex/llm-purchase-ingestion`, read-only) — the JSON assertion
   schema ("where the node with capacity 32 GiB must exist, at min_count 1")
   is the best extraction **unit-test pattern** we have. Borrow the format
   wholesale as the way the engine's first EPYC run is scored against human
   reads (§5.3 fixture zero). Do not import the engine code; its
   one-listing-per-call pattern is the defect we are fixing.

Also noted, not recommended: Reddit homelabsales-specific bots on GitHub —
the Atom feed fixture (§5.4 shape 4) is already structured enough that
regex-lite line-splitting does the pre-pass and the LLM handles the rest;
no external project's Reddit parser is better than the BRIEF's own
requirements for that cell.

### Cost / latency trade-offs (named)

- Deterministic pre-passes (`extruct`, `price-parser`, `trafilatura`)
  **reduce LLM input tokens per batch** (the dominant cost on per-token
  billed endpoints) and shrink wall-clock batch latency, at the cost of one
  extra CPU-bound local step per capture — negligible vs any LLM call.
  The risk to manage is *false determinism*: a pre-pass that emits a wrong
  price silently bypasses LLM judgment. Guard with the same provenance
  marking as LLM output: every deterministic extraction row gets a
  `basis = deterministic` provenance tag, checked in the §6-4 "what did we
  miss" view.
- **Borrowing fixture format vs code**: zero runtime cost; it makes
  fixture zero (EPYC) reviewable against a human ground truth instead of
  vibes.

### Target queries served

- **§6-1** — deterministic pre-pass feeds the decomposition + per-unit
  price that query 1 depends on.
- **§6-4** — provenance-tagged deterministic-vs-LLM extraction rows are
  exactly the "every capture accounted for with reason" coverage view.
- **§6-2** — `price-parser`'s refusal of "from" ranges is a direct
  trust-guard for the price-history series.

---

## Summary (one line each)

1. **Extraction pattern**: thin custom batch client on OpenRouter-compatible
   endpoints with provider JSON-schema structured outputs, stable-prefix
   prompts aligned with automatic prompt caching, per-item JSON-salvage
   fallback borrowed from `llmscore.py`, and a per-batch cost ledger row —
   serves §6 queries 2 and 4 and §3.6 batch economics.
2. **Time-series**: plain declarative monthly partitioning + btree/BRIN on
   append-only `observations`; skip TimescaleDB (Neon has community-edition
   only, missing the features that would matter) and external analytics until
   an evidenced need — serves §6 query 2 and 1.
3. **OSS parsers**: borrow `extruct`/`trafilatura`/`price-parser` as
   deterministic pre-pass provenance-tagged layers and PR-222's
   `semantic_cases.json` as the fixture/assertion format — serves §6
   queries 1, 2, and 4.

## Sources consulted

- `/home/coldaine/big-racks/pipeline/rackrat_pipeline/llmscore.py`
  (read-only; batch-of-25 pattern, JSON-repair fallback, cache-key design).
- TechdealsHandoff branch `codex/llm-purchase-ingestion` via `git show`:
  `purchase_ingest/llm.py` (two-call interpret-then-enrich, 16k
  MAX_OUTPUT_TOKENS, untrusted-input discipline), `semantic_cases.json`
  (assertion fixture format).
- Web (2026-10-12): OpenRouter docs on `response_format` structured outputs;
  Neon extension docs and third-party notes on the Apache-2-only
  TimescaleDB edition; prompt-caching behavior and per-provider cache-read
  discounts on OpenRouter-routed providers; structured-output library
  comparisons (Instructor vs BAML vs Outlines); the scraping-extraction
  tooling landscape (`extruct`, `trafilatura`, `price-parser`).
