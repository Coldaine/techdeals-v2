# schema/ — TechDeals v2 posting-first schema

Implements BRIEF.md §4 (settled design) for the four §6 target queries:

| Query | View |
|-------|------|
| Q1 cheapest N units of spec S available right now | `v_cheapest_available`, `v_category_prices`, `v_line_ram`, `v_group_ram` |
| Q2 what did this cost over time | `v_price_history` |
| Q3 what is this lot actually worth | `v_lot_worth` (+ `v_product_reference_price`), `v_partout` (+ `v_ddr4_gb_rate`) |
| Q4 what did we miss (quarantined/accounting) | `v_accounting` (+ `v_stale_quarantine`) |

Every table, column, and view names the target query it serves in a SQL
`COMMENT`. Constructs serving none of the four were not built (the one
exception found in review — `postings_payload_gin`, which served no query —
was dropped).

## Files (apply in order)

1. `000_functions.sql` — `uuidv7` resolution (PG18+ built-in, public fallback
   for older servers), `reject_mutation()` (DELETE/TRUNCATE on append-only
   tables), `supersede_only()` (the one permitted UPDATE: setting
   `superseded_by`), and `observation_offer_key_guard()` (writer-contract
   enforcement of the observation offer_key).
2. `010_tables.sql` — all tables, CHECK constraints, indexes, reject-mutation
   triggers, and insert guards.
3. `020_views.sql` — the four target-query views plus helpers.
4. `smoke_test.sql` — self-contained checks inside one ROLLBACK transaction,
   including the replay-dedupe, ordinal-shift, multi-term-split, and
   supersession cases (must-fail inserts for each).

Conventions (BRIEF §4): uuidv7 PKs, timestamptz everywhere, text + CHECK (no
enum types), append-only ledgers whose ONLY correction path is the
`superseded_by` pointer (set once, only to a strictly later row), derived
values computed in views only.

## Key invariants added by the adversarial-review fixes (2026-10-12)

- **Offer-key writer contract (H2).** `price_observations` and
  `availability_observations` carry `subject_path` (the subject's stable
  position path: `g<index>` for a group, `g<index>.<ordinal>[.<ordinal>...]`
  for a line) and their `offer_key` must equal
  `sha256(posting.offer_key || '|' || subject_path)` — enforced by trigger.
  An ordinal shift across parser versions changes the path, so it cannot
  silently alias the old offer; replays with stable structure hash identically.
- **Replay-dedupe indexes (H2).** Partial unique indexes block a second LIVE
  observation for the same `(offer_key, observed_at, price_kind)` (price) /
  `(offer_key, observed_at, state)` (availability). PARTIAL was chosen over
  FULL for price because `observed_at` is pinned to the capture's fetch time:
  a replay that CHANGES a value must be recordable, and the recordable path is
  supersession (supersede the live row → it leaves the partial index → append
  the new live row). A full index would make that correction impossible
  forever. Availability has no supersession column, so its index includes
  `state`: identical-state replays are blocked; a differing-state replay stays
  visible as evidence (the view reads the newest by id).
- **Single supersession (L5).** `UNIQUE(superseded_by) WHERE NOT NULL` on
  `price_observations`, `resolutions`, and `categories`; `supersede_only()`
  additionally requires the superseder to be a strictly later row (uuidv7
  ordering) and permits no other column to change. This is what makes the
  forward pointer actually usable under append-only rules (append the
  superseding row, then point back).
- **One membership term per (group, line) (H3).**
  `UNIQUE(sale_group_id, line_id)` on `sale_group_terms` — with the per-row
  guard against `stated_quantity`, splitting an allocation across terms
  (two 0.7s against a stated 1.0) is now impossible, and the per-row cap is
  also the aggregate cap because there is exactly one term to cap.
- **bound_only states something (M4).** CHECK: `bound_only` requires at least
  one of `bound_low` / `bound_high`.
- **Unstated quantities stay NULL (S5).** `lines.stated_quantity`,
  `sale_group_terms.line_quantity`, and `price_observations.quantity` are
  nullable; the `sale_group_terms` guard rejects a stated share for a line
  whose own count is unstated. NULL is never silently promoted to 1.
- **`sale_groups.position` (H2).** The group's zero-based position within its
  extraction pass — the stable half of the offer natural key
  (`sha256(posting natural key | '|g' || position)`), the group analogue of
  `lines.ordinal`. Not a derived value: it is part of the natural key and must
  be recorded for offer-key stability across replays. Unique per extraction.
