## Verified findings

Read-only SELECT investigation against live-cluster `market_live` and local `techdeals_work`; no repository/production changes or checks.

### 1. Reddit model/fan-count text is parsed as quantity, dividing actual asking prices

**Database:** `market_live`. **Confidence:** high; retained normalized payload and `live.listing_snapshots` explicitly contain source line, total price, inferred quantity, and divided price. Original Garage Atom bytes not downloaded; “source claim” below is the retained `source_line`, not independently authenticated original HTML.

All **334 hardwareswap observations / 31 distinct offers** examined. **313 observations / 10 offers** have quantity >1; every such source line contains GPU model/fan-count text corresponding to the quantity:
- RX **6500** XT: $60 or $70 → quantity 6500 → **$0.01** stored. Offers `5f8405e0-ccdf-5de5-8c31-3de99052ca5c` (54 observations) and `466c0ddd-4295-5929-af1e-0ea02418ed8d` (60).
- RX **7900**XTX: $800 → quantity 7900 → **$0.10**. Offers `7bab6be5-72c9-5319-bc89-d5ae889c0efa` (7) and `d8832cc6-c604-58ea-824c-aa2892901343` (66).
- Windforce **3X** RTX 4070: $480 → **$160**, $500 → **$166.67**. Offers `23eee989-3b64-5b80-89ef-00647a062d83` (1), `de917099-c0f7-550f-8ebe-d1becb089888` (10), `feae1532-f55f-5dab-866b-8e0eb1d2b56d` (112).
- SHADOW **2X** RTX 5050: $275 → **$137.50**. Offers `28406169-6e84-5740-a66f-316f3c90371f`, `86be696c-a82b-5d20-85ec-6cc6ef8cfb7b`, one each.
- VENTUS **2X** RTX 4060: $320 → **$160**. Offer `507fd737-d649-5e6f-a409-192ea24b2cea`, one.

**6 of 19 current hardwareswap deals** expose these divided prices; **6/3311** total API current deals. Price transformation is proven; parser mechanism matching model numbers is a strongly supported inference from exact correspondences, not inspected code.

Concrete observation `4e301e3f-f556-5fa2-adc6-6de1c777f662`:
```
source_line: Gigabyte Windforce 3X OC RTX 4070 - 12GB - $480
total_price: 480
quantity: 3
price_usd: 160.00
```
Matching snapshot `2ed5d5c3-fe41-510f-ab01-a6dad52609c4` has the same fields. Evidence artifact `97a5a099-3066-4e1f-8db6-6d69dca042b1`, Atom content, 191448 bytes, Garage URI:
`s3://techdeals-artifacts/fetch/sha256/79/799ebf80925e73ab825be1bf9b2217d23edf067f9470c6abd650c6cdb05ce610.bin`.

### 2. Additional unavailable encoding missed: `out_of_stock`, not just parent's `outofstock`

**Database:** `market_live`. **Confidence:** high.

Two of 19 current hardwareswap deals have **`out_of_stock`** and source lines explicitly say sold:
- Observation `d08f17d9-3cfb-58f5-815e-1ae72846d810`, offer `677d0faf-32e9-5648-b85c-59be852105af`, $370, RTX 4060 Ti.
- Observation `d03ae962-dd9d-5ef5-8895-19cc39f1c5c9`, offer `d8832cc6-c604-58ea-824c-aa2892901343`, $0.10 mispriced RX 7900XTX; raw source line ends `$800-sold`.

Both offers remain `listing_status='active'`, eligible true, unavailable_at NULL. API stock regex misses underscores. Thus total confirmed API unavailable encodings are **1028/3311**, comprising Central Computers 940, Water Panther 59, ServerPartDeals 27, hardwareswap 2. Parent already owns the first 1026.

No API observation is older than its category freshness interval (**0/3311**). No current offer has eligibility false or unavailable_at set (**0/3311** each). Age alone is not demonstrated failure.

### 3. Price-history backfill preserves price rows but discards availability semantics

**Database:** `techdeals_work`, strictly local data. **Confidence:** high.

