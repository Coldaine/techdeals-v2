-- TechDeals v2 Acceptance Queries
-- Run these against the Neon database after pipeline execution to verify acceptance.
-- Each query tests one criterion from BRIEF.md §3 and §6.

-- AC1: Total capture — every fixture posting lands as raw evidence with provenance
-- Expected: all fixture sources represented, none silently dropped
SELECT source, COUNT(*) as capture_count, 
       MIN(fetched_at) as earliest, MAX(fetched_at) as latest
FROM postings
GROUP BY source 
ORDER BY source;

-- AC2: Decomposition — multi-item postings produce expected line counts
-- Expected: server postings have multiple lines, single items have 1
SELECT p.id, p.source, COUNT(l.id) as line_count
FROM postings p
JOIN extractions e ON e.posting_id = p.id
JOIN lines l ON l.extraction_id = e.id
GROUP BY p.id, p.source
ORDER BY line_count DESC;

-- AC3: No fabricated prices — lot totals never silently divided
-- Expected: all sale_groups have explicit price_basis, no hidden division
SELECT sg.price_basis, COUNT(*) as count,
       SUM(sg.total_price_cents) as total_cents
FROM sale_groups sg
GROUP BY sg.price_basis
ORDER BY sg.price_basis;

-- AC3b: Verify price observations flow through valid lines or sale groups
SELECT po.id, po.price_cents, po.price_kind, po.subject_kind
FROM price_observations po
WHERE po.line_id IS NULL AND po.sale_group_id IS NULL AND po.subject_kind != 'posting';

-- AC4: Time series — price and availability history queryable via views
-- Expected: price history view returns active observations
SELECT * FROM v_price_history LIMIT 50;

-- AC5: Lazy identity — unresolved postings visible in read views
-- Expected: postings without resolutions are still queryable in v_accounting
SELECT * FROM v_accounting LIMIT 20;

-- AC6: Batch economics — extraction metadata recorded
SELECT b.id, b.model, b.prompt_version, b.cost_usd, b.listing_count, b.created_at
FROM extraction_batches b
ORDER BY b.created_at DESC;

-- AC7: Dynamic categories — categories are data, not DDL
SELECT name, description, parent_category, created_at
FROM categories
ORDER BY name;

-- AC8: Replay safety — re-ingesting creates new extractions, not duplicate postings
-- Expected: offer_key is unique per posting
SELECT offer_key, COUNT(*) as count
FROM postings
GROUP BY offer_key
HAVING COUNT(*) > 1;

-- AC9: Honest quarantine — quarantined subjects visible in accounting
SELECT q.id, q.posting_id, q.state, q.reason, q.detail, q.created_at
FROM quarantine_events q
ORDER BY q.created_at DESC;

-- Summary: overall pipeline health
SELECT 
    (SELECT COUNT(*) FROM postings) as total_postings,
    (SELECT COUNT(*) FROM extractions) as total_extractions,
    (SELECT COUNT(*) FROM lines) as total_lines,
    (SELECT COUNT(*) FROM sale_groups) as total_sale_groups,
    (SELECT COUNT(*) FROM price_observations WHERE superseded_by IS NULL) as active_price_observations,
    (SELECT COUNT(*) FROM availability_observations) as availability_observations,
    (SELECT COUNT(*) FROM resolutions WHERE superseded_by IS NULL) as active_resolutions;