- **`v_line_ram`** — deterministic `ram_total_gb` from stated factors only
  (own `stated_quantity × ram_dimm_gb`, or the all-children sum when every
  child states both factors); NULL otherwise. No stored derivation, no LLM
  arithmetic (ram_total decision, 2026-10-12 — prompt-bump rejected).
- **`v_stale_quarantine`** — Q4 hygiene: still-quarantined subjects whose
  posting has a LATER extraction that produced lines, with no later release
  event. Catches the stale `parse_failed` events bring-up runs leave behind.

## Neon branch

- Project: `winter-brook-99288103` (scratch `techdeals-v2` project)
- Verification branch for the fix mission: **`fix-verify`** — ID
  `br-muddy-dawn-b4np8wck` (endpoint `ep-rough-math-b4w97ahp`), off the
  project default branch. Created 2026-10-12; rebuilt clean from these files
  twice during verification (once after `sale_groups.position` landed).
- Earlier mission branches (untouched): `schema-mission`
  (`br-plain-band-b4k69ht8`), `engine-pilot` (`br-old-meadow-b4kfistc`),
  `verify-rebuild` (`br-mute-resonance-b43zmenl`).
- Server: PostgreSQL 18.6, so `pg_catalog.uuidv7()` is the built-in used by all
  PK defaults; the fallback in `000_functions.sql` never fires here.
- Database state after build: schema only (smoke test and view probes run in
  rolled-back transactions — no data rows remain). The fix-verify branch also
  holds the two-run replay evidence (see below) plus one synthetic
  `parse_failed` quarantine event inserted on purpose to exercise the
  release path — it is mission evidence, not pipeline data.

## Rebuild steps

Connection strings are secrets: capture into a variable, never print.

```sh
NEON=/home/coldaine/.local/share/mise/shims/neon
DB_URL=$("$NEON" connection-string fix-verify --project-id winter-brook-99288103 | head -1)
psql "$DB_URL" -v ON_ERROR_STOP=1 -f schema/000_functions.sql
psql "$DB_URL" -v ON_ERROR_STOP=1 -f schema/010_tables.sql
psql "$DB_URL" -v ON_ERROR_STOP=1 -f schema/020_views.sql
psql "$DB_URL" -v ON_ERROR_STOP=1 -f schema/smoke_test.sql   # expect NOTICE 'smoke: all checks passed'
```

To rebuild from scratch on this branch, `DROP SCHEMA public CASCADE; CREATE
SCHEMA public;` first (a bare `neon branches reset` to anything but the parent
is rejected by the CLI), then run the four psql commands above.

## Verification record (2026-10-12, fix mission)

- All four files applied clean from scratch on `fix-verify`: no errors.
- `smoke_test.sql`: PASS, including the new cases — wrong observation
  offer_key rejected; ordinal shift (g0.1 vs g0.2) yields distinct offer_keys;
  duplicate replay price/availability observations rejected by the dedupe
  indexes; `bound_only` without bounds rejected; single-supersession UPDATE
  path (allowed once to a later row, then rejected; non-pointer UPDATE
  rejected); second `sale_group_terms` row for the same (group, line)
  rejected (0.7 + 0.7 against stated 1.0); stated term share for an
  unstated-count line rejected; `v_line_ram` computes 8×64→512 and refuses to
  guess when one child's count is unstated; category live-name uniqueness +
  append-supersede correction.
- Batched replay proof (engine, 5 fixture-zero listings, one call per run,
  parser versions `fixv1` then `fixv2-replay` on `fix-verify`):
  postings 5 (no duplicates), extractions 10 (5+5, appended), sale_groups 10,
  price_observations **5 total = 5 distinct offer_keys** (the replay minted
  ZERO new logical offers — position-path keys for both ledgers, identical
  replays deduped by the H2 index with a loud `replay_dedupe` ledger row and
  stderr note), availability 5 = 5 keys. `v_cheapest_available` renders all 5
  group-priced offers against the CURRENT pass with their latest availability;
  `v_accounting` shows `priced_unresolved` with `priced_group_count = 1` each.
  No history mutated (reject-mutation triggers; nothing UPDATEd).
- See `engine/README.md` (addendum) and `engine/pilot_report.md` (addendum)
  for the engine-side fix record, quarantine reconciliation, and API spend.
