# Cluster data audit

Status: initial data investigation complete. No repairs applied.

## Scope and consolidation context

This audit was conducted by the owner's request: investigate actual data failures
in `TechdealsHandoff` using real data from both cluster databases (`market_live`
and `techdeals_work`), not Neon, and evaluate them **in the explicit context of
planning the eventual consolidation of both repositories (`TechdealsHandoff` and
`techdeals-v2`) into one unified TechDeals platform**.

This audit does **not** declare `techdeals-v2` complete or non-flawed. The
greenfield v2 implementation has only been exercised on ~640 static listings
(376 eBay EPYC servers, 259 Shopify drives, 3 Reddit posts, 1 GovDeals auction).
It has untested assumptions, fragile heuristic resolution, and directly equivalent
flaws in its current code. The goal of documenting these failures is to ensure
the merged destination repository avoids repeating the architectural and parsing
defects of both implementations.

Separate parallel investigations cover prices/history, classification/configurations,
and intake/retention. Findings must include query scope, denominator, persistent
row IDs, source evidence where reachable, consumer impact, and uncertainty. A
deliberately partial rolling Reddit feed is not a failure merely because its status
is partial. Missing current offers do not establish missing collection.
## Verified access and inventory

Read-only SELECT queries succeeded against both databases at `pg18-core-db.moosegoose.xyz`, as database role `techdeals`. Password supplied by Doppler `homelab/dev`; no credentials retained here. Every audit connection uses:

```text
PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=20000 -c lock_timeout=2000
psql -X -v ON_ERROR_STOP=1
```

| Database | Relations visible through information_schema.tables | Relevant observed surfaces |
|---|---:|---|
| market_live | 83 | core items/offers/market observations; evidence assertions/artifacts; workflow runs/intake decisions; live snapshots/changes; auction_watch lots/components/bids |
| techdeals_work | 101 | core items/offers/market observations; evidence assertions/artifacts; workflow raw_intake/intake decisions; map source links/unmapped rows; market_live_fdw foreign relations |

These are accessible relation counts, including views and foreign tables, not row counts or stored-table counts. `techdeals_work` has foreign relations for market_live items, offers, observations and sources. A union/read view can therefore show the same underlying cluster record; do not count it as a second independently stored record.

The initial catalog query was:

```sql
SELECT current_database(), current_user;
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_schema, table_name;
```

No production writes, schema changes, collector runs, schedules, or repairs were
performed. Earlier conversation claims were treated as hypotheses. Aggregates
are separate query snapshots while live ingestion continued, not one coordinated
cross-database snapshot.

## Verified finding: unavailable listings leak into current deals

Database: `market_live`. At the audit snapshot, `api.current_deals` returned
3,311 distinct offers/observations. Of those, 1,026 had `availability = 'outofstock'`
and another 2 had `availability = 'out_of_stock'`: 1,028 of 3,311 (31.0%).
The affected source counts were Central Computers 940, Water Panther 59,
ServerPartDeals 27, and Reddit r/hardwareswap 2.

This is not inferred from run status. The stored definition of `api.current_deals`
excludes `(out of stock|unavailable|sold out|expired)` case-insensitively,
but neither `outofstock` nor `out_of_stock` matches that expression.
The view therefore admits those explicit unavailable observations.

Concrete evidence: observation `b6b39cc0-9cfe-5f67-bd5e-502c38b9a5b0`,
offer `0d08b78a-b577-576a-a2fe-8b912817100a`, Water Panther, USD 763,
observed October 13. Both the stored observation and offer say `outofstock`.
Its retained observation payload says `"availability": "OutOfStock"`.
Source URL:
https://www.waterpanther.com/products/refurbished-6-4tb-sas-4-24gb-s-2-5-ssd-for-dell-poweredge-servers-enterprise-drive-in-13g-tray

Impact: the current-deal SQL surface includes listings explicitly not purchasable.
This proves a read-model filtering defect, not a fetch failure. No repair applied.

```sql
SELECT count(*) AS deal_rows, count(DISTINCT offer_id) AS offers,
       count(*) FILTER (WHERE availability IN ('outofstock','out_of_stock'))
         AS explicitly_unavailable
FROM api.current_deals;

SELECT source_family, availability, count(*)
FROM api.current_deals
GROUP BY source_family, availability ORDER BY source_family, availability;

SELECT pg_get_viewdef('api.current_deals'::regclass, true);

SELECT d.observation_id, d.offer_id, d.price_usd, d.availability,
       o.availability_raw, m.raw_payload
FROM api.current_deals d
JOIN core.offers o USING (offer_id)
JOIN core.market_observations m USING (observation_id)
WHERE d.observation_id = 'b6b39cc0-9cfe-5f67-bd5e-502c38b9a5b0';
```

