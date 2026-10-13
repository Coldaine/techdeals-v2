# Slice 3 report — Generality + full corpus

**Date:** 2026-10-12. **Committed engine HEAD scored:** `2f70120` (prompt `batch-v1`,
prompt byte-identical across every call in this slice — zero prompt edits).
**Neon branch:** `slice3-full` (`br-muddy-moon-b4mc5fyt`, endpoint `ep-soft-dawn-b43untz8`),
built clean from the committed `schema/{000,010,020}.sql`; `smoke_test.sql` NOTICE
`smoke: all checks passed`. Model throughout: `deepseek/deepseek-v4-flash-0731`
via OpenRouter, temperature 0, structured JSON-schema output, batched
(MIN_BATCH_SIZE = 2 floor respected; 0 one-listing-per-call).

---

## 1. Full fixture-zero corpus (all 376 EPYC 1P eBay captures)

The **unchanged** committed engine (`extract.py` at `2f70120`, prompt `batch-v1`,
parser version `slice3-full-v1`) ran all 376 captures in 15 batched calls
(14 × 25 + 1 × 26), one call per batch:

- **Outcome:** 351 scored results — 350 extracted, 1 quarantined (`dead_page`,
  `127220408839`, the known 404 capture), **25 parse_failed** (all one failure
  mode, see §5 GF-1), every one a visible `quarantine_events` row.
- **DB state on `slice3-full`:** postings 376 (distinct offer_keys), extractions
  376, lines 1890, sale_groups 571, price_observations 571 (all ask),
  availability_observations 571, quarantine_events 26.

### Scores vs `servers_read_v2.csv` (engine/out/scores_slice3_full376_viewmap.md)

| field | applicable | hit | miss | hit rate |
|---|---|---|---|---|
| cpu_model | 276 | 274 | 2 | **99%** |
| ram_total_gb | 151 | 140 | 11 | **93%** |
| price_usd | 339 | 318 | 21 | **94%** |
| chassis_model | 152 | 139 | 13 | **91%** |
| listing_status | 350 | 345 | 5 | **99%** |

Scorer change (only file-level change besides adapters): `score_pilot.py` now
takes `--ram-view-map` — a `{item_id: ram_total_gb}` map **exported from the
committed `v_line_ram` view** (deterministic stated-factor aggregation, g0 = the
group whose `sale_groups.position = 0`, matching what `predicted()` reads). The
view's answer wins when present; the engine's `ram_total_gb` attribute is the
fallback. The 5 scored fields are unchanged. Export SQL is recorded in
`engine/out/ram_view_map_slice3.json` provenance notes (below). Without the view
map the committed scorer reads 85% on ram_total_gb (attribute-only) — the view
closes the pilot's three known aggregation misses and more.

### Miss classification (every miss traced, not excused)

**ram_total_gb (11 misses):**
- 7 × Dell "Build Your Own Server" R6515/R7515 configurator captures
  (`2564…`, `2666…`) where the RAM is genuinely not stated in the payload —
  the human reads carry a configured value the raw page does not. Engine=NULL
  (correct never-guess); view=NULL. Not reachable from the payload.
- `327384765001` R6515 384GB — the capture literally states **8×32GB + 8×16GB
  mixed DIMMs**; human=384 (sum over both), view=256 (it computes one line's
  factors; the other DIMM line has its count but the view's per-line rule does
  not sum across sibling lines of one group). Engine attribute=128 (first line's
  product). Honest partial coverage; would need a v_line_ram group-level sum.
- `377236783982/4298/5489` — the human read the FINAL configured build; the
  engine priced the base group (g0, 16GB/32GB). The extraction decomposed all
  groups correctly; the scorer reads g0. A scorer fix (pick the group whose
  stated RAM matches the title) is a scoring-convention question, not an
  extraction defect.

**price_usd (21 misses):**
- **17 sale-vs-list**: raw captures carry `price = $X` (list) and
  `sale_price = $Y` (current); the engine correctly stored the SALE price as
  the ask (description-beats-display semantics), while the human read recorded
  the list price. Engine semantics confirmed correct on raw evidence (e.g.
  `316777084170` price=$6,756.98 sale_price=$5,069.00, engine=5069).
