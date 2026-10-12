# schema/ — TechDeals v2 posting-first schema

Implements BRIEF.md §4 (settled design) for the four §6 target queries:

| Query | View |
|-------|------|
| Q1 cheapest N units of spec S available right now | `v_cheapest_available`, `v_category_prices` |
| Q2 what did this cost over time | `v_price_history` |
| Q3 what is this lot actually worth | `v_lot_worth` (+ `v_product_reference_price`) |
| Q4 what did we miss (quarantined/accounting) | `v_accounting` |

Every table, column, and view names the target query it serves in a SQL
`COMMENT`. Constructs serving none of the four were not built.

## Files (apply in order)

1. `000_functions.sql` — `uuidv7` resolution (PG18+ built-in, public fallback
   for older servers) and the `reject_mutation()` trigger body.
2. `010_tables.sql` — all tables, CHECK constraints, indexes, append-only
   reject-mutation triggers (UPDATE/DELETE/TRUNCATE), and insert guards
   (nesting integrity, sale-group membership caps, observation subject ↔ posting).
3. `020_views.sql` — the four target-query views plus helpers.
4. `smoke_test.sql` — self-contained checks inside one ROLLBACK transaction.

Conventions (BRIEF §4): uuidv7 PKs, timestamptz everywhere, text + CHECK (no
enum types), append-only ledgers with corrections via `superseded_by`, derived
values computed in views only.

## Neon branch

- Project: `winter-brook-99288103` (scratch `techdeals-v2` project)
- Branch name: **`schema-mission`** — ID `br-plain-band-b4k69ht8`
  (endpoint `ep-divine-darkness-b4gnt2l9`, off the project default branch)
- Server: PostgreSQL 18.6, so `pg_catalog.uuidv7()` is the built-in used by all
  PK defaults; the fallback in `000_functions.sql` never fires here.
- Database state after build: schema only (smoke test and view probe both run
  in rolled-back transactions — no data rows remain).

## Rebuild steps

Connection strings are secrets: capture into a variable, never print.

```sh
NEON=/home/coldaine/.local/share/mise/shims/neon
DB_URL=$("$NEON" connection-string schema-mission --project-id winter-brook-99288103 | head -1)
psql "$DB_URL" -v ON_ERROR_STOP=1 -f schema/000_functions.sql
psql "$DB_URL" -v ON_ERROR_STOP=1 -f schema/010_tables.sql
psql "$DB_URL" -v ON_ERROR_STOP=1 -f schema/020_views.sql
psql "$DB_URL" -v ON_ERROR_STOP=1 -f schema/smoke_test.sql   # expect NOTICE 'smoke: all checks passed'
```

To rebuild from scratch on this branch, first
`neon branches reset schema-mission ...` or drop/recreate the branch, then run
the four psql commands above.

## Verification record (2026-10-12)

- All four files applied clean from scratch on `schema-mission`: no errors.
- `smoke_test.sql`: PASS — tables/views exist; `uuidv7()` version nibble = 7,
  variant 10xx; `UPDATE` and `DELETE` on `postings` and `price_observations`
  raise `append-only: ...` (reject-mutation triggers fire); cross-posting
  observation rejected by subject guard; `sale_group_terms` insert with
  `line_quantity` over `stated_quantity` rejected. Final `ROLLBACK`.
- Functional probe (ad-hoc, also rolled back): a 3-line posting (SSD line,
  64×32GB DIMM lot with a nested component, sale group) verified all four
  views end-to-end —
  `v_cheapest_available` returns the resolved/available SSD line at
  unit_price 110; `v_price_history` separates ask kinds/bases and derives
  unit price in the view (640/64 = 10); `v_lot_worth` shows the lot ask with
  `valuation_incomplete = true` for its unresolved line (no silent
  allocation); `v_accounting` reports the posting at `reach_state =
  priced_unresolved` with nested line counts.