Additional measured facts awaiting interpretation: all 3,311 current-deal rows
had a NULL historical floor. `api.entity_summaries` had 44,782 rows and
44,782 distinct entity IDs, so repeated search labels alone do not establish
duplicate entities in that view.

The two affected community observations are
`d03ae962-dd9d-5ef5-8895-19cc39f1c5c9` (offer
`d8832cc6-c604-58ea-824c-aa2892901343`) and
`d08f17d9-3cfb-58f5-815e-1ae72846d810` (offer
`677d0faf-32e9-5648-b85c-59be852105af`). Their observations and offers both
say `out_of_stock`; their payload's top-level availability field is absent.
This verifies stored-state leakage, not independent correctness of the
community parser's stock interpretation.

## Second-database baseline

`techdeals_work.api.current_deals` returned zero rows at this snapshot.
The local stored data is not empty:

| Local relation | Actual row count |
|---|---:|
| core.items | 10,078 |
| core.offers | 11,176 |
| core.market_observations | 23,467 |
| workflow.raw_intake | 24,139 |
| evidence.artifacts | 0 |

The zero artifact count does not prove missing evidence: raw intake and
observation payloads may retain it. The intake investigator is tracing the
exclusion conditions and payload retention before assigning a failure cause.
`api.entity_summaries` returned 41,508 rows with 41,508 distinct IDs.

```sql
SELECT count(*) FROM api.current_deals;
SELECT 'core.items' AS relation, count(*) FROM core.items
UNION ALL SELECT 'core.offers', count(*) FROM core.offers
UNION ALL SELECT 'core.market_observations', count(*) FROM core.market_observations
UNION ALL SELECT 'workflow.raw_intake', count(*) FROM workflow.raw_intake
UNION ALL SELECT 'evidence.artifacts', count(*) FROM evidence.artifacts;
SELECT count(*), count(DISTINCT entity_id) FROM api.entity_summaries;
```

## Verified finding: GPU model text becomes quantity and divides the ask

Database: `market_live`. Price investigator inspected all 334 retained
r/hardwareswap observations across 31 offers. 313 observations across 10
offers carry quantities matching model/fan-count text, not a stated number
of GPUs. Parent independently reproduced those counts and two payloads.

Observation `4e301e3f-f556-5fa2-adc6-6de1c777f662`, offer
`23eee989-3b64-5b80-89ef-00647a062d83`, retains:

```text
source_line: Gigabyte Windforce 3X OC RTX 4070 - 12GB - $480
quantity: 3
total_price: 480
price_usd: 160.00
```

Observation `d03ae962-dd9d-5ef5-8895-19cc39f1c5c9`, offer
`d8832cc6-c604-58ea-824c-aa2892901343`, retains an RX 7900XTX source line
ending `$800-sold`, quantity 7900 and stored price USD 0.10. That sold listing
also leaks into current deals through the stock-spelling defect above.
RX 6500 XT lines similarly become quantity 6500 and USD 0.01. Windforce 3X
and SHADOW/VENTUS 2X are model names, not sufficient evidence of lots.

The price investigator measured six affected current deals out of nineteen
hardwareswap deals (six out of 3,311 total). Quantity-to-price transformation
is visible in retained payloads; the precise parser code responsible is
not established by this data-only investigation. Original Atom bytes live
in Garage and were not independently fetched; evidence is the stored source
line and normalized payload, corroborated by a listing snapshot.

```sql
SELECT observation_id, offer_id, price_usd, raw_payload
FROM core.market_observations
WHERE observation_id IN (
 '4e301e3f-f556-5fa2-adc6-6de1c777f662',
 'd03ae962-dd9d-5ef5-8895-19cc39f1c5c9');
SELECT count(*) AS observations,
       count(*) FILTER (WHERE (raw_payload->>'quantity')::numeric > 1)
         AS quantity_gt_one
FROM core.market_observations m
JOIN source.sources s ON s.source_id = m.source_id
WHERE s.source_family = 'reddit_hardwareswap';
```

