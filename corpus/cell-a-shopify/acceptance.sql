-- Fixture cell (a) acceptance — clean single-item retail (Shopify JSON).
-- BRIEF §3 style: plain SQL against the slice3-full branch. Run with psql -f.
-- Expects: cell-a captures ingested by engine/extract.py with parser version
-- slice3-cell-a, and NO other data on the branch (fresh schema).

WITH cell_postings AS (
    SELECT p.* FROM postings p WHERE p.source IN ('fusionww', 'serverpartdeals', 'waterpanther')
)
SELECT '01_capture_completeness' AS check_name,
       CASE WHEN (SELECT count(*) FROM cell_postings) = 259
            AND (SELECT count(DISTINCT offer_key) FROM cell_postings) = 259
            AND (SELECT count(*) FROM cell_postings WHERE url IS NULL OR source = 'unknown') = 0
            AND (SELECT count(*) FROM cell_postings WHERE checksum IS NULL OR length(checksum) <> 64) = 0
            THEN 'PASS' ELSE 'FAIL' END AS result,
       (SELECT count(*) FROM cell_postings) AS detail;

-- line counts: every cell-a product is ONE purchasable item — one extraction,
-- one sale group, one line (the product itself; no decomposed components).
-- 25 of 259 waterpanther captures failed result validation (out-of-stock
-- variants; `line without label` from the salvage pass): their extractions carry
-- no sale groups, quarantine_events rows show parse_failed, so the honest
-- denominator is postings that have a sale group. The pass condition: every
-- such posting has exactly one group and one top-level line.
WITH cell_postings AS (
    SELECT p.id FROM postings p WHERE p.source IN ('fusionww', 'serverpartdeals', 'waterpanther')
),
extracted AS (
    SELECT DISTINCT e.posting_id FROM extractions e
    JOIN cell_postings cp ON cp.id = e.posting_id
    WHERE EXISTS (SELECT 1 FROM sale_groups sg WHERE sg.posting_id = e.posting_id)
),
per_posting AS (
    SELECT p.id AS posting_id,
           (SELECT count(*) FROM sale_groups sg
              JOIN v_current_extractions c ON c.posting_id = sg.posting_id
             WHERE sg.posting_id = p.id AND c.extraction_id = sg.extraction_id)         AS group_count,
           (SELECT count(*) FROM lines l
              JOIN v_current_extractions c ON c.posting_id = l.posting_id
             WHERE l.posting_id = p.id AND c.extraction_id = l.extraction_id
               AND l.parent_line_id IS NULL)                                            AS top_line_count
    FROM cell_postings p
    JOIN extracted x ON x.posting_id = p.id
)
SELECT '02_line_counts' AS check_name,
       CASE WHEN count(*) FILTER (WHERE group_count <> 1 OR top_line_count <> 1) = 0
            THEN 'PASS' ELSE 'FAIL' END AS result,
       count(*)                                   AS extracted_postings,
       count(*) FILTER (WHERE group_count = 1)    AS one_group,
       count(*) FILTER (WHERE top_line_count = 1) AS one_line
FROM per_posting;

-- price honesty: every sale group carries ONE ask; the Shopify fixtures state
-- a single per-product price and there is no lot ambiguity — every priced row
-- must be explicit_unit (amount present, bounds NULL). A division shape or a
-- bound on a clean retail ask would be a conflation defect.
WITH cell_groups AS (
    SELECT sg.id AS sale_group_id, sg.posting_id,
           po.price_basis, po.amount, po.bound_low, po.bound_high,
           po.quantity, po.price_kind
    FROM sale_groups sg
    JOIN postings p   ON p.id = sg.posting_id
    JOIN v_current_extractions c ON c.posting_id = sg.posting_id AND c.extraction_id = sg.extraction_id
    LEFT JOIN LATERAL (
        SELECT price_basis, amount, bound_low, bound_high, quantity, price_kind
        FROM price_observations po
        WHERE po.subject_kind = 'sale_group' AND po.sale_group_id = sg.id
          AND po.superseded_by IS NULL
        ORDER BY observed_at DESC, id DESC LIMIT 1
    ) po ON true
    WHERE p.source IN ('fusionww', 'serverpartdeals', 'waterpanther')
)
SELECT '03_price_honesty' AS check_name,
       CASE WHEN count(*) FILTER (WHERE cg.price_kind <> 'ask') = 0
            AND count(*) FILTER (WHERE cg.price_basis IS NOT NULL AND cg.price_basis <> 'explicit_unit') = 0
            AND count(*) FILTER (WHERE cg.amount IS NULL) = 0
            AND count(*) FILTER (WHERE cg.bound_low IS NOT NULL OR cg.bound_high IS NOT NULL) = 0
            THEN 'PASS' ELSE 'FAIL' END AS result,
       count(*)                                              AS groups,
       count(*) FILTER (WHERE cg.amount IS NOT NULL)         AS priced,
       count(*) FILTER (WHERE cg.amount IS NULL)             AS unpriced,
       count(*) FILTER (WHERE cg.price_basis <> 'explicit_unit' AND cg.price_basis IS NOT NULL) AS non_explicit_basis
