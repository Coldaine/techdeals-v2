# TechDeals v2 — batched LLM extraction engine

Reads raw capture JSONs, packs dozens of listings into ONE LLM call (never one
listing per call — that is a defect, not an optimization), validates the
per-listing results, and writes them into the posting-first schema
(`schema/010_tables.sql`) with full provenance and honest quarantine.

Shape-generic by construction: the capture packer maps common listing-field
synonyms (title / price / description / spec table / variants) and keeps small
unknown scalars under a byte budget, so it works on any capture that carries
title/price/specs — not just eBay servers. No vendor-specific prompt hacks
(the anti-overfit rule: fixture-zero is one cell).

## How to run

```bash
# 0. Branch + schema (once per branch)
neon branches create --name engine-pilot --project-id winter-brook-99288103
psql "$DSN" -f schema/000_functions.sql -f schema/010_tables.sql -f schema/020_views.sql

# 1. Dry run — check the condensed captures without an LLM call or DB writes
python3 engine/extract.py --raw-dir corpus/fixture-zero/raw --limit 5 --dry-run

# 2. Real run — key from Doppler, DSN from Neon CLI (never committed anywhere)
export TDV2_DSN=$(neon connection-string engine-pilot --project-id winter-brook-99288103 | tail -1)
doppler run --project ai-automation --config dev -- \
  python3 engine/extract.py --raw-dir corpus/fixture-zero/raw \
  --limit 20 --batch-size 20 --parser-version engine-v1

# 3. Replay safety check — same 5 listings, bumped parser version
doppler run --project ai-automation --config dev -- \
  python3 engine/extract.py --raw-dir corpus/fixture-zero/raw --limit 5 \
  --batch-size 5 --parser-version engine-v2

# 4. Score against the human reads
python3 engine/score_pilot.py --results engine/out/results_*.json \
  --humans corpus/fixture-zero/servers_read_v2.csv
```

Environment: `OPENROUTER_API_KEY` (injected by doppler), `TDV2_DSN`
(the Neon branch connection string — generated at run time, never stored).
Dependencies: python3 stdlib + `psql` on PATH.

## Free-model policy for the extraction CLI

`engine/extract.py` allows only the models listed in its `MODEL_PRICES` table;
the current default is `nvidia/nemotron-3.5-lightning:free`, priced at zero.
An unlisted `--model` is rejected before loading captures or creating an API
client. This is a guard on this standalone extraction CLI, not an application-
wide restriction on other parsers or on already saved results. It controls the
model slug and recorded cost; it does not establish endpoint availability or
semantic extraction quality. The earlier paid-model pilot figures below are
historical measurements and do not validate this free model.

## What one batch does

1. **Pack** — N condensed captures (field-synonym projection, budgets below)
   into one user message: `{"listings":[{id, ...fields}...]}`. Stable ids are
   the capture's natural item id (or `idxN`), so per-listing verdicts are
   addressable across replays.
2. **Call** — one chat-completions call, temperature 0,
   `response_format: json_schema strict`. The system prompt (fixed =
   `PROMPT_VERSION`) carries the extraction policy: purchase-shape semantics
   (sale groups / lines / quantities, absorbed from PR #222's
   options-nodes-memberships), never-allocate-lot-price, null-instead-of-
   guessing, description-beats-title conflicts, untrusted-input discipline.
   The stable prefix is zero-listing-content, so provider prompt caching sees
   identical schema+policy bytes every call.
3. **Validate / salvage** — results must cover every input id. Malformed batch
   JSON goes through a salvage parser (fences / brackets / NDJSON). Missing ids
   get one targeted follow-up call with only those listings. Ids still missing
   become `quarantine_events` rows with reason `parse_failed` — never silent
   drops. Truncated output (output-token limit) splits the batch and retries.
4. **Write** — one transaction per batch: `extraction_batches` row (model,
   prompt version, cost USD, listing count), `postings` upserted on natural-key
   `offer_key = sha256(source|url|fetched_at)`, one `extractions` row per
   posting (`parser_name = llm_batch:<parser-version>`), `lines` (nested via
   `parent_line_id`), `sale_groups` + `sale_group_terms`, group-level
   `price_observations` (ask kind; basis `explicit_unit` / `homogeneous_division`
   / `bound_only` — **never** a divided lot total on a component line), group
   `availability_observations`, and `quarantine_events` for every
   quarantined / failed listing.

## Batch-size tuning notes

- Target band: **25–50 raw captures per call** (BRIEF §3.6). The binding
  constraint is output-token headroom, not listing count: rich per-listing
  results run ~400–800 output tokens each, so `max_tokens` bounds the batch.
  Default `--max-tokens 24000` ≈ safe for ~30 listings; raise it (or shrink
  the batch) if the ledger shows `truncated: true`.