## Verified finding: local work history is excluded and availability changes

All 23,467 local `techdeals_work.core.market_observations` have NULL run_id.
`api.traceable_market_observations` INNER JOINs the run and requires non-NULL
run_id: zero survive. This explains loss from the traceable history surface.
The price investigator also found all 11,176 local offers outside their
freshness windows, so zero current deals is independently expected from age;
do not blame the empty current feed exclusively on provenance.

All 23,467 local market payloads are nonempty, but the investigator found
they consist solely of `{"backfill_source":"price_observations"}`.
Parent reproduced that payload on three observation IDs:
`019f1b06-7eb3-7763-8c2a-1baa37ffe171`,
`019f1b06-7eb5-7171-a539-e9745ef83f73`,
`019f1b06-7eb5-7ec8-a055-094229f52bdd`.
Nonempty JSON is therefore not proof that original source content survived.

The legacy price rows themselves are preserved: investigator's offer/time/price
comparison found zero missing counterparts among 23,467 rows. But of 4,466
latest legacy observations explicitly marked unavailable, 4,459 are returned
as available by `core.latest_prices`. Parent reproduced this count. The
read view interprets missing/unsupported availability via a negative stock
expression, reversing the older explicit flag. This is history-semantic
corruption, not missing numerical prices.

```sql
SELECT count(*) AS observations,
       count(*) FILTER (WHERE run_id IS NULL) AS missing_run
FROM core.market_observations;
SELECT count(*) FROM api.traceable_market_observations;
SELECT pg_get_viewdef('api.traceable_market_observations'::regclass, true);
SELECT count(*) AS unavailable_latest,
       count(*) FILTER (WHERE lp.available_at_observation) AS marked_available
FROM core.price_observations p
JOIN core.latest_prices lp
  ON lp.offer_id = p.offer_id AND lp.observed_at = p.observed_at
WHERE p.available_at_observation = false;
```

## Classification and configuration findings

The identity investigator found five of 476 CPU items and one of 347 GPU items
with structured RAM evidence. Parent reproduced those counts and the DDR4
RDIMM/SODIMM capacities on the representative observations, not just titles.
CPU item `3d78bca3-859d-573c-9b70-12ded76e8243` has observation
`5bef3a79-0024-5288-a577-ee2db7c4dcc4` describing `DDR4`, `RDIMM`,
`8 GB x2`. GPU item `6e67469f-9702-59eb-aaaa-9d60a700d993` has observation
`d585ebeb-bb66-5142-a5e1-9cc0ba962dca` describing `DDR4`, `SODIMM`,
`32 GB x2`. Investigator traced that GPU kit into a 64GB VRAM projection.

Ten memory identities merge different module arrangements. Parent verified
item `860970e8-35a4-56f5-a49e-ebbeeb127139` joins both `16 GB` and
`8 GB x2` latest payloads: observations `8879b4f6-e1e5-5ff2-b9bd-b31b399d405d`
and `be31ef27-7cd0-5cd6-bd64-753e5cf5885b`. An assertion selector choosing
one quantity does not fix two different products sharing an identity.

Thirteen memory items describe RAM+SSD bundles; three attach offers with
different SSD sizes. Parent verified bundle item
`1b8613a1-86b4-531d-b093-fa6c18ebd4c6` joins retained titles for CARDEA A440
2TB (`44a709c5-64c0-5ea1-ac20-cae66e73e748`) and 1TB
(`6fcb565c-a4dc-5e27-9de4-8ecd12919c0e`), including different part numbers.
Whole bundle prices are consequently grouped under one RAM identity.

The Water Panther stock example also loses compatibility grain: its offer
and payload name a 13G tray, while canonical item
`33fb7333-cb85-5a3f-9cb0-88600d3e17e5` names a 14G tray. Parent verified
both names and the shared identity key. Market item_variants contains zero
rows; no variant represents this difference.

Work database legacy RAM lots and mini-PC fields have internal contradictions
documented in the detailed identity report. Their true specifications are
supported only by stored titles/manual summaries, not independently fetched
original product pages. They must not be presented as externally verified
hardware facts.

## Retention versus promotion: findings from actual records

Parent reproduced 24,139 work raw-intake records: 6,927 unprocessed and
unlinked, 24,096 nonblank payloads, and 43 blank payloads with original rows
retained in metadata. The full investigator partitions are:

