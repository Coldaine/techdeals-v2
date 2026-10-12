## Per-field hit rates

| field | applicable | hit | miss | hit rate |
|---|---|---|---|---|
| cpu_model | 51 | 51 | 0 | 100% |
| ram_total_gb | 21 | 18 | 3 | 86% |
| price_usd | 59 | 59 | 0 | 100% |
| chassis_model | 14 | 13 | 1 | 93% |
| listing_status | 59 | 59 | 0 | 100% |

Outcome split over 60 scored results: 59 extracted, 1 quarantined/no-info.

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
| 127822340628 | hit | na | hit | na | hit |
| 127822340867 | hit | na | hit | na | hit |
| 127822479792 | hit | na | hit | na | hit |
| 127851946605 | hit | na | hit | na | hit |
| 127852021044 | hit | na | hit | na | hit |
| 127910760440 | hit | na | hit | na | hit |
| 127910760470 | hit | na | hit | na | hit |
| 127910921547 | hit | na | hit | na | hit |
| 127916316802 | hit | hit | hit | na | hit |
| 127931129280 | hit | na | hit | na | hit |
| 127932828201 | hit | na | hit | na | hit |
| 127937947036 | hit | hit | hit | na | hit |
| 127940112860 | na | na | hit | hit | hit |
| 127940112864 | hit | hit | hit | hit | hit |
| 127940259331 | hit | hit | hit | hit | hit |
| 127941668776 | na | na | hit | hit | hit |
| 127956898826 | hit | hit | hit | na | hit |
| 127956898857 | hit | hit | hit | na | hit |
| 127956966556 | hit | na | hit | na | hit |
| 127959492006 | hit | na | hit | na | hit |
| 127959492196 | hit | na | hit | na | hit |
| 127976485478 | hit | miss | hit | na | hit |
| 127978020600 | hit | na | hit | na | hit |
| 127978236879 | hit | na | hit | na | hit |
| 128008832123 | hit | miss | hit | na | hit |
| 128071439116 | na | na | hit | na | hit |
| 128082143975 | hit | na | hit | na | hit |
| 128082759919 | hit | na | hit | na | hit |
| 128084558185 | hit | na | hit | na | hit |
| 128100032495 | hit | miss | hit | na | hit |
| 134147346048 | hit | na | hit | na | hit |
| 134707750284 | hit | na | hit | na | hit |
| 135210124717 | hit | na | hit | na | hit |
| 137291211126 | hit | hit | hit | hit | hit |
| 137350935318 | hit | hit | hit | hit | hit |
| 137428560780 | na | na | hit | na | hit |
| 137456445157 | hit | hit | hit | hit | hit |
| 137496550733 | na | na | hit | miss | hit |
| 137736518897 | na | na | hit | na | hit |
| 147620197777 | hit | na | hit | na | hit |

## Misses (with raw title)

  (cpu_model: +1 quarantined-listing cells, see below)
  (ram_total_gb: +1 quarantined-listing cells, see below)
- **ram_total_gb** `127976485478` human=`512.0` engine=`None` — Supermicro H12SSL-i Server Motherboard With AMD EPYC 7402 CPU，512GB 2666MHz RAM
- **ram_total_gb** `128008832123` human=`512.0` engine=`None` — Supermicro H12SSL-i Motherboard With AMD EPYC 7713 CPU, 8x64GB 2666MHz RAM
- **ram_total_gb** `128100032495` human=`256.0` engine=`None` — Supermicro H12SSL-i Motherboard With AMD EPYC 7413 CPU，8x32GB 2666MHz RECC RAM
  (chassis_model: +1 quarantined-listing cells, see below)
- **chassis_model** `137496550733` human=`ProLiant DL325 Gen10 Plus` engine=`ProLiant DL325 G10 Plus` — HPE ProLiant DL325 G10 Plus 8B SFF 1U CTO – No CPU Mem HDD
  (listing_status: +1 quarantined-listing cells, see below)

## Quarantined-listing cells (human read them; capture was a dead page)

- **cpu_model** `127220408839` human=`EPYC 7543` engine=unparseable — Dell PowerEdge R6515 1 x 32 Core 2.8GHz AMD EPYC 7543 256GB 10x 1.92TB NVMe S150
- **ram_total_gb** `127220408839` human=`256.0` engine=unparseable — Dell PowerEdge R6515 1 x 32 Core 2.8GHz AMD EPYC 7543 256GB 10x 1.92TB NVMe S150
- **chassis_model** `127220408839` human=`PowerEdge R6515` engine=unparseable — Dell PowerEdge R6515 1 x 32 Core 2.8GHz AMD EPYC 7543 256GB 10x 1.92TB NVMe S150
- **listing_status** `127220408839` human=`ended` engine=unparseable — Dell PowerEdge R6515 1 x 32 Core 2.8GHz AMD EPYC 7543 256GB 10x 1.92TB NVMe S150

## Not-applicable notes (engine answered where human read nothing)

- **chassis_model** `127822340628` engine=`H12SSL-i` (human left blank) — Supermicro H12SSL-i With AMD EPYC 7T83 Server CPU（7763 OEM Version Processors）
