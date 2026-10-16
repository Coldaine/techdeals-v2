# Cluster intake and retention evidence

## Scope and evidence boundaries

Queried **`techdeals_work` and `market_live` on `pg18-core-db.moosegoose.xyz`**, read-only. No production/repository changes, collectors, tests, builds, linters, or formatters.

Discovered schema before querying. Important distinctions:

- `techdeals_work` has `workflow.raw_intake`; `market_live` does not.
- `market_live` has `live.listing_snapshots`; `techdeals_work` does not.
- Work DB’s `core.unified_market_observations` includes `market_live_fdw` observations, excluding matching local fingerprints. **All local work totals below use `core.*` directly**, not unified/API views.
- Live ingestion continued during investigation. Reported aggregate counts are observed query results, not a coordinated cross-database snapshot. Fixed historical run IDs are reproducible.

## Findings

### 1. Work intake is retained, but most records never acquired canonical links

**Database: `techdeals_work`. High confidence in accounting; not evidence that every reviewed record should be accepted.**

Of **24,139 raw-intake records**:

| Persisted state | Records |
|---|---:|
| Unprocessed, no decision, no item/offer link | **6,927** |
| Processed, `needs_review`, no item/offer link | **11,868** |
| Processed, `out_of_scope`, no item/offer link | **5,308** |
| Processed, canonical item/offer links | **36** |

All 36 item and offer links resolve; **zero dangling links**.

The recent unprocessed records comprise:

- **6,884 eBay scrape records**, run `01a0f256-0462-7705-a30b-92143f874cf0`, September 30.
- **43 manual records**, run `01a0f249-5fb8-7f84-968c-78038c1264b4`, September 30.

All 6,927 have `source_id IS NULL`; none have intake decisions or canonical links. They are retained raw/workflow records, not normalized market observations.

Examples:

- Intake `01a0f25c-1f48-7522-831b-31589a993bff`: Samsung RDIMM; stored price `$90`, source URL is an eBay search page. Stored uncertainty explicitly says **“no per-listing /itm/ id.”** Its raw payload is only:
  ```json
  {"i":9,"f":"ebay_ddr4_ddr5_rdimm_16gb_sold_and_for_sale_2026-09-30.csv","id":null}
  ```
  Title, price, date, and metadata survive, but this is **not a retained complete original listing payload**.
- Intake `01a0f24a-2d75-7290-9e5e-e8d5baeae7ee`: Framework laptop, `$849`. `raw_payload` is blank, but **`metadata.raw_row` retains the original imported row**. Its description explicitly calls the laptop category untracked/raw intake.

**Payload accounting:** 24,096 have nonblank `raw_payload`; the other 43 have `metadata.raw_row`. Therefore **43 blank payload-column values are not 43 lost records**.

**eBay-specific source quality:** of 6,884 scrape records:

- **3,459** use search-page URLs rather than individual `/itm/` URLs.
- **3,425** have `/itm/` URLs.
- All **6,884** have a null `raw_payload.id`.
- All **6,884** retain `observed_price`.

Consumer impact: these records cannot reach ordinary offer/observation consumers through their raw-intake links. For search-page-only records, persistent listing identity is additionally unresolved. Whether they were intentionally parked is not established.

### 2. Legacy imported records have explicit promotion failures—not missing raw rows

**Database: `techdeals_work`. High confidence; cause is the persisted decision reason, not independently diagnosed writer code.**

Central Computers DuckDB import: **16,901 retained raw records**:

- **11,621** `needs_review`.
- **5,280** `out_of_scope`.
- **0** raw-to-canonical links.

Of those reviewed rows:

- **7,935**: `no tracked category match`.
- **3,662**: `writer could not build identity`.
- Remaining 24 reviewed rows have other reasons.

Representative:

- Intake `ee9f5d0e-cb3e-5752-943d-efe61e34e1a0`.
- Decision `019fa5ae-278a-792b-b1fc-56e1c5391c8a`.
- Raw AMD EPYC 7543 row retains model `100-100000345`, item number `CPUAMDE7543R`, `$3299.99`, availability `Special Order`.
- Decision: **`needs_review`, “writer could not build identity.”**

PSU DuckDB import: **116/117** records have the explicit reason:

> one-time DuckDB migration row retained in intake; legacy canonical writer could not promote it

The remaining one is accepted and linked.

There are already legacy canonical offers from separate sources in the work DB. **Do not equate “no raw link” with “no equivalent item anywhere.”** These findings establish failed/absent promotion of the identified intake records.

### 3. Work DB’s empty current-deals API has a concrete provenance gate and an independent freshness gate

**Database: `techdeals_work`. High confidence.**

All **23,467/23,467 `core.market_observations` have `run_id NULL`**.

`api.traceable_market_observations`:

- Inner-joins `workflow.collection_runs`.
- Requires nonnull `mo.run_id`.

Consequently **0/23,467 observations survive that view**, and `api.current_deals` starts from the empty traceable view.

Independent freshness accounting:

- **0/11,176 local offers** are fresh under their category’s `freshness_days`.
- Tracked-category freshness windows are 14 or 30 days.
- Latest local observation: **June 24**.

Raw evidence nuance:

- All **23,467 observation payloads are exactly**
  ```json
  {"backfill_source":"price_observations"}
  ```
- Thus the observation `raw_payload` is a migration marker—not original source evidence.
- Work DB has **0 artifacts, 0 fetch attempts, 0 parse executions, 0 run-source ledger rows**.
- Raw-intake payloads remain separately retained as described above.

Representative observation `019f1b06-be4b-7fc3-8ccc-a56a1f595429`, offer `b2e51874-bacf-5798-ab16-9d0cba6cf768`: entity links populated, `run_id NULL`, marker-only payload.

Consumer impact: local migrated observations are structurally excluded from the provenance-aware API; their age would independently exclude them from current deals. This is not evidence that all imported prices disappeared.

### 4. Fusion Worldwide parsed 10,614 records but persisted no record-level disposition or normalized result

**Database: `market_live`. High confidence in the gap; implementation cause unverified.**

Fixed run **`dbcdb505-5272-4526-be45-6180a9281682`**, September 24:

- **118/118 fetch attempts succeeded**.
- Parser **`3488b100-76fe-4943-b397-591b798fb0f8`** succeeded, recording **10,614 outputs**.
- **0 listing snapshots**.
- **0 intake decisions**.
- **0 market observations**.
- **0 offer-run presences**.
- **0 canonical offers for Fusion Worldwide**.
- **119 artifact references**, all without inline payloads.
- Parser `output_artifact_id NULL`.

Run metadata explicitly records:

```json
{
  "records_parsed":10614,
  "offers_accepted":0,
  "distinct_offers_seen":0,
  "incomplete_reasons":["zero_rows"]
}
```

The retained artifact references are Windows `file:///D:/...` paths; e.g. artifact `1d9e1d0d-9fc8-41c6-b2eb-aa19a983fd79` describes the first category response, 429,507 bytes.

Consumer impact: none of those reported parser outputs reach canonical consumers, and no per-record decision explains their disposition. **Do not assert 10,614 eligible offers were lost**: those are parser-reported records, not a verified eligible catalog. Original external artifact bytes were not reachable through the database.

### 5. RackWatch retains substantial raw discovery data outside canonical offers

**Database: `market_live`. High confidence in retention/linkage; intentional raw-only workflow remains possible.**

Observed **776,362 listing snapshots**, all with nonempty JSON.

Across these snapshots:

- **9,651 snapshots / 8,653 distinct keys** have no canonical `source_listing_key` match.
- All 9,651 retain a URL.
- Only **3** have an exact canonical URL match.
- **9,648** have neither an exact key nor exact URL match.
- These unmatched snapshots belong to RackWatch/manual runs, not the ordinary catalog collector runs.

