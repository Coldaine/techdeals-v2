## Per-field hit rates

| field | applicable | hit | miss | hit rate |
|---|---|---|---|---|
| cpu_model | 17 | 17 | 0 | 100% |
| ram_total_gb | 9 | 9 | 0 | 100% |
| price_usd | 19 | 19 | 0 | 100% |
| chassis_model | 6 | 6 | 0 | 100% |
| listing_status | 19 | 19 | 0 | 100% |

Outcome split over 20 scored results: 19 extracted, 1 quarantined/no-info.

## Per-listing score table

| item_id | cpu_model | ram_total_gb | price_usd | chassis_model | listing_status |
|---|---|---|---|---|---|
| 115876998802 | hit | hit | hit | na | hit |
| 116572740961 | na | na | hit | hit | hit |
| 117083098586 | hit | na | hit | na | hit |
| 117173565052 | hit | hit | hit | hit | hit |
| 117219265177 | hit | hit | hit | na | hit |
| 117303596450 | hit | hit | hit | hit | hit |
| 117303596488 | hit | hit | hit | hit | hit |
| 117303596513 | hit | hit | hit | hit | hit |
| 117303596603 | hit | hit | hit | hit | hit |
| 126472428668 | hit | hit | hit | na | hit |
| 126718876005 | hit | na | hit | na | hit |
| 127199933537 | hit | hit | hit | na | hit |
| 127212119662 | hit | na | hit | na | hit |
| 127212226077 | hit | na | hit | na | hit |
| 127220408839 | quarantined | quarantined | na | quarantined | quarantined |
| 127462928151 | hit | na | hit | na | hit |
| 127540686442 | hit | na | hit | na | hit |
| 127552535357 | hit | na | hit | na | hit |
| 127554847495 | na | na | hit | na | hit |
| 127608523462 | hit | na | hit | na | hit |

## Misses (with raw title)

  (cpu_model: +1 quarantined-listing cells, see below)
  (ram_total_gb: +1 quarantined-listing cells, see below)
  (chassis_model: +1 quarantined-listing cells, see below)
  (listing_status: +1 quarantined-listing cells, see below)

## Quarantined-listing cells (human read them; capture was a dead page)

- **cpu_model** `127220408839` human=`EPYC 7543` engine=unparseable — Dell PowerEdge R6515 1 x 32 Core 2.8GHz AMD EPYC 7543 256GB 10x 1.92TB NVMe S150
- **ram_total_gb** `127220408839` human=`256.0` engine=unparseable — Dell PowerEdge R6515 1 x 32 Core 2.8GHz AMD EPYC 7543 256GB 10x 1.92TB NVMe S150
- **chassis_model** `127220408839` human=`PowerEdge R6515` engine=unparseable — Dell PowerEdge R6515 1 x 32 Core 2.8GHz AMD EPYC 7543 256GB 10x 1.92TB NVMe S150
- **listing_status** `127220408839` human=`ended` engine=unparseable — Dell PowerEdge R6515 1 x 32 Core 2.8GHz AMD EPYC 7543 256GB 10x 1.92TB NVMe S150
(no misses on applicable fields)

## Not-applicable notes (engine answered where human read nothing)