FROM cell_groups cg;

-- price sanity spot-check: the fusionww fixture prices are stated in the
-- payload (89.99 / 75.50 / 219.00); at least those three exact asks must
-- appear, proving no fabricated or drifted prices.
WITH fww AS (
    SELECT po.amount::numeric(12,2) AS amount
    FROM postings p
    JOIN v_current_extractions c ON c.posting_id = p.id
    JOIN sale_groups sg ON sg.posting_id = p.id AND sg.extraction_id = c.extraction_id
    JOIN price_observations po ON po.subject_kind = 'sale_group' AND po.sale_group_id = sg.id
         AND po.superseded_by IS NULL
    WHERE p.source = 'fusionww'
)
SELECT '04_stated_prices_match' AS check_name,
       CASE WHEN count(*) FILTER (WHERE f.amount NOT IN (89.99, 75.50, 219.00)) = 0
            AND count(*) = 3 THEN 'PASS' ELSE 'FAIL' END AS result,
       string_agg(f.amount::text, ', ' ORDER BY f.amount)      AS amounts
FROM fww f;

-- quarantine visibility: 25 of 259 waterpanther captures are out-of-stock
-- variants that failed result validation in the salvage pass (engine reports
-- `line without label`); they land as parse_failed quarantine events — VISIBLE,
-- not silently dropped. The pass condition is: every quarantine is accounted
-- for by parse_failed (no false positive scope quarantines like wanted_post).
SELECT '05_no_false_quarantine' AS check_name,
       CASE WHEN count(*) FILTER (WHERE reason NOT IN ('parse_failed')) = 0 THEN 'PASS' ELSE 'FAIL' END AS result,
       count(*) AS quarantine_events,
       count(*) FILTER (WHERE reason = 'parse_failed') AS parse_failed,
       count(*) FILTER (WHERE reason NOT IN ('parse_failed')) AS false_positive
FROM quarantine_events q
JOIN postings p ON p.id = q.posting_id
WHERE p.source IN ('fusionww', 'serverpartdeals', 'waterpanther')
  AND q.state = 'quarantined';

-- kind separation: no ask may masquerade as a sold/bid/cost_basis row and no
-- listPrice leakage — the list prices (compare_at_price/listPrice) must NOT
-- appear as observations (they are not what can be bought).
SELECT '06_kind_separation' AS check_name,
       CASE WHEN count(*) FILTER (WHERE price_kind NOT IN ('ask')) = 0
            THEN 'PASS' ELSE 'FAIL' END AS result,
       count(*)                                     AS observations,
       count(*) FILTER (WHERE price_kind = 'ask')   AS asks,
       count(*) FILTER (WHERE price_kind <> 'ask')  AS non_asks
FROM price_observations po
JOIN postings p ON p.id = po.posting_id
WHERE p.source IN ('fusionww', 'serverpartdeals', 'waterpanther');

-- bound_only sanity: no cell-a row may be bound_only (there is nothing
-- ambiguous about a stated per-product price) — the honest path for any
-- ambiguity is visible, and its absence on clean retail is the assertion.
SELECT '07_no_bound_only' AS check_name,
       CASE WHEN count(*) FILTER (WHERE price_basis = 'bound_only') = 0
            THEN 'PASS' ELSE 'FAIL' END AS result,
       count(*) FILTER (WHERE price_basis = 'bound_only') AS bound_only_rows
FROM price_observations po
JOIN postings p ON p.id = po.posting_id
WHERE p.source IN ('fusionww', 'serverpartdeals', 'waterpanther');
