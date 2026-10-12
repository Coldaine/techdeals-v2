# Read-the-raw spec (no regex parsing)

For each eBay item id in your batch file, open
/workspace/epyc-1p-mass-hunt-2026-10-05/raw/<item_id>.json and READ it the way a
human would: the title, product_specifications, description_from_the_seller /
description_from_the_seller_parsed / description, product_information, and the
variants/all_variations fields (when the listing has configurable options, record
the base config and list the options).

Output ONE JSON object per listing, one per line, to your batch_NN.out.jsonl.
Only record what the page states. If the page doesn't say something, set it to
null. Never guess. When the title and the description disagree, trust the
description, and note the conflict in `conflicts`.

Fields:
- item_id, url, title, price_usd, shipping_usd, condition, seller, seller_feedback, qty_available, qty_sold, item_location, listing_status (live/ended)
- chassis_vendor, chassis_model (e.g. PowerEdge R7515), chassis_gen (vendor's term, e.g. "Dell 15G" / "14th generation" as stated), form_factor_u, drive_bays_desc (e.g. "24x 2.5in SAS/SATA, up to 4 U.2 NVMe")
- motherboard: board model/part number if stated (e.g. "Supermicro H12SSL-i", Dell board PN). For OEM servers where no board is named, null + note "OEM board, not named".
- cpu_model (exact, e.g. "EPYC 7H12"), cpu_count, cpu_cores, cpu_threads, cpu_base_ghz, cpu_boost_ghz, cpu_tdp_w, cpu_family (Naples 7001 / Rome 7002 / Milan 7003 / Genoa 9004 / Intel gen)
- ram_total_gb, ram_dimm_count, ram_dimm_gb, ram_type (DDR4/DDR5), ram_kind (RDIMM/LRDIMM/3DS/UDIMM), ram_speed_mts, ram_rank (e.g. 2Rx4), ram_part_numbers, ram_slots_total, ram_notes (e.g. "registered ECC")
- drives: array of {count, capacity, unit, interface (SAS/SATA/NVMe U.2/M.2), type (HDD/SSD), rpm, notes}
- boot_device (BOSS, M.2, SD/IDSDM), raid_controller (model + cache, e.g. "PERC H740P 8GB NV cache w/ battery"), hba
- nics: array of {ports, speed, type (LOM/OCP/PCIe/rNDC), model, notes}
- psu_count, psu_watts, psu_notes
- gpu, pcie_slots_risers, mgmt (e.g. "iDRAC9 Enterprise"), tpm, rails_bezel, warranty, extras
- excluded_or_addons: things listed as NOT included or as optional add-ons
- conflicts: title vs spec vs description disagreements
- read_confidence: high/med/low, plus one-line reason

Example (item 137291211126, from its description): EPYC 7H12, 64C/128T, 2.6/3.3GHz, 280W; 128GB DDR4 registered ECC RDIMMs (no speed or stick count stated); PERC H740P 8GB NV cache; 4x 900GB 10k SAS HDD + 2x 960GB U.2 NVMe SSD; 2x 1Gb RJ45 LOM + 2x 10Gb card; 2x 750W; iDRAC9 Enterprise; TPM 2.0. Conflict: spec table says "2 x 1.2TB 10K SAS" but the description says 4x 900GB, so the description wins.
