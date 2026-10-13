# Cluster data audit

Status: investigation in progress. This baseline is verified; it does not claim that the failure analysis is complete.

## Scope

Owner request: investigate actual data failures in TechdealsHandoff with multiple agents, from stored data rather than guesses or documentation. Inspect both cluster databases, not Neon. Preserve the results in commits and a PR.

Separate parallel investigations cover prices/history, classification/configurations, and intake/retention. Findings must include query scope, denominator, persistent row IDs, source evidence where reachable, consumer impact, and uncertainty. A deliberately partial rolling Reddit feed is not a failure merely because its status is partial. Missing current offers do not establish missing collection.

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

No production writes, schema changes, collector runs, schedules, or repairs are authorized by this investigation. Exact live failures and their evidence will be added as the investigations complete. Earlier conversation claims are hypotheses until verified against these databases.

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