- **4 configurator variant groups**: `128071439116`, `226694303131`,
  `226695636383`, `226703188936` — the human priced a specific configuration;
  the engine's g0 is the base variant and the human's exact amount appears in
  another group of the same extraction. Decomposition preserved the value;
  the scorer reads the wrong group for CTO listings.

**chassis_model (13 misses):** 7 × Dell 10-bay CTO ("R6515 10 Bay" as chassis
string vs human "PowerEdge R6515" — seller's own label), 1 × "G10 Plus 8B"
vs "Gen10 Plus" (known normalization near-miss from the pilot), 2 × vendor-model
mixups (`267696398195` DL335/DL325 — the model echoed the sibling product,
a real misread), 2 × DL325 Gen10 vs Gen10 Plus (variant ambiguity), plus 2 NULLs
where the human merged "Gen10 / Gen10 Plus v2".

**cpu_model (2 misses):** `256421652115` (CPU not in payload) and `298715493398`
(title "7402P/7313P", engine chose 7313P, human chose 7402P — title-vs-desc
conflict the model resolved the other way).

**listing_status (5 misses):** all 5 are raw `availability='out_of_stock'`
captures the engine marked unavailable, while the human read them live
(`available_count` still ≥ 1 in the same capture — the capture itself is
self-contradictory; the engine believed the availability field, the human
believed the counter). 6 such captures exist; the engine matched the human on 1.

**Quarantined cells:** the 1 dead-page capture accounts for 4 human-read cells
(cpu/ram/price/chassis on `127220408839`) that no payload can reach — unchanged
from the pilot.

---

## 2. Cell (a) — clean single-item retail (Shopify JSON)

Witnesses: fusionww `sample_products.json`, serverpartdeals +
waterpanther `collections_all_p1.json` (per `corpus/manifest.json`).

- **Adapter (new file `engine/adapters/shopify_catalog.py`):** the committed
  packer condenses the collection wrappers to `{}` (measured dry-run, recorded
  as GF-3). The thin adapter splits each wrapper into per-product captures
  projected ONLY onto the packer's existing synonyms — no engine/prompt edits.
  Staged: 259 captures (3 + 6 + 250) under `corpus/cell-a-shopify/captures/`,
  checksums in `corpus/cell_a_c_SHA256SUMS`, manifest staged.
- **Run:** parser version `slice3-cell-a`, 11 batched calls, **234 extracted /
  25 parse_failed** (all 25 one failure mode, GF-1; quarantined visibly).
- **Acceptance (`corpus/cell-a-shopify/acceptance.sql`)** — all **7 PASS**:
  1. capture completeness: **259/259** postings with provenance + checksum.
  2. line counts: **234/234** extracted postings = 1 group / 1 top-level line
     (25 quarantined parse_failed visible, not force-fitted).
  3. price honesty: **234/234** asks, all `explicit_unit`, zero bounds, zero
     unpriced, zero non-explicit bases — no lot ambiguity invented on clean retail.
  4. stated prices land: fusionww 75.50 / 89.99 / 219.00 exact.
  5. quarantine honesty: 25 events, 100% parse_failed, zero false-positive
     scope quarantines.
  6. kind separation: 234 observations, 234 asks, **0** non-ask contamination
     (listPrice never became an observation).
  7. bound_only: **0** rows (nothing ambiguous about a stated per-product price).

## 3. Cells (c) + (f) — Reddit multi-item FS posts + [W] wanted post

Witness: reddit_homelabsales `sample_atom.xml` (2 multi-line FS posts + 1 [W]).

- **Adapter (new file `engine/adapters/atom.py`):** Atom → listing-JSON captures,
  verbatim title/content/url/timestamp, JSON-only engine boundary. Staged:
  3 captures in `corpus/cell-c-reddit/captures/` (checksums in the same SUMS
  file), manifest staged. Run twice (parser versions `slice3-cell-c`, replay
  `slice3-cell-c-retry`) to prove replay safety on this shape too.
- **Acceptance (`corpus/cell-c-reddit/acceptance.sql`)** — all **9 PASS**:
  1. capture completeness: 3/3 postings.
  2. `t3_abc123` decomposition: **2 top-level lines** ("Seagate Exos 8TB SATA
     HDD" + "Samsung 980 Pro 2TB NVMe SSD").
  3. `t3_def456` decomposition: **2 lines** ("WD Gold 20TB SATA HDD" + "HGST
     12TB SAS HDD").
  4. price honesty: exactly 1 price observation (`explicit_unit`, qty 1);
     **no silent division** of any lot price across lines.
  5. stated amount lands exact: 110.00.
  6. quantity_conflict visibility: **6 quarantines** (3 groups × 2 runs), each
     detail carrying the stated contradiction.
  7. [W] wanted post: quarantined with reason `wanted_post` ("User is looking
     to buy drives, not selling inventory"), **zero** lines / groups / prices.
  8. replay safety: 3 postings (no dupes), 6 extractions appended.
  9. `v_accounting` agrees: wanted_post row quarantined; FS rows visible with
     their priced-group counts (1 group-priced offer priced, others visible).

**What the unchanged engine got right and wrong on this shape** (GF-2): it
decomposed both FS posts correctly and never divided a lot total — but it
labeled every lot price ("$280 for the lot of 4") `explicit_unit, quantity_units=1`,
which the engine's own S6 cross-check then caught and dropped as
`quantity_conflict` (visible quarantine). The honest outcome — nothing wrong
stored — is by design; the informative outcome would be `homogeneous_division`,
which the prompt already documents but the model did not select on this shape.
Recorded as a generality finding, **not** silently absorbed.

---

## 4. Batch ledger (engine/out/batch_ledger.jsonl)

| run | listings | batch calls | cost |
|---|---|---|---|
| fixture-zero full 376 | 376 | 15 | **$0.213060** |
| cell (a) Shopify 259 | 259 | 11 | **$0.058294** |
| cell (c/f) Reddit 3 (run 1) | 3 | 1 | $0.000749 |
| cell (c/f) Reddit 3 (retry) | 3 | 1 | $0.000743 |
| **slice-3 API total** | **641** | **28** | **$0.272846** |

Token totals (batched calls only): 897,961 input / 519,434 output. Per-listing:
**$0.000426 ≈ $0.43 per 1,000 listings** (fixture-zero alone: $0.213060 / 376 =
$0.000567). Zero one-listing-per-call; batch sizes 25/3; the floor held on
every call including salvage retries.

Every batch logged model + prompt version + cost in `extraction_batches`
(mirrored on the branch) and full detail in the ledger file.

## 5. Generality findings

**GF-1 (engine defect to record, not absorbed): `line without label` kills
whole salvage batches.** 25 of 376 fixture-zero and 25 of 259 cell-a listings
failed validation with `invalid result: line without label` — the model emitted
a line with an empty label, `validate_result` rejects the whole listing, the
targeted salvage retry (also batched, floor respected) re-asked **the same
unchanged payload** and reproduced the same failure, so the listings went to
`parse_failed` quarantine. The quarantine path worked (visible, payload
preserved), but a single-line-repair fallback never got a chance. Engine fix
suggestion (out of scope here): salvage could retry per-listing with a
"re-emit just this listing" prompt instead of the identical batch. NOT fixed in
this slice — engine is committed-read-only.

**GF-2 (shape, visible): Reddit lot pricing** — see §3. The unchanged prompt's
lot-price vocabulary (`homogeneous_division`) was not selected by the model on
the Reddit shape; the engine's S6 cross-check caught it and quarantined with
full detail. No prompt change made; logged as the generality finding it is.

**GF-3 (adapter gap, now closed for catalog wrappers):** the packer sees only
top-level synonyms; catalog wrappers (`{"products": [...]}`) condense to `{}`.
Thin per-shape adapters are the fix (one per shape, JSON-only boundary kept):
`engine/adapters/shopify_catalog.py` (cell a) and `engine/adapters/atom.py`
(cells c/f) are the two this slice needed. **HTML shapes (cells d/e and the
retailer-catalog/liquidation HTML of BRIEF 5.4 shapes 2/3/6) remain OUT OF
SCOPE — no adapter was built for them, noted not silently absorbed.**

**GF-4 (score-side, closed): the view's deterministic ram aggregation was NOT
wired into the scorer** until this slice — the report's ram_total_gb target
(≥ ~97%) required exporting `v_line_ram` (g0) and preferring it. Scorer now
does (attribute fallback). With the view map: 93% (was 85% attribute-only).
The remaining 11 misses: 7 payload-empty configurator captures, 1 mixed-DIMM
sum (view rule limitation), 3 scorer-group-selection questions.

**Explicitly: no prompt change was made anywhere in this slice.** `batch-v1`
stayed byte-identical across all 28 batched calls.

## 6. Verdict — anti-overfit

**The eBay-shaped engine generalized — with one honest caveat per shape.**

- Same prompt, zero prompt edits, across 641 listings from three structurally
  different sources (eBay raw item JSON, Shopify catalog JSON, Reddit Atom
  posts): cpu_model 99%, price_usd 94%, listing_status 99% on the hardest
  single-source corpus, and the Shopify cell passed every price/kind
  clean-retail assertion with **0** fabricated or ambiguous prices, **0** kind
  conflations.
- The one thing the engine genuinely did not solve is lot-price labeling on
  free-text multi-item posts (GF-2) — caught and quarantined by the engine's
  own cross-check rather than mis-stored, which is exactly the failure mode
  the schema is built to make visible. The fix is a prompt-policy matter that
  must go through the review process, not this slice.
- The adapter gap (GF-3) is structural: ingestion shapes need thin per-shape
  adapters; extraction itself is shape-generic.

**Not overfit** on the evidence: nothing in `batch-v1` is eBay-specific; the
same prompt handles retail catalogs and forum posts with perfect kind
separation and honest quarantine. The pilot's warning that engine performance
on fixture-zero alone is not acceptance now has its counterpart: engine
performance across cells (a) and (c/f) holds with the same prompt unchanged.

## 7. Q4 hygiene on `slice3-full`

- `v_stale_quarantine`: **0 rows** — the two cell-c runs released their own
  earlier quantity_conflict events through the engine's committed release path
  (2 `released` events in the DB), and the 50 `parse_failed` quarantines have
  no later successful extraction to release (correctly still visible).
- The committed release SQL (`INSERT … SELECT … FROM v_stale_quarantine`) was
  executed against the branch: 0 rows appended (nothing stale to release).

## 8. Reproduction

```sh
NEON=/home/coldaine/.local/share/mise/shims/neon
export TDV2_DSN=$($NEON connection-string slice3-full --project-id winter-brook-99288103 | tail -1)
psql "$TDV2_DSN" -f schema/000_functions.sql -f schema/010_tables.sql -f schema/020_views.sql
doppler run --project ai-automation --config dev -- python3 engine/extract.py \
  --raw-dir corpus/fixture-zero/raw --batch-size 25 --parser-version slice3-full-v1
psql "$TDV2_DSN" -qAt -f <(cat /tmp/g0_ram3.sql)   # view map export (recorded above)
python3 engine/score_pilot.py --results engine/out/results_slice3_full376.json \
  --humans corpus/fixture-zero/servers_read_v2.csv --ram-view-map engine/out/ram_view_map_slice3.json
psql "$TDV2_DSN" -f corpus/cell-a-shopify/acceptance.sql
psql "$TDV2_DSN" -f corpus/cell-c-reddit/acceptance.sql
```

Scorecards: `engine/out/scores_slice3_full376.md` (attribute-only, for the record),
`engine/out/scores_slice3_full376_viewmap.md` (headline). Raw results:
`engine/out/results_slice3_{full376,cell_a,cell_c,cell_c2}.json`.
