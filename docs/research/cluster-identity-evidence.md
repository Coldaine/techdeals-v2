## Identity/configuration audit: live PostgreSQL databases

Investigated **`market_live` and `techdeals_work` on `pg18-core-db.moosegoose.xyz`**, SELECT-only with required read-only/timeouts. No repository or production changes. Counts below are separate query snapshots; live ingestion continued during investigation.

All inventory counts use **local base tables**, not `market_live_fdw` or unified views. Confirmed `techdeals_work.market_live_fdw.items/offers/market_observations` are foreign tables and excluded them.

### Confirmed findings

#### 1. `market_live`: RAM actually stored as CPUs/GPUs

**5/476 CPU items and 1/347 GPU items** have structured observation evidence identifying RAM: `technology=DDR4/DDR5`, `form_factor=RDIMM/UDIMM/SODIMM`, and explicit module capacities. This is **not title-only classification**.

| Stored category | Item ID | Structured source evidence |
|---|---|---|
| CPU | `3d78bca3-859d-573c-9b70-12ded76e8243` | DDR4 RDIMM, `8 GB x2`; A-Tech RAM kit |
| CPU | `863d8290-5557-5fc5-8e40-1082a66f3de1` | DDR4 RDIMM, `16 GB`; A-Tech module |
| CPU | `45f973a5-6d24-52a5-8457-f028f75189bf` | DDR5 UDIMM, `64 GB x2`; Crucial Pro kit |
| CPU | `b502b9bf-ce9f-5a7d-b525-a025d73eafb6` | DDR5 RDIMM, `96 GB`; Kingston-compatible module |
| CPU | `7690e2cb-0f37-5f27-a5b3-bf8d26f2a70b` | DDR4 RDIMM, `64 GB`; parts-quick module |
| GPU | `6e67469f-9702-59eb-aaaa-9d60a700d993` | DDR4 SODIMM, `32 GB x2`; A-Tech kit |

Representative persistent traces:

- CPU RAM kit: offer `266507c8-ea5f-5d5f-8262-743036357720`, observation `5bef3a79-0024-5288-a577-ee2db7c4dcc4`, artifact `3d7e7fd8-7daa-4a91-819b-5fd7e157fce4`.
- GPU RAM kit: offer `41b8428f-0351-56e0-bdd4-516fb53b3b87`, observation `d585ebeb-bb66-5142-a5e1-9cc0ba962dca`, artifact `ead84bea-ca81-458b-874e-3f92a2d7675b`.
- GPU kit is stored with **`compute.gpu_specs.vram_gb=64`**. Assertion `01a01ff8-ac81-70c4-9fea-37fb78a10fb5` sets `memory.capacity_gb=64`, with metadata explicitly naming projection column `vram_gb`, parser `diskprices.parse_html`, provenance `verified`. It is **selection-eligible and selected**, not quarantined.
- CPU kit model assertion `01a092fc-9439-7247-a1aa-0c4d2b95961d` stores model **`2 x for Dell`**.

**Impact:** RAM appears under processor/graphics categories; GPU capacity filtering can present a SODIMM kit as 64GB VRAM.  
**Confidence:** high. **Cause:** category detection being diverted by compatibility mentions of Xeon/CPU/GeForce is **[INFERENCE]**, not proven from code.

`techdeals_work`: **0/162 CPU and 0/39 GPU items** matched this structured-evidence predicate. This does not establish universal correctness: its local observations generally contain legacy backfill payloads rather than equivalent structured product facts.

#### 2. `market_live`: ten memory identities merge different module configurations

**10/1,428 memory items**, out of **630 items with module-count assertions**, have conflicting module-count assertions. For **all ten**, latest observations attached to the same item also contain two distinct structured `capacity_raw` configurations:

