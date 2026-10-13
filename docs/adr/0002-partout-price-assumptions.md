# Part-out prices use exact keys and one DDR4 rate

Status: accepted (records the rules in `schema/020_views.sql` as of 2026-10-13)

`v_partout` publishes two numbers for a sale group and keeps them apart.
`exact_value` is stated quantity times the cheapest standalone ask with the
same `product_key`. `ram_rate_value` is stated DDR4 gigabytes times the
cheapest standalone DDR4 dollars-per-gigabyte. The rate is not added into the
exact sum. A line with neither stays unpriced. These rules are calculation
assumptions. They change a published price and which listings are grouped.

## Rules that are in force

1. **Identity is an exact key, not a nearby spec.** `engine/resolve.py`
   `product_identity` builds one string. A drive key is kind, the first
   interface word, and the stated capacity in gigabytes
   (`drive:hdd:sas:1200gb`). A 1.6TB SAS drive does not join a 1.2TB SAS
   drive. A CPU key is the model slug (`cpu:epyc-7h12`). A different model
   does not stand in.

2. **Only a one-line listing may set a comparable.** `member_line_count` must
   be null or 1. A 1.2TB drive that appears only inside another server does
   not price this server's 1.2TB line.

3. **The published exact price is the minimum ask on that key.** There is no
   median, no percentile, and no count gate. One comparable is enough.
   `comps` is reported and then ignored.

4. **Out-of-stock asks are included.** Neither aggregate filters
   `availability_state`. `exact_refs_in_stock` is false when any exact
   comparable is unavailable. On the loaded R7515 (ask $4,599, label matching
   `EPYC 7H12, 128GB`) the exact $1,152 is two 1.2TB SAS drives at $576, and
   those asks are unavailable. This contradicts the comments on
   `v_cheapest_available`, `v_product_reference_price`, and `v_lot_worth`,
   which say the comparable is the cheapest currently available.

5. **Currency is not filtered.** A non-USD amount with the same key can win
   the minimum.

6. **DDR4 gigabytes are one pool, and only for the rate.** Any standalone
   DDR4 module whose `ram_dimm_gb` parses as a positive number can set
   `v_ddr4_gb_rate`. Rank, speed, and RDIMM versus LRDIMM are ignored. The
   rate is `min(unit_price / ram_dimm_gb)`. One module is enough. The loaded
   rate is $2.3594/GB from one 32GB module, which prices the R7515's stated
   128GB at $302. That $302 is not part of the $1,152.

7. **A line may carry both figures.** The rollup counts a line as exact when
   `exact_value` is present and as rate-only only when the rate is present
   and the exact value is absent. Both can still be non-null on the same line.

8. **There is no spread gate.** No percentile band is computed. An outlier ask
   is the price.

## What was rejected for this view

Family correlation is not implemented. A later estimate that pools nearby
capacities (dollars per terabyte across 1.2TB and 1.6TB) needs its own rule:
a minimum count and a spread test, recorded before it is allowed to publish.
Until that exists, a family with no exact key stays blank.

Whole-box scoring (dollars per PassMark, per gigabyte, per terabyte) is
RackRat's score in `big-racks` and is not this view. `v_partout` does not
call a server cheap because its CPU and RAM were stated.

## What is given up

Most configured servers stay mostly unpriced. Of the loaded groups with 8 or
more lines, none had `lines_unpriced = 0`. The R7515 leaves 7 of 9 lines
blank (chassis, CPU, RAID card, power supplies, license, network card,
bezel). That gap is the result of rules 1 and 2, not a missing join.

## Worked example (loaded schema `v2`, 2026-10-13)

| Piece | Amount | Rule |
|---|---|---|
| Ask | $4,599 | latest non-superseded ask on the sale group |
| Exact parts | $1,152 | rule 3 and rule 4: 2 × $576, unavailable |
| DDR4 rate | $302 | rule 6: 128 × $2.3594, one module |
| Unpriced lines | 7 of 9 | rules 1 and 2 |
| Ask minus exact | $3,447 | rate excluded |