Fixed October 5 run **`9f63541e-eac2-4719-a180-77c3b181f91f`**:

- Stated raw count: **5,233**.
- Stated candidates: **5,233**.
- Retained snapshots: **5,233**.
- Intake decisions: **0**.
- Market observations: **0**.
- Canonical key or URL matches: **1/5,233**.
- eBay-tagged snapshots: **2,423/5,233**.

Example snapshot `e6f36435-9a25-430c-8e19-c3680b17fd57`, key `ebay:364979054867`, retains an individual eBay URL, source title, seller, `$7,026.80` price text, shipping, condition, route, and query.

Consumer impact: discovery candidates exist in retained raw snapshots but are not generally represented in canonical observations. This is **stranded/raw-only retention**, not payload loss. Candidate counts do not establish eligibility.

### 6. Live review events heavily repeat; distinct keys and present canonical offers must be separated

**Database: `market_live`. High confidence.**

Historical review decisions are not a unique-record count:

| Source | `needs_review` decisions | Distinct reviewed keys | Reviewed keys without present canonical offer |
|---|---:|---:|---:|
| Central Computers | **847,072** | **11,712** | **10,873** |
| diskprices.com | **228,980** | **3,224** | **2,836** |
| DiscTech | **2,284** | **2,277** | **2,277** |
| ServerSupply.com | **159** | **146** | **146** |
| Water Panther | **1,287** | **99** | **0** |

Water Panther demonstrates why historical review events cannot automatically be labeled currently stranded.

For Central Computers’ specific **“identity key could not be built”** reason:

- **80,438 decisions / 1,954 distinct keys**.
- **1,135/1,954 keys** currently lack canonical offers.
- **59,856** decision events concern those missing keys.

Concrete unpromoted example:

- Decision `0c74c4bd-1079-57ff-8e3d-a17aa7c49299`.
- Key `sku:POWTRIDU15NR`.
- Raw metadata retains individual product URL, SKU/product ID, `$299.99`, `InStock`.
- Stored reason: **identity key could not be built**.
- No same-source canonical offer with that listing key.

Do not classify the bulk `no tracked category match` records as necessarily incorrect exclusions. No correctness assumption was made from titles.

### 7. Actual acquisition failures exist; successful partial Reddit runs are not failures

**Database: `market_live`. High confidence from persisted failed fetch/run evidence.**

Run-source ledger outcomes observed:

- Central Computers: **46 failed / 158 run-source rows**.
- Water Panther: **21 failed / 126**.
- diskprices.com: **28 failed / 207**.
- Reddit homelabsales: **118 failed / 5,503**.
- Reddit hardwareswap: **50 failed / 2,550**.

Separately, **5,385 homelabsales and 2,500 hardwareswap run-source rows are partial rolling-feed results**. These are **not classified as failed coverage**.

Concrete actual failure:

- Central Computers run `2f11777b-f9bd-41dd-866e-8025c5f27870`.
- Failed parser `6e32df23-e5f7-4cc9-b637-e114d9575e60`.
- October 13.
- Error: acquisition failure on page 5, `attempts=1 last_reason=timeout`.
- Zero snapshots/decisions/presence/observations for that failed run.
- A subsequent separate partial run retained **2,542 snapshots**, **13,930 decisions**, and **2,767 offer presences**. Therefore this failed attempt does not imply the day’s entire source was absent.

Recorded eBay acquisition attempts: **27 attempts across nine runs**, **0 succeeded**, eight failed, 12 blocked; other attempts skipped. This does **not** mean zero eBay discovery data: RackWatch separately retains paid/manual discovery snapshots.

Seven `collection_runs` remained `running` for more than a day at observation, including Central Computers runs from August 16, August 20, and October 12. These are stale workflow states; process survival was not checked.

### 8. Counters and evidence references have important limitations