- Input budget: the packer spends ≤ ~12k chars per listing (description capped
  4000, spec list 6000, each spec value 400); fixture-zero condensed to ~5.1k
  chars/listing average (measured dry-run: 20 listings ≈ 101k chars ≈ 6–7k
  input tokens). 50 listings ≈ 25–30k input tokens — trivial against a 1M-context
  model, and comfortably inside 128k-context models too.
- One malformed listing must not discard twenty good ones — the engine
  salvages per-listing instead of re-running whole batches (only missing ids
  are re-asked, cache-friendly).
- Latency is the real tax: bigger batches are fewer calls but longer calls
  (~3 min for 20 listings on deepseek-flash-tier models). For wall-clock-bound
  ingest, run batches concurrently; for cost-bound ingest, bigger is better.
- Free-tier routers sometimes ignore `response_format` — the salvage path +
  per-endpoint failure counters in the ledger make that an evidenced choice,
  not a one-time bet.

## Cost-per-listing math

`cost = (prompt_tokens × prompt_rate + completion_tokens × completion_rate) / 1e6`
per call, computed from the response `usage` and written into
`extraction_batches.cost_usd` and the ledger. Pilot model
`deepseek/deepseek-v4-flash-0731`: **$0.02 / MTok prompt, $0.64 / MTok
completion** (OpenRouter catalog, 2026-10-12). Worked example (fixture-zero
pilot, 20 listings, one call): ~9k prompt tokens (~$0.0002) + ~14k completion
tokens (~$0.009) ≈ **$0.009/batch ≈ $0.00045/listing** — about 45¢ per
thousand listings. See `engine/out/batch_ledger.jsonl` for exact measured rows.

Note: the v2 schema's `extraction_batches` has no token/latency columns yet
(model, prompt_version, cost_usd, listing_count only). The full ledger —
input/output/cached tokens, latency, retries, truncation — lives in
`engine/out/batch_ledger.jsonl` per batch row; extend the table when the
schema mission lands token columns.

## Replay safety

- Posting identity is content-addressed (source|url|fetched_at) — replaying a
  capture never invents a second posting.
- Every replay with a new `--parser-version` appends new `extractions` + `lines`
  + observations; `v_current_extractions` views read the newest pass.
- Price-observation `offer_key = sha256(posting_offer_key | "g<group_index>")` —
  position-path based, stable while the model's group ordering is stable
  (temperature 0, fixed prompt). Verify with the task-3 replay check: new
  extraction rows, zero duplicate postings, zero history mutation.
- History mutation is impossible by construction: every ledger table has a
  reject-mutation trigger (`schema/000_functions.sql`).

## Files

- `extract.py` — the engine (CLI above).
- `score_pilot.py` — scores a results file against `servers_read_v2.csv`
  (per-field hit rates, per-listing table, misses with raw titles).
- `out/batch_ledger.jsonl` — append-only batch ledger (tokens, cost, latency).
- `out/results_<run>_<ver>.json` — validated per-listing extraction results.
- `pilot_report.md` — attempt-1 verdict on fixture zero.

---

## Addendum — 2026-10-12, adversarial-review fixes (append; history above is the pre-fix record)

Corrections and fixes to the engine made by the review mission. Where the
original README or pilot report claimed something false, the claim is corrected
HERE, not rewritten above.

1. **S1 (offer-key unification) — the pilot's replay claim was partly FALSE.**
   The replay-safety section above says price-observation `offer_key` is
   position-path based; in the committed pilot code the PRICE ledger actually
   hashed the group's fresh random `uuid7` id (`sha256(pk|<gkey>)`), while
   availability hashed the position path (`sha256(pk|g<index>)`). Every run
   therefore minted new logical price offers and the two ledgers were
   unjoinable. Fixed: both ledgers now hash the stable position path
   `g<group_index>`, the schema stores that path as
   `subject_path` and trigger-enforces the derivation
   (`schema/000_functions.sql observation_offer_key_guard()`), and
   `sale_groups.position` records the group's stable index.
   Re-proven on Neon branch `fix-verify` with a two-run replay (5 listings,
   one call each): price and availability offer_keys are identical across
   runs, 5 distinct keys total, zero duplicate offers, history append-only.
2. **S3 (batch floor).** `--batch-size` is floored at 2 (`MIN_BATCH_SIZE`);
   `--batch-size 1` is rejected by the CLI. The salvage retry never sends a
   single-listing call: if fewer than 2 ids are missing, the retry call is
   padded with other listings from the batch (answers for ids already parsed
   are discarded). A run remainder smaller than the floor merges into the
   previous batch instead of making a tiny call. The ledger row records
   `salvage_batch_size`.
