# TECHDEALS v2 STATUS/PLAN

## Purpose

This document tracks progress toward the v2 goal: catch every scrape, parse it into
items with honest prices, and serve it for analysis.

See `BRIEF.md` for:
- **§3** the acceptance criteria
- **§5** the corpus and fixture cells
- **§6** the target queries

## The loop

The pipeline is:

1. Load fixture captures.
2. Parse each capture into structured line items.
3. Persist to the database.
4. Answer the four target queries from plain SQL views.

Until now, nothing in the repo wrote a single `postings`/`lines` row, so every
acceptance view was empty by construction. That loop now closes.

## Table (where we are)

| Area | Before | Now |
|------|--------|-----|
| Fixtures in-repo | empty (laptop-only paths) | **14 real captures** across 5 sources |
| Migration / DB run | never executed anywhere | **applied and verified** on a real Postgres |
| Capture → LLM text | missing entirely | `parser/prepare.py` (html/json/atom) |
| Persistence | missing entirely | `db/persistence.py` (postings/lines/groups/observations) |
| CLI `ingest`/`extract` | stubs | implemented; `pipeline`, `query`, `acceptance`, `status` added |
| Batched LLM call path | scaffold | unchanged + verified in one call per batch |
| Tests | 15 unit | 28 (incl. DB integration + acceptance invariants) |
| Lint | 11 ruff errors | clean |

## Acceptance criteria (§3)

| # | Criterion | Status |
|---|-----------|--------|
| AC1 | Total capture with provenance | **verified** — 14/14 raw_captures, 5 sources |
| AC2 | Decomposition | **verified** — configured server = 8 lines; multi-item posts 12–13 |
| AC3 | No fabricated prices | **verified** — 38 `explicit_unit`, 8 `bound_only`, 0 hidden division |
| AC3b | No line price without a sale group | **verified** — guardrail query returns 0 |
| AC4 | Time series | **verified** — ask + bid observations, indexed by `observed_at` |
| AC5 | Lazy identity | **verified** — all 12 extracted postings visible with 0 resolutions |
| AC6 | Batch economics | **verified** — `extraction_batches` records model/prompt/cost per call |
| AC7 | Dynamic categories | **verified** — unknown categories inserted as data |
| AC8 | Replay safety | **verified** — same parser = no-op; new version = new posting |
| AC9 | Honest quarantine | **verified** — wanted-post + consumer item quarantined with reasons |

## Bugs found and fixed

- `uuidv7()` never set the version nibble and set the variant to `11`, so it produced
  version **15** and non-RFC UUIDs. Rewritten; now returns version 7 and sorts by time.
- Loaders hardcoded `/home/coldaine/...`, so ingestion could not run anywhere but one
  laptop. Now repo-relative, overridable with `TECHDEALS_FIXTURES_DIR`.
- Parse breakage was filed as `quarantined`; it now lands as `failed`, keeping
  "deliberately set aside" and "we broke" separately countable.

## How to verify locally

Requires no credentials.

```bash
./scripts/local_postgres.sh up
export NEON_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/techdeals
uv run techdeals migrate
uv run techdeals pipeline --provider offline
uv run techdeals acceptance
```

`--provider offline` replays recorded model responses in
`fixtures/expected/extractions.json` through the same persistence path, so the SQL
and views are exercised deterministically. `--provider llm` calls the real batched
engine and needs a configured endpoint.

## What remains

1. **Real LLM extraction quality.** `--provider offline` proves plumbing, not model
   accuracy. Run `--provider llm` against a free endpoint and score against the
   recorded reads.
2. **On-disk fixtures.** The committed set stands in for the much larger laptop
   corpus. Broaden coverage and commit more cells.
3. **Neon.** Migrations have only run on a local Postgres. Point
   `NEON_DATABASE_URL` at the Neon scratch branch and re-run.
4. **Fixture zero (EPYC).** The anti-overfit proof. Needs the `data/inbox` package,
   which is unreachable from this workspace.
5. **Resolutions.** The table exists but nothing populates it yet
   (`resolutions` = 0).
6. **Old-corpus migration.** Intentionally out of scope until 1–4 are done.
