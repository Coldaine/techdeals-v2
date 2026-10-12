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