3. **S4 (truncation split-and-retry) — the claim above was FALSE when the
   pilot ran.** The committed code skipped salvage on truncated output;
   ledger row 3 (the 2026-10-12 11:26 truncated run) shows the result:
   24,000 output tokens, 9 `parse_failed` listings, no split retry. That run
   is honestly recorded as a truncated run with parse failures, not a
   split-and-retry success. The mechanism is NOW implemented: a truncated
   batch is split in half and each half retried recursively (sub-calls append
   their own ledger rows — `truncated_split` / `L`/`R` sub-indexes / a
   `split_retry` summary; a truncated single-listing batch fails outright).
4. **S5 (no silent quantity defaults).** Unstated counts stay NULL everywhere:
   `lines.stated_quantity`, `sale_group_terms.line_quantity`,
   `price_observations.quantity` (schema now nullable), and every line gets an
   explicit `quantity_stated` attribute (children included). An
   `explicit_unit` price with an unstated unit count is stored with quantity
   NULL and a `quantity_units not stated` basis note — the derived unit price
   is NULL (non-unit-confident), never a silent 1.0.
5. **S6 (no silent price drops).** A stated price that cannot be stored
   confidently (e.g. `homogeneous_division` without a real lot total and unit
   count) now emits a `price_ambiguous` quarantine event plus a ledger
   `engine_note` and stderr line instead of returning silently. A cheap
   cross-check flags `explicit_unit` quantity contradicting the group's own
   stated member count (single-line group with stated N, price says another
   count) as `quantity_conflict` — never silently stored. Normal multi-line
   bundles priced at quantity 1 are not flagged. The engine still never
   allocates a lot price itself (confirmed clean in review; kept that way).
6. **S7 (honest salvage flag).** `salvaged_parse` in the ledger is now true
   only when the strict JSON parse actually failed and the salvage path was
   used (the pilot code set it true on every successful parse). The salvage
   retry's own flag is folded in.
7. **S8 (transport vs parse).** Batch-call failures get a distinct quarantine
   reason: `transport_failed` (transport errors, HTTP 5xx, 429), 
   `batch_call_failed` (other call-level failures, e.g. HTTP 400), and
   `parse_failed` only for unparseable/invalid results. `quarantine_events`
   reason vocabulary updated in `schema/010_tables.sql`. The engine also
   emits a `released` quarantine event when a listing that carries a stale
   `parse_failed`/transport/batch-call quarantine parses successfully in a
   later run — see the reconciliation note in `pilot_report.md`.
8. **S9 (no silent dedupe drops).** (a) A repeated client id across input
   files is reported to stderr and the ledger (`input_dedupe_drop` row) —
   there is no posting row yet to hang a quarantine event on. (b) Replay
   observations identical to ones already written
   (`offer_key, observed_at, price_kind/state`) are skipped BEFORE insert and
   reported in a `replay_dedupe` ledger row plus stderr — the H2 unique
   indexes make the duplicate a schema-level error otherwise, and skipping is
   never silent.
9. **S10 (storage-capacity attribute keys).** The prompt's suggested
   attribute vocabulary now includes `storage_capacity_gb`, `storage_kind`,
   `storage_interface` — the drive-capacity facts that fixture cell (c)
   (Reddit multi-item posts) and GovDeals lots live on. Boundary note: the
   packer today consumes JSON captures only. The Reddit-Atom and HTML adapter
   cells do not exist yet — nothing in this mission parses Atom or HTML — so
   cells like `reddit_homelabsales` / `central_computers` are not ingestable
   end-to-end until adapters are written (explicitly out of scope here).
10. **ram_total aggregation decision.** The pilot report's proposal to let
    the prompt multiply stated factors was REJECTED. Deterministic fix only:
    `schema/020_views.sql v_line_ram` computes `ram_total_gb` from stated
    factors (own `stated_quantity × ram_dimm_gb`, or the all-children sum when
    every child states both), else NULL — BRIEF §6 "derived values in views,
    never stored", and no LLM arithmetic. `score_pilot.py` was NOT changed;
    its committed fixture numbers (86% on ram_total_gb) remain the honest
    pre-fix measurement.

Mission API spend (OpenRouter, deepseek/deepseek-v4-flash-0731, all batched,
zero one-listing-per-call): **$0.009319 total** across five 5-listing batched
calls — the final S1 replay proof pair ($0.001860 + $0.001914) plus one
earlier attempt pair ($0.001756 + $0.001948, of which one run crashed after
the LLM call and before any DB write, and one retry $0.001841) invalidated by
a mid-flight schema change (`sale_groups.position`). Ledger:
`engine/out/batch_ledger.jsonl`, rows from 12:06–12:12 UTC.