| Item ID | Configurations merged |
|---|---|
| `1b73686e-1384-5126-b9c7-fb70f71d7cb3` | `16 GB` / `8 GB x2` |
| `4f37f8a2-d53f-5f3c-b641-b8891c7c7b4c` | `8 GB` / `4 GB x2` |
| `860970e8-35a4-56f5-a49e-ebbeeb127139` | `16 GB` / `8 GB x2` |
| `9bdf2ffd-bc95-5d23-a1d4-3278e210ec06` | `16 GB x2` / `8 GB x4` |
| `9c82f3a3-e626-51ad-abd2-75597b8ce654` | `16 GB` / `8 GB x2` |
| `b8488773-df60-561d-aee5-a25522e64df9` | `16 GB x2` / `8 GB x4` |
| `b9b18a72-7a9a-5630-a0f3-533500ce54a6` | `32 GB x8` / `64 GB x4` |
| `d279ac16-4bfd-530f-955f-fade26a6e029` | `16 GB x2` / `8 GB x4` |
| `de498bea-3ecf-5cbc-a721-a38144fcc5e6` | `32 GB x4` / `64 GB x2` |
| `f04fddcd-ffb8-5013-a1d1-bff1ff6f9d9e` | `16 GB x4` / `32 GB x2` |

Detailed example: `860970e8-35a4-56f5-a49e-ebbeeb127139`:

- Canonical name: Corsair **1×16GB C18**, model `CMK16GX4M1Z3600C18`.
- Typed specs: module count **1**, per-module **16GB**, total **16GB**.
- Offer `d31f9e1a-52b7-574f-ac84-10e40e5d78fb`, observation `8879b4f6-e1e5-5ff2-b9bd-b31b399d405d`: `capacity_raw="16 GB"`, source ASIN `B08D6GKX3J`.
- Offer `c41e0894-a1f2-5d04-a9bd-167ac1b0aca1`, observation `be31ef27-7cd0-5cd6-bd64-753e5cf5885b`: `capacity_raw="8 GB x2"`; source title specifies **2×8GB C16**, ASIN `B08PW3RDPN`.
- Assertions `01a0a427-ca07-7607-9a74-6636827a04c1` and `01a0a427-cc02-7b33-aca1-c848c4867d13` respectively assert module counts **2** and **1**, with a `value_mismatch` conflict.
- Latest selected module-count assertion `01a1345c-5b44-7384-9028-83264f48abf8` chooses **1** despite `is_conflicted=true`.

**Impact:** a two-slot kit and a single-module product share canonical specs, price history, and identity; the example also conflates C16/C18 source descriptions. Choosing one assertion cannot repair the incorrect identity grain.

**Confidence:** high from structured capacities, separate source identifiers, and source titles. The identity key contains total capacity/speed but not module quantity; attributing the merge algorithm specifically to that omission remains **[INFERENCE]**.

`techdeals_work`: **0 module-count assertions**, so no comparable assertion-conflict count exists there.

#### 3. `market_live`: mixed RAM+SSD bundles lose decomposition and merge SSD sizes

- **13/1,428 memory items** explicitly describe `Bundle with ... SSD`.
- **0 item components and 0 variants globally** in this database.
- **3/13 bundle items** attach offers naming different included SSD capacities:

  - `1b8613a1-86b4-531d-b093-fa6c18ebd4c6`
  - `d7abd357-572c-59e4-8577-0a38224e41a7`
  - `dc59b059-10d5-538c-9f6c-ac2ab2603c98`

Strong trace for the first:

- Canonical bundle includes CARDEA A440 **2TB SSD**.
- Offer `8e57a072-e687-5037-8824-5087977730f1`, observation `44a709c5-64c0-5ea1-ac20-cae66e73e748`, raw payload title names **2TB**, part `TM8FPZ002T0C`, ASIN `B0D46F6XTQ`.
- Offer `f19aaad3-13b8-5128-8b31-9b255b26479d`, observation `6fcb565c-a4dc-5e27-9de4-8ecd12919c0e`, raw payload title names **1TB**, part `TM8FPZ001T0C`, ASIN `B0D45HH5S1`.
- Both attach to the same RAM item.