All **23467 legacy price rows** have matching market observations by offer/time/price (**0 missing**); all market payloads are only `{"backfill_source":"price_observations"}`. Therefore prices are not absent, but history metadata is misread.

Of **4487 price observations with `available_at_observation=false`**, **4480** map to availability strings interpreted as available by price read views:
- Mini PC market scan: **3640/3640** unavailable rows misread; source denominator 5461 history rows.
- DDR5 RDIMM unified: **832/836**; source denominator 1822.
- DDR5 verified: **8/8**; denominator 23.
- Manual buildapcsales: **0/3**; denominator 35.

Latest-price counterpart: **4459/4466 unavailable latest history rows** are returned as available by `core.latest_prices`: Mini PC 3640, DDR5 unified 811, DDR5 verified 8.

Concrete:
- Price ID `4c8f1b8d-a1e2-568d-8d21-92d379023a75`, offer `f5355cfd-9bdc-5614-a5dd-733a995feae2`, $4799.20, legacy available=false.
- Market observation `019f1b06-872c-75bb-b189-367a9c4d158f` has availability NULL.
- `core.latest_prices` yields available=true, because NULL becomes empty string and passes negative stock regex.

Also **1064/11073 latest-time matched history rows** have their observation kind changed to hardcoded `current_listing`; history contains 1235 `historical_scrape` rows overall. Consumer impact: read view erases historical/source availability classification. No current local deals are exposed: all local offers are stale.

**Related market_live issue:** legacy eBay history has **18 rows**, **4/18 offers absent from `core.latest_prices`**, and **10/18 unavailable historical rows read available**. Example price ID `01a0ffce-122e-753e-851b-a2f290dcfcdf`, offer `2d559d4d-91d2-41ea-ae5f-b170aec073a5`, notes “sold/OOS”, historical false → latest true, `ask` → `current_listing`. Four recently added UK/AU eBay offers have no market observation, so the market-observation-only latest view omits them; legacy notes contain currency conversions, not verified currency errors.

### 4. API historical floors are universally NULL because no authority-eligible source exists

**Database:** `market_live`. **Confidence:** high; policy outcome rather than demonstrated price parser error.

**3311/3311 current deals** have NULL historical_floor_usd. All **114 registered sources** have trust tier >2 or NULL (**0 tier≤2**); **0/59973 traceable observations** meet floor authority predicate `authority_tier<=2`. Even direct retailer sources Central Computers, ServerPartDeals, Water Panther have tier 3. Hence historical price data exists but this consumer cannot use any of it for floors/at-or-below-floor. Whether trust tiers are unintended requires policy confirmation.

### 5. Provenance exclusions include offer-item identity drift, not missing ingestion

**Database:** `market_live`. **Confidence:** high.

**955/60928 observations** excluded from traceable view:
- diskprices: **542/25755**, all observation/offer item mismatch.
- Central Computers: **229/11430**, same.
- Water Panther: **42/5018**, same.
- eBay: **141/141**, all missing item entity IDs and offer item mismatch; 7 additionally no run.
- Liquidation battery hunt: **1/1**, no run.

No non-NULL artifact failed provenance-chain validation (**0**).

Example observation `1208f068-81ea-54d4-a354-440bb2166bf7`, offer `ac594f98-3ca7-5dcf-a859-59cd13755608`, diskprices $5500:
observation item `c82b8cdf-9778-55d4-aec4-b0fd5a9477c7` vs current offer item `7bb0c186-56a5-524f-942c-6a0d8775b6fa`.

Among **3316 raw latest observations otherwise satisfying API tracked/status/freshness/availability/price predicates**, **5** are excluded by traceability: diskprices **4/1584**, Central **1/1143**. Thus source rows exist; absent API deals must not be described as failed ingestion. Historical identity reassignment cause remains inference.

**techdeals_work:** **23467/23467 local observations have NULL run_id**, traceable count zero, artifacts zero. But **0/11176 offers are fresh**, so zero current deals is independently warranted by freshness; **11173 active**, **4604 eligible**. Work unified observations UNION local plus `market_live_fdw`, labeled origins local/market_live; remote rows are not a second independent local corpus.

### Null/zero outcomes

