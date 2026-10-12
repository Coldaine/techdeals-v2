# TechDeals v2 — Greenfield Brief

This is the authoritative briefing for the v2 rebuild. It exists so that any agent
(or human) can start cold and understand: what is broken, where we are going, how
we will know we arrived, and where to find the raw material. Read this before
planning anything.

---

## 0. Hard Parts & Requirements (owner-distilled, read first)

### The hard parts

1. **Heterogeneity at scale** — a huge amount of heterogeneous items that must
   eventually be sorted, queried, and tallied for analysis: RAM, SSDs, enterprise
   HDDs, servers, U.3 drives, rackmount inference boxes, used gear.
2. **Parsing is the bottleneck, not scraping** — no regex parser will ever be
   accurate enough on free-text listings; a small/cheap LLM is required.
3. **Multi-item postings** — one URL containing 8–10 items (a configured server);
   contents must be broken apart and the total cost apportioned across them,
   with the basis of any apportionment recorded.
4. **Provenance** — where it was seen and when it was seen, always.
5. **The data is temporal** — prices and availability are time series.
6. **Failure modes compound silently** — missed URLs, mis-parsed items, wrong
   pricing.
7. **Categories don't sit still** — they are built dynamically, from data.
8. **The bar is analysis** — the job is getting everything onto one level playing
   field so it can be sorted/queried/tallied; v1 never got there.

### The requirements

1. **This repo has NO scrapers** — scraping is the easy part and is out of scope
   to start. The old scrapers keep running where they are. If live capture is ever
   needed here, thin fetchers are written fresh, reusing the old scrapers' logic
   as reference only. The problem to solve is everything after the fetch.
2. **Batched, cheap LLM parsing** — many listings per call, never one at a time;
   free/cheap endpoints are fine (OpenRouter, Kilo gateway, LiteLLM — see §6).
3. **Research before building** — check what databases, processing tooling, and
   existing projects/libraries already do this before inventing anything.
4. **Greenfield the schema on Neon** — redesign from scratch; do not literally
   remove the old database.
5. **Do not break the existing cluster.**
6. **Old corpus waits** — ignore it until the new pipeline works; then it becomes
   a trivial migration input.
7. **Don't overfit** — never prove the pipeline on one listing type (e.g. the
   parked EPYC lane); prove it across varied real shapes.
8. **No acceptance-harness bureaucracy** — fixtures + plain SQL checks folded
   into the real work, not a separate framework.

### What we build against (concrete)

- **Input contract**: a raw captured listing — the page payload (HTML/JSON), the
  source URL, and the fetch timestamp. That capture is the pipeline's ONLY input
  boundary. The initial corpus is captures that ALREADY exist (old-repo fixtures,
  raw records in the old databases) — no new scraping is needed to get a wide,
  varied set of real shapes.
- **Store**: Neon Postgres, scratch project (credentials in Doppler
  `apps-data/dev`). Production and the existing cluster are never touched.
- **Parser**: small/cheap LLM over OpenRouter / Kilo gateway / LiteLLM (keys in
  Doppler `ai-automation/dev` and `homelab/dev`), invoked in batches.