**Impact:** whole-bundle prices are compared under one RAM identity despite differing included SSDs; no component/variant record represents the difference. The existence of a bundle itself is valid; **merging distinct bundles is the error**.

**Confidence:** high that stored source representations differ; SSD inclusion evidence is source-title text preserved in observations, not independently fetched manufacturer specifications.

#### 4. `techdeals_work`: RAM lots store per-module capacity as total lot capacity

`memory.ram_specs` has **0 rows**. Local legacy RAM data instead lives in `memory.ddr5_rdimm_specs`: **543 rows**, **440 missing module count or per-module capacity**.

Among its **9 “lot of” listings**, **all 9** store the first per-module capacity as `total_capacity_gb`, with `module_count=NULL`. Particularly explicit contradictions:

| Item ID | Stored total | Source representation |
|---|---:|---|
| `6e8d91cc-3b2a-5ab6-b6c4-c5ca0b33b426` | 64GB | “LOT OF 3 … 64GB … **(192GB)**” |
| `8b13a2e1-f53f-5a94-88e1-0ee171b378e5` | 128GB | “128GB … lot of 8 **(1024GB …)**” |
| `b67671b8-bf04-5984-8026-b8522bc8a050` | 64GB | “64GB … lot of 8 **(512GB)**” |
| `2e74e384-ac7c-5cd5-b387-a00b5314e9c2` | 32GB | “LOT OF 12 … 32GB” — stated quantity implies 384GB |

Representative offers:

- `260335ee-916b-57d1-bf65-b143949afa7e`: 3×64GB; **no URL**, notes identify `user_supplied_manual_summary`.
- `e28dcc98-ab10-5840-92a8-209e2ded6eee`: 8×128GB; https://www.ebay.com/itm/206044823718
- `95f2cf4c-bce1-5d59-9acd-f4a333e4432c`: 12×32GB; https://www.ebay.com/itm/327118046406

No `memory.capacity_gb` assertions were present for these sampled lot items. Latest decisions for the first two are `needs_review`, “identity backfill: insufficient_native_facts” (`019fa6de-dd58-73ec-ac13-a34f8e4fd831`, `019fa6de-e5f1-72d3-b28b-a3d79ac85897`).

**Impact:** stored “total” is unsuitable for lot capacity comparison; however **do not claim an exercised price/GB inflation**. Actual work DB `core.offer_price_metrics` and `core.deal_ready_ddr5` join the **empty `memory.ram_specs`**, not these legacy rows, so their memory denominator/readiness path is absent instead.

**Confidence:** high for internal disagreement, strongest where the source explicitly states aggregate capacity; **title/manual-summary evidence only**, not verified current eBay product content.

#### 5. Malformed processor/configuration fields

**`market_live`: 7/130 mini-PC configs** have `cpu_model` containing RAM/SSD or truncated core/thread prose.

Example `2b531978-2491-5c38-8682-696e077fee1b` stores **`i5-12600H 32GB RAM 1TB SSD`** as CPU model. Assertion `019fa6b9-4fe3-7130-ae4a-2313eeea8909` simply backfills that same value from `compute.mini_pc_configs`; it is `legacy_unverified`, `needs_evidence`, **not selection-eligible**.

**Impact:** typed CPU comparisons/identity derivation are polluted. The assertion layer correctly withholds this legacy assertion; it does not make the base projection correct. **Confidence:** high, no external hardware assumption needed.

**`techdeals_work`: 13/61 mini-PC configs with explicit GB storage in their names** disagree with `storage_gb`, excluding **1024GB title versus 1000GB stored** as a capacity-convention difference. Denominator is **1,007 configs** overall.

Examples:

- `277d4be6-27a9-532c-ba74-cae9855676f4`: title/source offer says **512GB SSD**, stored **1000GB**.
  - Offer `31115d7d-8ecd-50fb-8531-690fad899cbc`.
  - Variant `019ef920-e08a-776a-943e-0394f3f513a4` repeats the 512GB title.
  - Assertion `019fa6b9-3bad-77f7-b962-5e9b89ee796a` backfills **1000GB**.
