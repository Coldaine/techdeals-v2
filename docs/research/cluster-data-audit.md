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
