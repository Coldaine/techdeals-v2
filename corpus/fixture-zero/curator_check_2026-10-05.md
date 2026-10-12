# Curator check of servers_read.jsonl vs raw pages (2026-10-05 ~9:50 PM CT)
Method: all 376 rows screened against raw (field value present in raw text; SKU core/family table; 1P-platform socket count; DIMM math; price); 72 screened hits; ~20 hits + 20 random clean rows read by hand against raw.

Fix before lock:
1. ram_type/ram_kind filled from "board supports DDR4 RDIMM" text where no RAM is included: 113 rows have ram_type with no RAM qty (62 explicitly board-support). Blank them or move to board_ram_support.
2. 227373919049 price_usd 4250 — raw page price is $4,690; 4250 appears nowhere in raw.
3. EPYC 7B13 (Milan, 64C): identical seller text read three ways. 176118710627 and 318885898683 have cpu_family "Rome 7002"; 134147346048 and 176118710627 have 60 cores (seller-note typo). Family/cores should follow the SKU, with the typo kept as a conflict.
4. 7402P "28-core" (227440010823, 336698173658, 364335404366, 800379470041): page typo, SKU is 24C. Same rule as 3.
5. 315097585172: description says 8x 64GB SK hynix 3200 2Rx8/2Rx4; ram_dimm_count/gb left blank.

Correctly handled: 2x 7T83 on H12SSL-i (5 rows) flagged as conflict; R6515 7313P; R7515 7H12; 377236783982 configurator base variant (7282, 2x16GB, $4,881.93); 305515009235 uses sale price $4,306.99 (listing out_of_stock).
Random 20: no other errors found.