- `9b33b252-6337-52c6-8b60-8b37923583a5`: title/source says **256GB**, stored **1000GB**.
  - Offer `15a7b32d-537e-5879-becb-be235bbbd6f4`.
  - Variant `019ef920-e067-7444-8dbb-941e55c2c218`.
  - Assertion `019fa6b9-3baa-71a3-999a-75a586ffa89b`.

Latest observations only contain `{"backfill_source":"price_observations"}`; no associated `workflow.raw_intake` rows were found for these examples. Assertions are `needs_evidence`, not selected. **Confidence:** high internal contradiction, **limited title evidence for the true purchased configuration**.

Also **57/4,695 `techdeals_work` rack-server items** are explicitly titled lots of CPUs/processors; all have rack configs. Example `02c40ef3-35d4-5b6c-b549-b4af8b875d09`, offer `9dfe34e2-01de-54c6-b53b-4b723b84ae18`, says **“Lot of 50 Intel Xeon E5-2630 v3 … Processors SR206”**, source URL is the matching TechMikeNY processor-lot path. Rack config has no CPU model/RAM; intake decision `019fa6de-c2c5-7abc-8102-c2b08c3b4c07` remains `needs_review`.

**Impact:** CPU lots inhabit server inventory; absence of decomposition means lot quantity is not represented as components. **Confidence:** high category disagreement from explicit product wording/path, but source evidence is title-level.

### Important zero/expected-unresolved outcomes

- **No arithmetic mismatch** where module count and per-module capacity are both stored:
  - `market_live.memory.ram_specs`: **0/1,426**.
  - `techdeals_work.memory.ddr5_rdimm_specs`: **0/543**.
- `market_live`: **796/1,426 RAM rows** lack count/per-module capacity. Four explicit `N×GB` titles still have null quantities; e.g. `0cca38bc-bfce-5b4c-a6ea-06207de016d1` “Single … (1×16GB).” Latest intake decision is appropriately `needs_review`; missing facts are not invented wrong quantities.
- `max_ram_gb` is **NULL in all 130 market and all 1,007 work mini-PC configs**; `barebones_or_configured` is also entirely NULL. Therefore **0 installed-above-stored-max cases is vacuous**, not proof of correct capability modeling.
- Market rack configs: **8/62** explicitly name an integer-valued RAM support maximum; **0/8** store that maximum as installed RAM. Example HPE item `9a6e316f-d699-5a20-8884-9b3a02450dca`: **16GB installed**, **128GB supported** in the source title; stored RAM is correctly 16GB. No confirmed supported-max→installed-RAM error found.
- Work assertion layer: **37,416/37,416 assertions** are `legacy_unverified`/`needs_evidence`, **0 selected**, **0 conflict rows**. This is deliberate withholding, **not 37,416 confirmed incorrect facts**.
- Work variants: **10,078**, one per item; **10,044** are `legacy_item_id` wrappers, **0 orphan items**. **712 category mismatches** consist of 695 `memory` items retaining variant category `ddr5_rdimm`, 14 SSD/3 HDD items retaining `deal_item`. These are observable stale category representations; not evidence of 712 incorrect product merges.
- No conclusion was drawn from partial collection status.

### Parent’s tray example

Confirmed offer `0d08b78a-b577-576a-a2fe-8b912817100a` points to item `33fb7333-cb85-5a3f-9cb0-88600d3e17e5`: offer title **13G Tray**, item canonical name **14G Tray**. Key is `ssd|water-panther|sas-4-s-2-5-for|6.4E+3gb`; there is no variant. This demonstrates lost compatibility grain in stored representation, alongside the parent’s raw observation evidence—not duplicate entity IDs.

## Exact reproducibility SQL

Run the common queries in **both databases**. Memory legacy queries are explicitly database-specific.

