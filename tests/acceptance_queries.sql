-- TechDeals v2 Acceptance Queries
-- Run these against the Neon database after pipeline execution to verify acceptance.
-- Each query tests one criterion from BRIEF.md §3.

-- AC1: Total capture — every fixture posting lands as raw evidence with provenance
-- Expected: all fixture sources represented, none silently dropped
SELECT source, COUNT(*) as capture_count, 
       MIN(fetched_at) as earliest, MAX(fetched_at) as latest
FROM raw_captures 
GROUP BY source 
ORDER BY source;

-- AC2: Decomposition — multi-item postings produce expected line counts
-- Expected: server postings have 8-10 lines, single items have 1
SELECT p.id, p.title, p.source, COUNT(l.id) as line_count
FROM postings p
JOIN lines l ON l.posting_id = p.id
WHERE p.status = 'extracted'
GROUP BY p.id, p.title, p.source
ORDER BY line_count DESC;

-- AC3: No fabricated prices — lot totals never silently divided
-- Expected: all sale_groups have explicit price_basis, no hidden division
SELECT sg.price_basis, COUNT(*) as count,
       SUM(sg.total_price_cents) as total_cents
FROM sale_groups sg
GROUP BY sg.price_basis
ORDER BY sg.price_basis;

-- AC3b: Verify no line has a price without a sale_group
-- Expected: 0 rows (all prices flow through sale_groups)
SELECT l.id, l.label, o.price_cents, o.price_kind
FROM lines l
JOIN observations o ON o.line_id = l.id
LEFT JOIN sale_group_lines sgl ON sgl.line_id = l.id
WHERE sgl.sale_group_id IS NULL
  AND o.price_cents IS NOT NULL;

-- AC4: Time series — price and availability history queryable
-- Expected: observations table has data, queryable by time
SELECT DATE_TRUNC('day', observed_at) as day,
       price_kind,
       COUNT(*) as observation_count,
       MIN(price_cents) as min_price,
       MAX(price_cents) as max_price
FROM observations
WHERE superseded_by IS NULL
GROUP BY DATE_TRUNC('day', observed_at), price_kind
ORDER BY day DESC;

-- AC5: Lazy identity — unresolved postings visible in read views
-- Expected: postings without resolutions are still queryable
SELECT p.id, p.title, p.source, p.status,
       COUNT(r.id) as resolution_count
FROM postings p
LEFT JOIN lines l ON l.posting_id = p.id
LEFT JOIN resolutions r ON r.line_id = l.id AND r.superseded_by IS NULL
WHERE p.status = 'extracted'
GROUP BY p.id, p.title, p.source, p.status
HAVING COUNT(r.id) = 0
LIMIT 20;

-- AC6: Batch economics — extraction metadata recorded
-- (This is verified by checking the extraction logs, not a DB query)

-- AC7: Dynamic categories — categories are data, not DDL
SELECT name, description, parent_category, created_at
FROM categories
ORDER BY name;

-- AC8: Replay safety — re-ingesting creates new versions, not duplicates
-- Expected: each (source, source_listing_id, checksum) appears exactly once
SELECT source, source_listing_id, checksum, COUNT(*) as count
FROM raw_captures
GROUP BY source, source_listing_id, checksum
HAVING COUNT(*) > 1;

-- AC9: Honest quarantine — out-of-scope items visible with reasons
SELECT p.id, p.source, p.title, p.failure_mode, p.failure_details
FROM postings p
WHERE p.status IN ('failed', 'quarantined')
ORDER BY p.created_at DESC;

-- Summary: overall pipeline health
SELECT 
    (SELECT COUNT(*) FROM raw_captures) as total_captures,
    (SELECT COUNT(*) FROM postings WHERE status = 'extracted') as extracted,
    (SELECT COUNT(*) FROM postings WHERE status = 'quarantined') as quarantined,
    (SELECT COUNT(*) FROM postings WHERE status = 'failed') as failed,
    (SELECT COUNT(*) FROM lines) as total_lines,
    (SELECT COUNT(*) FROM sale_groups) as total_sale_groups,
    (SELECT COUNT(*) FROM observations WHERE superseded_by IS NULL) as active_observations,
    (SELECT COUNT(*) FROM resolutions WHERE superseded_by IS NULL) as active_resolutions;
-- =====================================================================
-- BRIEF 6 target-query demonstrations (every design choice is scored
-- against these four questions; these two are the ones with a schema shape).
-- =====================================================================

-- TQ1: "Cheapest 32GB DDR4 available right now" — needs decomposition +
-- per-unit/bound prices + spec attributes. Rows must be REAL asks.
SELECT l.label, l.category, l.quantity, l.capacity_gb, l.interface,
       o.price_cents, p.source, p.url
FROM lines l
JOIN postings p ON p.id = l.posting_id
JOIN observations o ON o.line_id = l.id
WHERE p.status = 'extracted'
  AND o.superseded_by IS NULL AND o.available = true AND o.price_kind = 'ask'
  AND l.category = 'ram' AND l.interface = 'DDR4' AND l.capacity_gb = 32
ORDER BY o.price_cents;

-- TQ3: "What is this lot actually worth" — lot totals must never be silently
-- divided into per-unit prices. Anything not explicit_unit must be labelled.
SELECT p.source, sg.label, sg.price_basis, sg.total_price_cents,
       COUNT(sgl.line_id) AS lines_in_group, sg.notes
FROM sale_groups sg
JOIN postings p ON p.id = sg.posting_id
JOIN sale_group_lines sgl ON sgl.sale_group_id = sg.id
WHERE sg.price_basis <> 'explicit_unit'
GROUP BY p.source, sg.label, sg.price_basis, sg.total_price_cents, sg.notes
ORDER BY sg.total_price_cents DESC;

-- Guardrail check: no observation may carry a line price without a sale group
-- (the "no fabricated prices" invariant, made queryable).
SELECT COUNT(*) AS naked_line_prices
FROM observations o
LEFT JOIN sale_group_lines sgl ON sgl.line_id = o.line_id
WHERE o.line_id IS NOT NULL AND o.price_cents IS NOT NULL
  AND sgl.sale_group_id IS NULL;