| State | Records |
|---|---:|
| Unprocessed, no decision/item/offer link | 6,927 |
| Processed, needs_review, no item/offer link | 11,868 |
| Processed, out_of_scope, no item/offer link | 5,308 |
| Processed, linked to canonical item/offer | 36 |

This proves stored records are largely outside the ordinary normalized
offer/observation path, not that all rejected records should be accepted.
6,884 unprocessed eBay imports include 3,459 search-page URLs without individual
listing URLs. Parent verified intake `01a0f25c-1f48-7522-831b-31589a993bff`
retains a USD 90 Samsung RDIMM claim and explicitly records missing listing ID;
its raw payload is only a CSV-row pointer, not original listing content.

The Central Computers legacy import has 16,901 retained intake records and no
canonical links from those records. Of its needs-review decisions, 3,662 say
the writer could not build identity. An EPYC 7543 example retains model, item
number and USD 3,299.99, yet its disposition is identity failure. This is
identity-dependent promotion, not proof the source lacks useful information.

Parent reproduced these fixed live run counts:

| Run | Parser outputs | Snapshots | Decisions | Market observations | Artifact references |
|---|---:|---:|---:|---:|---:|
| FusionWW dbcdb505-5272-4526-be45-6180a9281682 | 10,614 | 0 | 0 | 0 | 119 |
| RackWatch 9f63541e-eac2-4719-a180-77c3b181f91f | Not recorded | 5,233 | 0 | 0 | 6 |

FusionWW records successful parsing but has no record-level disposition or
normalized result. Its artifacts reference Windows filesystem paths; byte
availability was not checked. Do not describe its 10,614 parser outputs as
10,614 eligible offers, or conclude their source bytes are definitely lost.
RackWatch retains the snapshots; most do not match canonical key/URL records.
That is retained/raw-only evidence, possibly intentional, not capture loss.

## Other observed gaps and important non-findings

- All 3,311 live current deals lack historical floors. Investigator verified
  no source satisfies the view's authority tier <= 2 rule: historical data
  exists, but this policy gate prevents a floor. Whether to change the policy
  requires a separate decision; do not call it absent collection.
- 955 of 60,928 live observations are outside the traceable surface. For 813
  retailer observations, stored observation item IDs disagree with their
  offer's current item ID. This is a history/read-link problem; source records
  exist. Detailed report includes source counts and an exact example.
- Run counters are not reliable coverage denominators: Water Panther can
  retain 1,641 snapshots while its run's raw/candidate counters remain zero.
- No numerical legacy prices were missing from the matched work backfill.
- No confirmed supported-RAM-maximum substituted for installed RAM was found
  in the examined eight explicit live rack-server examples.
- Repeated entity labels are not duplicate entity IDs in the queried API view.
- Deliberately partial Reddit feeds are not failed acquisition. Actual failed
  attempts are counted separately in the intake report.
- External Garage/file/sandbox byte existence, source-page correctness beyond
  stored representations, and exact responsible code paths remain unverified.

## Complete evidence reports and repair order

Full investigator findings, denominators, persistent IDs and successful SQL:

- [Price and history evidence](cluster-price-evidence.md).
- [Identity and configuration evidence](cluster-identity-evidence.md).
- [Intake and retention evidence](cluster-intake-evidence.md).

Proposed follow-through, separate from this investigation:

1. Stop publishing fabricated per-unit GPU prices and unavailable current deals.
2. Correct affected retained normalized rows through an explicit history-safe
   repair, preserving the source evidence and distinguishing old from corrected
   interpretation. Do not merely hide bad rows in the UI.
3. Separate materially different module/bundle/tray configurations before
   comparing their prices.
4. Recover queryable readings from parked raw records without requiring product
   identity or a current ask; record incomplete evidence and deliberate exclusions.
5. Preserve original availability and price-kind semantics through migration;
   do not fabricate run provenance for legacy rows.
6. Decide historical-floor authority policy using the actual source tiers.

An implementation plan needs exact code localization and failing-before/
passing-after verification for each repair. This report does not claim those
repairs or the two-repo consolidation are complete.

## Comparison: Existing implementation vs current greenfield (`techdeals-v2`)

The table below documents how the defects identified in `TechdealsHandoff` compare
to the current state of `techdeals-v2`. v2 is not a proven replacement; it is an
early schema and extraction pilot that shares several of the same failure modes.