- Work `collection_runs.raw_intake_count` totals **24,056**, versus **24,139 actual raw records**. The 83-row difference is explained by two runs declaring zero while storing **61** and **22** raw rows.
- Live catalog run counters frequently remain **0/0 despite successful persistence**. Example Water Panther run `aa1bdee9-832b-4e3f-ae14-34fa5ff7e234` ultimately completed with **1,641 snapshots, 1,641 presences, five new observations**, but counters remained zero.
- Consequently **neither counters nor max `offers_seen` are a defensible intended-catalog denominator**.
- Live artifacts: observed **25,568** references: Garage 25,073; inline 292; filesystem 130; external 68; memory five. All inline references have inline bytes. **Zero artifacts lack both an inline payload and a storage URI**.
- Five memory references use `sandbox://rackwatch/...` URIs and have no inline content. External object/file/sandbox existence was not verified; **database references alone do not prove durable byte availability**.
- **Zero snapshots have a missing run**; **zero nonnull fetch-response references point to absent artifact rows**.
- All parser executions inspected have no `output_artifact_id`. Input evidence exists, but parser output replay generally depends on record-level snapshots/decisions or rerunning the parser.
- The 149 offers without joined items are **null item IDs**, not dangling IDs: eBay 145, Express Computer Systems three, PC Server & Parts one.

## Reproducible SQL

Run through the agreed Doppler/`psql -X -v ON_ERROR_STOP=1` read-only wrapper.

### Work intake partitions, retention, source accounting, and counters

```sql
WITH d AS (
  SELECT intake_id, array_agg(DISTINCT scope_decision) decisions
  FROM workflow.intake_decisions
  WHERE intake_id IS NOT NULL
  GROUP BY intake_id
)
SELECT r.processed, r.offer_id IS NOT NULL offer_link,
       d.decisions, count(*)
FROM workflow.raw_intake r LEFT JOIN d USING (intake_id)
GROUP BY 1,2,3 ORDER BY 4 DESC;

SELECT s.source_name, r.source_type, count(*) total,
       count(*) FILTER (WHERE processed) processed,
       count(item_id) item_links, count(offer_id) offer_links,
       count(*) FILTER (
         WHERE nullif(trim(raw_payload),'') IS NULL
       ) blank_payload,
       count(*) FILTER (
         WHERE nullif(trim(raw_payload),'') IS NOT NULL
            OR metadata ? 'raw_row'
       ) retained_record_payload,
       min(captured_at), max(captured_at)
FROM workflow.raw_intake r
LEFT JOIN source.sources s USING (source_id)
GROUP BY 1,2 ORDER BY 3 DESC;

SELECT s.source_name, d.scope_decision, d.reason, count(*)
FROM workflow.intake_decisions d
JOIN workflow.raw_intake r USING (intake_id)
LEFT JOIN source.sources s ON s.source_id=r.source_id
GROUP BY 1,2,3 ORDER BY 4 DESC;

SELECT r.run_id, r.scope, r.raw_intake_count, r.candidates_produced,
       count(i.intake_id) actual_raw
FROM workflow.collection_runs r
LEFT JOIN workflow.raw_intake i USING (run_id)
GROUP BY r.run_id ORDER BY r.started_at;

SELECT metadata->>'scrape_family' family,
       metadata->>'listing_status' status,
       count(*) records,
       count(*) FILTER (
         WHERE source_url LIKE 'https://www.ebay.com/sch/%'
       ) serp_urls,
       count(*) FILTER (WHERE source_url LIKE '%/itm/%') item_urls,
       count(*) FILTER (
         WHERE raw_payload::jsonb->>'id' IS NULL
       ) absent_payload_id,
       count(observed_price) prices
FROM workflow.raw_intake
WHERE source_type='scrape'
GROUP BY 1,2;
```

### Work provenance/freshness gates