```sql
-- Column discovery used before querying.
SELECT table_schema, table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema IN ('core','compute','memory','evidence','workflow')
ORDER BY table_schema, table_name, ordinal_position;

-- Local vs foreign relation identity.
SELECT n.nspname,c.relname,c.relkind
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname IN ('core','compute','memory','market_live_fdw')
  AND c.relname IN
 ('items','offers','market_observations','item_variants','item_component',
  'mini_pc_configs','rack_server_configs','cpu_specs','gpu_specs','ram_specs');

-- Structured RAM in CPU/GPU categories.
WITH x AS (
 SELECT DISTINCT i.item_id,i.category_id
 FROM core.items i JOIN core.market_observations m USING(item_id)
 WHERE i.category_id IN ('cpu','gpu')
 AND m.raw_payload->>'technology' IN ('DDR3','DDR4','DDR5')
 AND m.raw_payload->>'form_factor'
     IN ('RDIMM','LRDIMM','UDIMM','SODIMM','DIMM')
)
SELECT i.category_id,count(*) all_category_items,
 count(*) FILTER(WHERE x.item_id IS NOT NULL) structured_ram_in_category
FROM core.items i LEFT JOIN x USING(item_id,category_id)
WHERE i.category_id IN ('cpu','gpu')
GROUP BY 1 ORDER BY 1;

-- Quantity-conflict denominator and affected IDs.
WITH x AS (
 SELECT i.item_id,count(DISTINCT a.value_integer) counts
 FROM core.items i JOIN evidence.assertions a
 ON a.entity_id=i.entity_id AND a.attribute_key='memory.module_count'
 WHERE i.category_id='memory' GROUP BY 1
)
SELECT (SELECT count(*) FROM core.items WHERE category_id='memory') all_memory,
 count(*) with_quantity_assertions,
 count(*) FILTER(WHERE counts>1) conflicting_quantity_items
FROM x;

-- Structured source confirmation for every quantity-conflicted item.
WITH x AS (
 SELECT i.item_id FROM core.items i JOIN evidence.assertions a
 ON a.entity_id=i.entity_id AND a.attribute_key='memory.module_count'
 WHERE i.category_id='memory'
 GROUP BY 1 HAVING count(DISTINCT a.value_integer)>1
), y AS (
 SELECT x.item_id,o.offer_id,o.source_title_raw,
        m.raw_payload->>'capacity_raw' cap
 FROM x JOIN core.offers o USING(item_id)
 LEFT JOIN LATERAL (
  SELECT raw_payload FROM core.market_observations
  WHERE offer_id=o.offer_id ORDER BY observed_at DESC LIMIT 1
 ) m ON true
)
SELECT item_id,count(*) offers,count(DISTINCT cap) distinct_caps,
 string_agg(DISTINCT cap,';') capacities
FROM y GROUP BY 1 ORDER BY 1;

-- General source/assertion trace. Substitute any item ID above.
SELECT i.item_id,i.category_id,i.canonical_name,i.identity_key,
 o.offer_id,o.source_title_raw,o.source_url,
 m.observation_id,m.artifact_id,m.raw_payload
FROM core.items i LEFT JOIN core.offers o USING(item_id)
LEFT JOIN LATERAL (
 SELECT observation_id,artifact_id,raw_payload
 FROM core.market_observations WHERE offer_id=o.offer_id
 ORDER BY observed_at DESC LIMIT 1
) m ON true
WHERE i.item_id='860970e8-35a4-56f5-a49e-ebbeeb127139';

SELECT a.*
FROM evidence.assertions a JOIN core.items i ON i.entity_id=a.entity_id
WHERE i.item_id='860970e8-35a4-56f5-a49e-ebbeeb127139'
ORDER BY a.attribute_key,a.observed_at DESC;

SELECT assertion_id,attribute_key,typed_value,is_conflicted,selection_eligible
FROM evidence.assertion_candidates
WHERE entity_id='860970e8-35a4-56f5-a49e-ebbeeb127139'
AND attribute_key='memory.module_count'
ORDER BY observed_at DESC LIMIT 4;

SELECT assertion_id,attribute_key,typed_value
FROM evidence.selected_assertions
WHERE entity_id='860970e8-35a4-56f5-a49e-ebbeeb127139'
AND attribute_key='memory.module_count';

-- Conflict sample / relevant conflict-row count, market_live.
SELECT c.*,a.attribute_key,a.value_integer,b.value_integer b_integer
FROM evidence.assertion_conflicts c
JOIN evidence.assertions a ON a.assertion_id=c.assertion_id
JOIN evidence.assertions b ON b.assertion_id=c.conflicting_assertion_id
WHERE a.attribute_key='memory.module_count' LIMIT 5;

SELECT c.conflict_kind,c.status,count(*)
FROM evidence.assertion_conflicts c
JOIN evidence.assertions a ON a.assertion_id=c.assertion_id
WHERE a.attribute_key IN
 ('memory.module_count','memory.module_capacity_gb','compute.cpu_model')
GROUP BY 1,2 ORDER BY 3 DESC;

-- Mixed bundle denominator/merges.
WITH x AS (
 SELECT i.item_id,
 count(DISTINCT
  (regexp_match(o.source_title_raw,'([0-9]+)[ ]*TB.{0,80}SSD','i'))[1]
 ) ssd_sizes
 FROM core.items i JOIN core.offers o USING(item_id)
 WHERE i.category_id='memory'
 AND i.canonical_name ~* 'bundle with' AND i.canonical_name ~* 'SSD'
 GROUP BY 1
)
SELECT count(*) bundle_items,
 count(*) FILTER(WHERE ssd_sizes>1) merged_distinct_ssd_sizes FROM x;

SELECT count(*) FROM core.item_component;
SELECT count(*) FROM core.item_variants;

-- Known quantity arithmetic and unknowns; both databases.
SELECT count(*) n,
 count(*) FILTER(WHERE capacity_gb_per_module*module_count<>total_capacity_gb)
 arithmetic_mismatch,
 count(*) FILTER(WHERE module_count IS NULL OR capacity_gb_per_module IS NULL)
 unknown_quantity
FROM memory.ram_specs;

-- techdeals_work legacy quantities.
SELECT count(*) n,
 count(*) FILTER(WHERE module_count*capacity_gb_per_module<>total_capacity_gb)
 arithmetic_mismatch,
 count(*) FILTER(WHERE module_count IS NULL OR capacity_gb_per_module IS NULL)
 unknown_quantity
FROM memory.ddr5_rdimm_specs;

WITH x AS (
 SELECT i.item_id,i.canonical_name,r.total_capacity_gb,r.module_count,
 regexp_match(i.canonical_name,'lot of[ ]+([0-9]+)','i') n,
 regexp_match(i.canonical_name,'([0-9]+)[ ]*GB','i') g
 FROM core.items i JOIN memory.ddr5_rdimm_specs r USING(item_id)
 WHERE i.canonical_name ~* 'lot of'
)
SELECT count(*) titled_lots,
 count(*) FILTER(WHERE n IS NOT NULL AND g IS NOT NULL
 AND total_capacity_gb=g[1]::int AND n[1]::int>1)
 stored_per_module_as_total,
 count(*) FILTER(WHERE module_count IS NULL) unknown_modules
FROM x;

-- Malformed CPU models.
SELECT count(*) total_configs,
 count(*) FILTER(WHERE cpu_model ~* '(RAM|SSD|Cores|Thre)') malformed_models
FROM compute.mini_pc_configs;

-- Explicit title/config disagreements, excluding 1024/1000 convention.
WITH x AS (
 SELECT c.*,i.canonical_name,
 regexp_match(i.canonical_name,'([0-9]+)[ ]*GB[ ]+(RAM|DDR[345])','i') ram,
 regexp_match(i.canonical_name,
  '([0-9]+)[ ]*GB[ ]+(M[.]2[ ]+)?(SSD|PCIe)','i') st
 FROM core.items i JOIN compute.mini_pc_configs c USING(item_id)
)
SELECT count(*) configs,
 count(*) FILTER(WHERE ram IS NOT NULL) explicit_ram_titles,
 count(*) FILTER(WHERE ram IS NOT NULL AND ram_gb<>ram[1]::int)
 ram_disagreement,
 count(*) FILTER(WHERE st IS NOT NULL) explicit_storage_titles,
 count(*) FILTER(WHERE st IS NOT NULL AND storage_gb<>st[1]::int
 AND NOT(storage_gb=1000 AND st[1]='1024')) storage_disagreement
FROM x;

-- Processor lots miscategorized as rack servers.
SELECT count(*) all_rack,
 count(*) FILTER(WHERE canonical_name ~*
 '^Lot of [0-9]+.*(Processors|CPU)') processor_lots
FROM core.items WHERE category_id='rack_server';

-- Capability/installed distinction.
SELECT count(*) configs,
 count(*) FILTER(WHERE max_ram_gb IS NOT NULL) known_maximum,
 count(*) FILTER(WHERE barebones_or_configured IS NOT NULL) known_configuration,
 count(*) FILTER(WHERE ram_gb>max_ram_gb) installed_above_max
FROM compute.mini_pc_configs;

WITH x AS (
 SELECT c.ram_gb,
 regexp_match(i.canonical_name,
 '([0-9]+)[ ]*(GB|TB)[ ]+RAM[ ]+Support','i') max_ram
 FROM core.items i JOIN compute.rack_server_configs c USING(item_id)
)
SELECT count(*) rack_configs,
 count(*) FILTER(WHERE max_ram IS NOT NULL) explicit_max_titles,
 count(*) FILTER(WHERE max_ram IS NOT NULL AND ram_gb=
 CASE WHEN upper(max_ram[2])='TB' THEN max_ram[1]::int*1000
 ELSE max_ram[1]::int END) max_stored_as_installed
FROM x;

-- Variants and withholding.
SELECT count(*) variants,
 count(*) FILTER(WHERE variant_key ? 'legacy_item_id') legacy_wrappers,
 count(*) FILTER(WHERE i.item_id IS NULL) orphan_items,
 count(*) FILTER(WHERE v.category_id<>i.category_id) category_disagreements
FROM core.item_variants v LEFT JOIN core.items i USING(item_id);

SELECT i.category_id,v.category_id,count(*)
FROM core.item_variants v JOIN core.items i USING(item_id)
WHERE v.category_id<>i.category_id GROUP BY 1,2 ORDER BY 3 DESC;

SELECT count(*) assertions,
 count(*) FILTER(WHERE provenance_state='legacy_unverified') legacy_unverified,
 count(*) FILTER(WHERE review_state='needs_evidence') needs_evidence,
 count(*) FILTER(WHERE raw_source_value IS NULL) raw_null,
 count(*) FILTER(WHERE artifact_id IS NULL) artifact_null
FROM evidence.assertions;
SELECT count(*) selected FROM evidence.selected_assertions;
SELECT count(*) conflicts FROM evidence.assertion_conflicts;

-- Intake decisions for any example; substitute relevant persistent item IDs.
SELECT decision_id,intake_id,item_id,offer_id,scope_decision,category_id,
 reason,metadata
FROM workflow.intake_decisions
WHERE item_id IN (
 '6e8d91cc-3b2a-5ab6-b6c4-c5ca0b33b426',
 '8b13a2e1-f53f-5a94-88e1-0ee171b378e5',
 '277d4be6-27a9-532c-ba74-cae9855676f4',
 '02c40ef3-35d4-5b6c-b549-b4af8b875d09')
ORDER BY decided_at DESC;

-- Actual consumer joins, techdeals_work.
SELECT pg_get_viewdef('core.offer_price_metrics'::regclass,true);
SELECT pg_get_viewdef('core.deal_ready_ddr5'::regclass,true);
```