| Defect / Dimension | Existing Repo (`TechdealsHandoff` / Cluster) | Current Greenfield (`techdeals-v2`) |
|---|---|---|
| **Unavailable listings leak into pricing** | **1,028 of 3,311** rows in `api.current_deals` say `outofstock` or `out_of_stock`. Regex misses both.<br>*(obs `b6b39cc0-9cfe-5f67-bd5e-502c38b9a5b0`)* | **Same defect in part-out:** `v_partout` allows out-of-stock asks to set reference prices.<br>*(R7515 drive comps of $1,152 come from unavailable listings; `exact_refs_in_stock = false` in `schema/020_views.sql:571`, ADR 0002)* |
| **Model / text parsed as quantity** | Model text divides asking price: Windforce 3X RTX 4070 ($480) parsed as qty 3 → **$160**; RX 7900XTX ($800) parsed as qty 7,900 → **$0.10**.<br>*(obs `4e301e3f-f556-5fa2-adc6-6de1c777f662`, `d03ae962-dd9d-5ef5-8895-19cc39f1c5c9`)* | **Unprobed on GPUs; lot-division failure on Reddit:** "$280 for the lot of 4" was extracted as `explicit_unit` at qty 1 ($280/ea), tripping `quantity_conflict` quarantine and dropping the price completely.<br>*(Example: `engine/out/results_slice3_cell_c.json`)* |
| **Loss of compatibility & configuration grain** | Merges 13G tray offer into a 14G tray item (`0d08b78a-b577-576a-a2fe-8b912817100a`). Merges 1x16GB vs 2x8GB (`860970e8-35a4-56f5-a49e-ebbeeb127139`). Merges 1TB and 2TB SSD bundles (`1b8613a1-86b4-531d-b093-fa6c18ebd4c6`). | **Same grain loss:** `resolve.py:78` builds `drive:hdd:sas:1200gb`, completely ignoring tray version (13G vs 14G).<br>**Same RAM fungibility error:** `v_ddr4_gb_rate` pools all DDR4 (RDIMM, UDIMM, SODIMM, speeds, module sizes) into a single $2.36/GB rate from one 32GB stick. |
| **Category misclassification** | 5 CPU items and 1 GPU item have structured payloads proving they are RAM kits/modules.<br>*(Example: CPU item `3d78bca3-859d-573c-9b70-12ded76e8243` is an A-Tech DDR4 RDIMM kit)* | **Completely uninvestigated across categories:** v2 has only processed single-socket EPYC servers and clean storage drives. Its prompt and parser have never been tested on mixed-category retail sweeps, GPUs, or expansion cards. |
| **Price history & availability corruption** | In `techdeals_work`, 4,459 of 4,466 unavailable historical prices flip to `available = true` in `core.latest_prices` because NULL defaults to available.<br>*(Example: price ID `4c8f1b8d-a1e2-568d-8d21-92d379023a75`)* | **Zero real time-series depth:** v2 has only ingested single-point-in-time snapshots on Neon (plus one 5-listing replay test). How `v_price_history` behaves over weeks of price drops, re-listings, and stock toggles is entirely unverified. |
| **Provenance exclusions dropping data** | In `techdeals_work`, all 23,467 local observations lack a `run_id`, causing `api.traceable_market_observations` to drop 100% of them from queryable views.<br>*(Example: `techdeals_work.core.market_observations`)* | **Single point of failure on offer keys:** In v2, if natural facts change slightly across parser versions (e.g. whitespace, currency default), the SHA-256 `offer_key` changes, creating orphaned observations or split series. Proven on 5 fixtures, never tested at scale. |
| **Intake retention vs queryable data** | 24,139 raw records in work DB: 6,927 unprocessed/unlinked, 11,868 stuck in `needs_review`. FusionWW parsed 10,614 records but stored 0 canonical offers or observations.<br>*(Example: run `dbcdb505-5272-4526-be45-6180a9281682`)* | **Zero automated pipeline:** v2 has no background collectors, no scheduler, and no queue. Ingestion requires manually running Python CLI scripts (`extract.py`) against local JSON directories. |
| **Server part-out coverage** | No part-out logic exists. Multi-item server listings are either force-fit into single items or discarded. | **Extremely sparse coverage:** On the loaded R7515 server, 7 of 9 lines have no comps. 0 of 51 multi-item server sale groups with 8+ lines are fully priced. |