- **Explicitly NOT build targets**: the old schema, the old identity graph, old
  application code. This repo starts as an EMPTY FOLDER — no code is copied from
  TechdealsHandoff. The old repo is read-only reference (fixtures, ADRs, issues,
  PR #222's engine semantics to learn from, not to import).

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

## 5. The Corpus (what workers actually ingest) & Pattern Sources

Workers do NOT start empty-handed. The corpus, concrete and inventoried:

### 5.1 Ready-now corpus (local disk, no scraping needed)

- **big-racks / RackRat Constellation** (`/home/coldaine/big-racks`) — the "tons
  of server data":
  - `web/public/data/snapshot.json` — ~3k used-server listings, typed JSON
    (5.0 MB), ships in-repo.
  - Live pull: ~20,000 active server listings from RackRat's public Meilisearch
    backend as typed JSON — one paginated pull, NO HTML scraping
    (`pipeline/rackrat_pipeline/client.py`).
  - `pipeline/rackrat_pipeline/` also contains working reference code for
    normalization, deterministic scoring, and `llmscore.py` — LLM review of
    ambiguous/high-value listings via any OpenAI-compatible endpoint, OpenRouter
    free tier by default. Learn from it; do not import it.
  - `pipeline/tests/fixtures/hits_sample.json` — sample API hits.
- **512GB DIMM discovery bundle** (`/home/coldaine/Downloads/fresh-512gb-server-discovery-2026-09-13.zip`):
  candidate/variant/US-located CSVs, provenance CSV, and 4 raw capture JSONs
  (5.8–9.0 MB each) incl. a 16-slot H12SSL server capture — real multi-item
  server raw payloads with documentation.
- **TechdealsHandoff fixtures** (`/home/coldaine/TechdealsHandoff/scripts/ingest/*/fixtures/`):
  15 sources, real captured payloads — atlas_gen5_ssd, auction_watch,
  central_computers (2.6 MB product-catalog HTML), disctech, diskprices,
  fusionww, goharddrive, google_shopping, govdeals, liquidation_com,
  reddit_homelabsales, serverorbit, serverpartdeals, serversupply, slickdeals,
  spl_psu_tier_list, ssd_pricing_run1, waterpanther.
- **TechdealsHandoff research CSVs** (`/home/coldaine/TechdealsHandoff/research/`):
  SSD pricing exports (brightdata, v1+v2), GPU V100 SXM2 server pricing incl.
  time series and 8×V100 server comps, SPL PSU tier list (5.6 MB),
  large PSU market scan (`data/triage/`).
- **PR #222** (branch `codex/llm-purchase-ingestion` in TechdealsHandoff): a
  working two-call small-LLM extraction engine with `semantic_cases.json`
  fixtures. Best existing engine semantics (options/nodes/memberships, quantities
  on edges, "never allocate lot price to components", untrusted-input discipline,
  null-instead-of-guessing) — absorb the IDEAS, not the code. CAUTION, verified
  2026-10-12: that engine is ONE LISTING PER CALL (`MAX_OUTPUT_TOKENS = 16000`,
  interpret-then-enrich per capture). Its semantics transfer; its calling pattern
  does not — the v2 engine's batched design (dozens of listings per call) is
  genuinely new work, and fixture zero is its first proof.
- **Issue corpus** (TechdealsHandoff): #131 Reddit multi-item rules, #204 price
  kinds & cost basis, #224 parked EPYC server lane, #172 agent shortlist needs,
  #223 the owner's own pivot sketch.
- IGNORE: `/home/coldaine/Downloads/report*.csv` — synthetic junk test data
  ("Indigo hinge", "Walnut bracket"), not real inventory.

### 5.2 The motherlode (not reachable yet, not needed to start)

- **Old databases** (`market_live`, `techdeals_work` on the cluster): the full
  historical raw corpus — 17k+ ServerPartDeals offers, every past capture's raw
  payload. Use later as *evidence* to replay through the new engine; identity
  from the old store is never trusted (known false merges). Currently behind a
  laptop routing issue; do not block on it.

### 5.3 Fixture cells (minimum coverage)

The fixture set is a handful of real captures, not a framework.

**Fixture zero (first, hardest, proves the engine): the EPYC 1P corpus** —
TechdealsHandoff issue #224, data branch
`data/epyc-1p-ebay-listings-2026-10-05`, folder
`data/inbox/epyc-1p-ebay-2026-10-05/`: 376 eBay single-socket EPYC server
listings with raw pages (`raw.tar.gz`), human-verified reads
(`servers_read_v2.csv`/`.jsonl`), a read-the-raw spec (`READ_SPEC.md`), a QA
curator check with real misreads (`curator_check_2026-10-05.md`), and a parse
report with coverage stats (`schema/parse_report.json`). Contains the hardest
shapes in one package: board+CPU+RAM combos, barebones, configurator base
variants, sale-price-vs-list, out-of-stock, title-vs-description conflicts. The
engine's first job is to reproduce the human reads in batches, scored against
them. It is ONE fixture among the cells, not the whole test — the anti-overfit
rule stands.

Remaining cells: (a) clean single-item retail listing — Shopify product JSON
(`waterpanther`, `serverpartdeals`, or `fusionww` fixtures: id, title,
body_html, variants, price); (b) configured server, 8–10 components, one URL —
exactly one cell (`raw_r2_16slot_h12ssl.json` in the 512GB bundle is the
candidate); (c) Reddit multi-item FOR-SALE post — the verified
multi-line-per-post shape in `reddit_homelabsales/fixtures/sample_atom.xml`
(e.g. "4x 8TB Exos $280 / Samsung 980 Pro 2TB $110" in ONE post =
decomposition; the `[W]` wanted-post in the same file = quarantine/skip, never
an ask); (d) liquidation/GovDeals lot with manifest — `liquidation_com` triple
(listing card + manifest + auction detail) or the GovDeals 64×32GB DIMM lot
(`govdeals/fixtures/*.json`, asset + live bidbox); (e) lot-total vs per-unit
price ambiguity; (f) out-of-scope consumer item (quarantine path); (g)
cost-basis record (internal purchase, not a market ask).

### 5.4 Shape census (verified on disk — ambition check)

Honest accounting of how many genuinely distinct structural shapes the corpus
holds for extraction work. In-repo fixtures are FIRST-ROW shapes only
(one sample each), and that is the gap to mind:

| # | Shape | Witness (exact path) | Status |
|---|-------|----------------------|--------|
| 1 | Shopify-style product catalog JSON (id/title/body_html/variants/price) | `TechdealsHandoff/scripts/ingest/{waterpanther,serverpartdeals,fusionww}/fixtures/*.json` | 3 first-rows |
| 2 | Retailer catalog HTML (product grid rows) | `TechdealsHandoff/scripts/ingest/central_computers/fixtures/all_products_p1_96.html` (2.6 MB), `disctech/fixtures/ssd_listing_p1.html`, `diskprices/fixtures/diskprices_sample.html` | 3 first-pages |
| 3 | Single-product HTML page | `TechdealsHandoff/scripts/ingest/goharddrive/fixtures/products/*.html`, `serversupply/fixtures/hard_drives_sample.html`, `serverorbit/fixtures/sample_listing.html` | ~5 pages |
| 4 | Reddit Atom feed, multi-line [FS] posts + [W] wanted posts | `TechdealsHandoff/scripts/ingest/reddit_homelabsales/fixtures/sample_atom.xml` (3 entries inspected: two multi-line FS posts, one W post) | REAL multi-item shape |
| 5 | GovDeals typed API JSON (asset description + separate live bidbox: currentBid, bidCount, all_in_estimate_usd) | `TechdealsHandoff/scripts/ingest/govdeals/fixtures/asset_30467_94.json`, `bidbox_30467_94.json` (64×32GB DIMM lot, watched live) | REAL auction time-series shape |
| 6 | Liquidation.com triple (listing card HTML + manifest HTML + auction detail HTML) | `TechdealsHandoff/scripts/ingest/liquidation_com/fixtures/*_21256289.html` | REAL lot+manifest shape |
| 7 | eBay Bright Data row captures (162-column structured rows, used servers) | `Downloads/fresh-512gb-server-discovery-2026-09-13.zip:raw_source/*.json` (14 captures, 6–12 MB each, incl. H12SSL/ROMED8/S8030 16-slot + DL325/H11SSL 8-slot server configs, DIMM-slot facts doc, provenance CSV) | REAL configured-server shape, deep |
| 8 | RackRat typed listing JSON (40-field servers: cpu/ram/storage/psu objects, pricing, condition, firstFound/lastSeen) + Meilisearch re-pull of ~20k live servers | `/home/coldaine/big-racks/web/public/data/snapshot.json` (~3k, 5 MB); `pipeline/rackrat_pipeline/client.py` documents the pull | REAL server-listing shape at scale |
| 9 | Google SERP rows (brand/model/spec/retailer/price/in_stock/scraped_at) | `research/ssd-pricing-brightdata/ssd_prices_export*.csv` (26 + 215 rows) | parsed-table shape |
| 10 | Curated analysis CSVs (server comps, time series) | `research/gpu-v100-sxm2-pricing/*.csv` (8×V100 servers, price time series), `data/triage/large_psu_market_scan_2026-06-24.csv` (24 rows) | reference data, not extraction input |
| 11 | Third-party opinion list (PSU tier list, 22k rows) | `research/reference_data/spl_psu_tier_list/*.csv` (5.6 MB) | JUDGMENT data — never a posting; attaches to products |
| 12 | Semantic-case micro-captions (single-fact text probes for extraction assertions) | PR #222 `collection-workbench/corpus_ingest/fixtures/semantic_cases.json` + `purchase_examples.jsonl` | extraction unit tests |

Gaps stated plainly: NO eBay raw HTML anywhere (blocked by CAPTCHA; Bright Data
row captures substitute). NO sold/completed-transaction records in the bundle
(bundle README: "Every price in this package is an active asking price"). NO
Slickdeals-thread or forum-discussion shape beyond the RSS sample. The corpus is
strong on listing STRUCTURES but thin on price TIME SERIES outside GovDeals'
bidbox and the V100 CSV — the engine must still prove temporal handling from
shapes 5 + 8's firstFound/lastSeen.

## 6. Acceptance contract (what workers optimize toward and how they stay on track)

Authority note: the product North Star is `TechdealsHandoff/docs/NORTH_STAR.md`
(owner-authored, living; that repo's AGENTS.md forbids inventing a second review
contract). This section is subordinate to it — the v2 acceptance contract: the
target the schema and ingestion work is scored against, nothing more.

The single target that keeps schema and ingestion work from drifting. Every
design choice is scored against it.

### The target query set

The system exists to answer THESE questions — nothing else justifies complexity:

1. **"Cheapest N units of spec S available right now"** — e.g. cheapest 32GB DDR4
   RDIMMs, cheapest 20TB SATA, cheapest 512GB-configured EPYC server. Requires:
   decomposition + per-unit or bound prices + identity + live availability.
2. **"What did this cost over time"** — price history per item/spec: asks, bids,
   solds as separate series. Requires: append-only observations, price-kind
   separation.
3. **"What is this lot actually worth"** — decompose a multi-item posting, price
   each line against (1), sum, compare to the lot ask. Requires: line hierarchy +
   honest price basis; bound_only lines are reported as bounds, never silently
   allocated.
4. **"What did we miss"** — every capture accounted for: quarantined items
   visible in counts, wanted-posts excluded with reason, parse failures surfaced
   with their payload intact for re-extraction. Requires: provenance + quarantine
   as first-class states, not silent drops.

If a schema construct does not serve one of these four, it does not get built.
If an ingestion step cannot show which query it feeds, it does not get built.

### The two numbers

- **Coverage**: fraction of ingested captures that reach queryable state
  (posted → lines → priced → resolved-or-explicitly-unresolved). Target: every
  fixture cell at 100%, measured by the acceptance checks in §3. Drops and
  quarantines count as long as they are VISIBLE with reasons.
- **Trust**: fraction of query answers whose underlying rows are correctly
  decomposed, priced, and kinded. Target: zero fabricated unit prices, zero
  kind conflations in the fixture set. This is enforced by spot-checking the
  acceptance queries against the raw payloads, not by a framework.

### Guardrails (how drift gets caught)

- **Schema additions need a query**: any new table/column must name which of the
  four target queries it serves, or it is rejected in review.
- **No stored derivations**: values computable from facts live in views
  (carried over from v1's ADR 0001). A stored column that duplicates a
  computation is a defect.
- **No silent allocation**: any code path that divides a lot price across lines
  must write `price_basis = homogeneous_division` or `allocated` on those rows;
  anything else is a defect.
- **Unresolved is visible**: any read path that filters out unresolved postings
  by default is a defect.
- **Batch discipline**: any LLM call path that processes one listing per call is
  a defect — batching is a requirement, not an optimization (owner's words:
  "DONT FRICKING DO ONE AT A TIME").
- **Review against the four queries**: every mission's review checks the diff
  against the target query set before code health.

## 7. Environment & Credentials

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

## 8. Owner's Verbatim Words (intent — do not paraphrase away)

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

## 9. Process Rules

- **Domain modeling is active**: root `GLOSSARY.md` holds canonical terms only
  (zero implementation details); `docs/adr/NNNN-*.md` records a decision only when
  it is hard to reverse, surprising without context, AND the result of a real
  trade-off. Formats: `/home/coldaine/.agents/skills/domain-modeling/`.
- **Tower mode**: the control tower plans missions with disjoint scopes, spawns
  workers into git worktrees, routes reviews, and merges. Mission briefings carry
  this document plus the owner's verbatim quotes relevant to the mission.
- Old-repo process constraints (PR templates, docs-coupling rules) do NOT apply
  here; this repo starts clean.