```sql
SELECT count(*) observations, count(run_id) run_links,
       count(item_entity_id) item_entity_links,
       count(offer_entity_id) offer_entity_links,
       count(*) FILTER (
         WHERE raw_payload='{"backfill_source":"price_observations"}'::jsonb
       ) marker_only
FROM core.market_observations;

SELECT count(*) FROM api.traceable_market_observations;

SELECT pg_get_viewdef('api.traceable_market_observations'::regclass,true);
SELECT pg_get_viewdef('api.current_deals'::regclass,true);
SELECT pg_get_viewdef('core.unified_market_observations'::regclass,true);

SELECT count(*) offers,
       count(*) FILTER (
         WHERE o.last_observed_at >=
               now()-make_interval(days=>c.freshness_days)
       ) fresh
FROM core.offers o JOIN core.categories c USING (category_id);
```

### Live fixed-run accounting and retained evidence

```sql
SELECT r.run_id, r.status, r.started_at, r.completed_at,
       r.raw_intake_count, r.candidates_produced, r.notes, r.metadata,
       (SELECT sum(output_record_count)
        FROM workflow.parse_executions p WHERE p.run_id=r.run_id) parser_output,
       (SELECT count(*) FROM live.listing_snapshots x
        WHERE x.run_id=r.run_id) snapshots,
       (SELECT count(*) FROM workflow.intake_decisions x
        WHERE x.run_id=r.run_id) decisions,
       (SELECT count(*) FROM core.market_observations x
        WHERE x.run_id=r.run_id) observations,
       (SELECT count(*) FROM workflow.offer_run_presence x
        WHERE x.run_id=r.run_id) presence,
       (SELECT count(*) FROM evidence.artifacts x
        WHERE x.run_id=r.run_id) artifacts
FROM workflow.collection_runs r
WHERE r.run_id IN (
 'dbcdb505-5272-4526-be45-6180a9281682',
 '9f63541e-eac2-4719-a180-77c3b181f91f',
 '2f11777b-f9bd-41dd-866e-8025c5f27870',
 '6e72e31c-d404-44e2-8142-0a125c34f622',
 'aa1bdee9-832b-4e3f-ae14-34fa5ff7e234'
);

SELECT fetch_attempt_id, status, failure_class, request_url,
       attempt_number, error_message
FROM workflow.fetch_attempts
WHERE run_id='dbcdb505-5272-4526-be45-6180a9281682';

SELECT * FROM workflow.parse_executions
WHERE run_id IN (
 'dbcdb505-5272-4526-be45-6180a9281682',
 '2f11777b-f9bd-41dd-866e-8025c5f27870'
);

SELECT a.artifact_id, a.storage_backend, a.storage_uri,
       a.content_length_bytes, a.inline_content IS NOT NULL inline_present
FROM evidence.artifacts a
WHERE run_id='dbcdb505-5272-4526-be45-6180a9281682';

SELECT s.source_name, count(o.offer_id)
FROM source.sources s LEFT JOIN core.offers o USING (source_id)
WHERE s.source_name='Fusion Worldwide'
GROUP BY 1;
```

### Live snapshots versus canonical keys/URLs

```sql
SELECT count(*) snapshots, min(captured_at), max(captured_at),
       count(*) FILTER (
         WHERE raw_json IS NULL OR raw_json='{}'::jsonb
       ) empty_payload
FROM live.listing_snapshots;

WITH x AS (
  SELECT ls.*,
         coalesce(ls.raw_json->>'source_url',
                  ls.raw_json->>'url',
                  ls.raw_json->'row'->>'url') url
  FROM live.listing_snapshots ls
  LEFT JOIN (
    SELECT DISTINCT source_listing_key FROM core.offers
  ) k ON k.source_listing_key=ls.source_listing_key
  WHERE k.source_listing_key IS NULL
), u AS (
  SELECT DISTINCT source_url
  FROM core.offers WHERE source_url IS NOT NULL
)
SELECT count(*) no_key_match,
       count(DISTINCT x.source_listing_key) distinct_keys,
       count(*) FILTER (WHERE x.url IS NOT NULL) has_url,
       count(u.source_url) exact_url_matches,
       count(*) FILTER (WHERE u.source_url IS NULL) neither_match
FROM x LEFT JOIN u ON u.source_url=x.url;

SELECT snapshot_id, run_id, source_listing_key, raw_json
FROM live.listing_snapshots
WHERE snapshot_id='e6f36435-9a25-430c-8e19-c3680b17fd57';
```