Both DBs: every market currency is USD; zero NULL prices, zero negative prices. No source currency correctness asserted solely from USD labels.
- market_live: **2/60928 zero prices**, both ServerPartDeals raw payload also price=0 and OutOfStock; not proven parser unit failure.
- work: **2/23467 zero prices**, DDR5 legacy rows; no raw source evidence to establish cause.
- work legacy shipping_cost>0: **0/23467**, so no verified shipping-loss case.
- market_live snapshots 776362; evidence artifacts 25566, mostly Garage rather than inline. Work has no live.listing_snapshots relation and zero evidence artifacts.

## Reproducible SQL

Run per DB using mandated read-only options. Queries below are the successful queries underlying findings (grouped compactly).

```sql
-- Both DBs: population, currencies, missing price/run data.
SELECT s.source_name,count(*) n,
 count(*) FILTER(WHERE m.currency IS DISTINCT FROM 'USD') nonusd,
 count(*) FILTER(WHERE m.price_usd<=0) nonpositive,
 count(*) FILTER(WHERE m.price_usd IS NULL) nullprice,
 count(*) FILTER(WHERE m.run_id IS NULL) no_run,
 min(m.observed_at),max(m.observed_at)
FROM core.market_observations m
JOIN source.sources s USING(source_id)
GROUP BY 1 ORDER BY n DESC;

-- market_live: quantity errors, history/current prevalence, exact retained source lines.
SELECT m.offer_id,count(*) observations,min(m.price_usd),max(m.price_usd),
 m.raw_payload->>'quantity' quantity,m.raw_payload->>'source_line' line,
 count(*) FILTER(WHERE d.observation_id IS NOT NULL) current_n
FROM core.market_observations m
JOIN source.sources s USING(source_id)
LEFT JOIN api.current_deals d USING(observation_id)
WHERE s.source_name='Reddit r/hardwareswap'
 AND (m.raw_payload->>'quantity')::numeric>1
GROUP BY 1,5,6 ORDER BY 1;

SELECT ls.snapshot_id,ls.run_id,ls.source_listing_key,ls.raw_json
FROM live.listing_snapshots ls
WHERE ls.run_id='44b857c6-adee-4c32-b7e8-3172739eab2d'
AND ls.source_listing_key='reddit:hardwareswap:1wtjgjw:07cf67363c20e397';

SELECT m.observation_id,m.offer_id,m.raw_payload,a.artifact_id,
 a.storage_backend,a.storage_uri,a.content_type,a.content_length_bytes,a.metadata
FROM core.market_observations m
JOIN evidence.artifacts a USING(artifact_id)
WHERE m.observation_id IN
 ('4e301e3f-f556-5fa2-adc6-6de1c777f662',
  'd03ae962-dd9d-5ef5-8895-19cc39f1c5c9');

SELECT source_name,count(*) total,
 count(*) FILTER(WHERE availability ~* 'out[_ ]?of[_ ]?stock') unavailable,
 count(*) FILTER(WHERE historical_floor_usd IS NULL) nullfloor
FROM api.current_deals GROUP BY 1 ORDER BY 1;

SELECT d.observation_id,d.offer_id,d.availability,d.price_usd,d.source_title,
 o.listing_status,o.eligible_for_current_deals,o.unavailable_at
FROM api.current_deals d JOIN core.offers o USING(offer_id)
WHERE d.availability='out_of_stock';

SELECT count(*) FILTER(WHERE trust_tier<=2) floor_sources,count(*) sources
FROM source.sources;
SELECT count(*) priced,count(*) FILTER(WHERE authority_tier<=2) floor_eligible
FROM api.traceable_market_observations;

-- Both DBs: history-price preservation and availability loss.
SELECT count(*) price_rows,
 count(*) FILTER(WHERE NOT EXISTS(
  SELECT 1 FROM core.market_observations m
  WHERE m.offer_id=p.offer_id AND m.observed_at=p.observed_at
   AND m.price_usd IS NOT DISTINCT FROM p.price_usd)) missing_market
FROM core.price_observations p;

SELECT s.source_name,count(*) history,
 count(*) FILTER(WHERE p.available_at_observation=false) unavailable,
 count(*) FILTER(WHERE p.available_at_observation=false
  AND COALESCE(m.availability,'') !~*
   '(out of stock|unavailable|sold out|expired)') read_as_available
FROM core.price_observations p
JOIN core.offers o USING(offer_id)
JOIN source.sources s USING(source_id)
JOIN core.market_observations m
 ON m.offer_id=p.offer_id AND m.observed_at=p.observed_at
 AND m.price_usd IS NOT DISTINCT FROM p.price_usd
GROUP BY 1 ORDER BY 4 DESC;

SELECT s.source_name,count(*) unavailable_latest,
 count(*) FILTER(WHERE lp.available_at_observation) incorrectly_available
FROM core.price_observations p
JOIN core.latest_prices lp
 ON lp.offer_id=p.offer_id AND lp.observed_at=p.observed_at
JOIN core.offers o ON o.offer_id=p.offer_id
JOIN source.sources s ON s.source_id=o.source_id
WHERE p.available_at_observation=false GROUP BY 1;

SELECT count(*) FILTER(WHERE p.observation_kind IS DISTINCT FROM
 lp.observation_kind) changed_kind,count(*) total
FROM core.price_observations p
JOIN core.latest_prices lp
 ON lp.offer_id=p.offer_id AND lp.observed_at=p.observed_at;

SELECT count(*) history,
 count(*) FILTER(WHERE lp.offer_id IS NULL) missing_from_latest
FROM core.price_observations p
LEFT JOIN core.latest_prices lp USING(offer_id);

-- market_live: exclusions and proved mismatch causes.
SELECT s.source_name,count(*) excluded,
 count(*) FILTER(WHERE NOT EXISTS(
  SELECT 1 FROM core.entities e WHERE e.entity_id=m.item_entity_id
   AND e.entity_kind='item' AND e.native_id=m.item_id)) bad_item_entity,
 count(*) FILTER(WHERE NOT EXISTS(
  SELECT 1 FROM core.offers o WHERE o.offer_id=m.offer_id
   AND o.item_id=m.item_id AND o.source_id=m.source_id)) offer_identity_mismatch,
 count(*) FILTER(WHERE NOT EXISTS(
  SELECT 1 FROM workflow.collection_runs r
  WHERE r.run_id=m.run_id)) missing_run
FROM core.market_observations m JOIN source.sources s USING(source_id)
LEFT JOIN api.traceable_market_observations t USING(observation_id)
WHERE t.observation_id IS NULL GROUP BY 1;

SELECT s.source_name,count(*) total,
 count(*) FILTER(WHERE t.observation_id IS NULL) excluded
FROM (SELECT DISTINCT ON(offer_id) * FROM core.market_observations
 ORDER BY offer_id,observed_at DESC,observation_id DESC) m
JOIN source.sources s USING(source_id)
JOIN core.offers o USING(offer_id)
JOIN core.items i ON i.item_id=m.item_id
JOIN core.categories c ON c.category_id=i.category_id
LEFT JOIN api.traceable_market_observations t USING(observation_id)
WHERE c.tracked AND o.listing_status='active'
 AND m.observed_at>=now()-make_interval(days=>c.freshness_days)
 AND COALESCE(m.availability,'') !~*
 '(out of stock|unavailable|sold out|expired)'
 AND COALESCE(m.source_effective_price_usd,m.price_usd) IS NOT NULL
GROUP BY 1 ORDER BY 3 DESC;

-- Both DBs: eligibility/freshness, authoritative definitions.
SELECT count(*) total,
 count(*) FILTER(WHERE o.last_observed_at >=
  now()-make_interval(days=>c.freshness_days)) fresh,
 count(*) FILTER(WHERE o.listing_status='active') active,
 count(*) FILTER(WHERE o.eligible_for_current_deals) eligible
FROM core.offers o JOIN core.categories c USING(category_id);

SELECT schemaname,viewname,definition FROM pg_views
WHERE schemaname IN ('core','api')
AND viewname IN ('latest_prices','market_observation_prices',
 'current_deals','traceable_market_observations','deal_floor',
 'offer_price_metrics','unified_market_observations','unified_deal_floor');
```