### Live review backlog, source/time coverage, failed attempts

```sql
WITH d AS (
  SELECT source_id, listing_key, scope_decision,
         count(*) events, min(decided_at) first, max(decided_at) last
  FROM workflow.intake_decisions
  WHERE source_id IS NOT NULL AND listing_key IS NOT NULL
  GROUP BY 1,2,3
)
SELECT s.source_name, d.scope_decision, sum(d.events) decisions,
       count(*) distinct_keys,
       count(*) FILTER (WHERE o.offer_id IS NULL) keys_without_offer,
       min(d.first), max(d.last)
FROM d JOIN source.sources s USING (source_id)
LEFT JOIN core.offers o
  ON o.source_id=d.source_id AND o.source_listing_key=d.listing_key
GROUP BY 1,2 ORDER BY 3 DESC;

SELECT decision_id, run_id, listing_key, reason, metadata
FROM workflow.intake_decisions
WHERE decision_id='0c74c4bd-1079-57ff-8e3d-a17aa7c49299';

SELECT s.source_name, rs.status, rs.scope_complete,
       count(*) run_sources, sum(rs.offers_seen) seen_events,
       sum(rs.expected_offer_count) stated_expected,
       min(rs.started_at), max(rs.started_at)
FROM workflow.collection_run_sources rs
JOIN source.sources s USING (source_id)
GROUP BY 1,2,3 ORDER BY 1,2;

SELECT s.source_name, count(*) offers,
       min(o.first_observed_at), max(o.last_observed_at)
FROM core.offers o JOIN source.sources s USING (source_id)
GROUP BY 1 ORDER BY 2 DESC;

SELECT s.source_name, f.status, f.failure_class,
       count(*) attempts, count(DISTINCT f.run_id) runs,
       min(f.started_at), max(f.started_at)
FROM workflow.fetch_attempts f
LEFT JOIN source.sources s USING (source_id)
GROUP BY 1,2,3 ORDER BY 4 DESC;

SELECT run_id, source_id, scope, started_at, completed_at
FROM workflow.collection_runs
WHERE status='running' AND started_at<now()-interval '1 day'
ORDER BY started_at;
```

### Evidence-reference completeness and null outcomes

```sql
SELECT storage_backend, count(*) artifacts,
       count(*) FILTER (WHERE inline_content IS NOT NULL) inline_payloads,
       count(*) FILTER (
         WHERE inline_content IS NULL AND nullif(storage_uri,'') IS NULL
       ) missing_payload_or_location
FROM evidence.artifacts GROUP BY 1;

SELECT count(*) missing_run
FROM live.listing_snapshots x
LEFT JOIN workflow.collection_runs r USING (run_id)
WHERE r.run_id IS NULL;

SELECT count(*) dangling_response_artifact
FROM workflow.fetch_attempts f
LEFT JOIN evidence.artifacts a ON a.artifact_id=f.response_artifact_id
WHERE f.response_artifact_id IS NOT NULL AND a.artifact_id IS NULL;

SELECT s.source_name, count(*) offers,
       count(*) FILTER (WHERE o.item_id IS NULL) null_item_id,
       count(*) FILTER (
         WHERE o.item_id IS NOT NULL AND i.item_id IS NULL
       ) dangling_item_id
FROM core.offers o
JOIN source.sources s USING (source_id)
LEFT JOIN core.items i USING (item_id)
GROUP BY 1
HAVING count(*) FILTER (WHERE i.item_id IS NULL)>0;
```

**Unverified:** external artifact byte availability, intended disposition of RackWatch raw-only candidates, exact code cause of Fusion’s parser-to-record gap, and correctness of individual classification/review choices. No catalog-size inference was made from maximum observed offer counts.
