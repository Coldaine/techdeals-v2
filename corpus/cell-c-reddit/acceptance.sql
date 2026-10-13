-- Fixture cells (c) + (f) acceptance — Reddit multi-item [FS] posts and the
-- [W] wanted post, from sample_atom.xml via engine/adapters/atom.py.
-- BRIEF §3 style: plain SQL against the slice3-full branch. Run with psql -f.
-- Expects: the 3 reddit captures ingested with parser versions slice3-cell-c
-- (run 1) and slice3-cell-c-retry (replay), on the branch also holding cell-a
-- and fixture-zero data (hence the source filter everywhere).
--
-- KNOWN ENGINE BEHAVIOR RECORDED (generality finding GF-2): the unchanged
-- batch-v1 prompt maps "$280 for the lot of 4" to an explicit_unit ask with
-- quantity_units=1, which the engine's own S6 cross-check flags as
-- quantity_conflict (group count 4 vs unit count 1) — the 3 lot-priced Reddit
-- groups are therefore dropped with a visible quarantine, not silently stored.
-- Only the single-unit Samsung ($110) group carries a price observation.

-- capture completeness: all 3 entries land as postings with provenance.
SELECT '01_capture_completeness' AS check_name,
       CASE WHEN (SELECT count(*) FROM postings WHERE source = 'reddit_homelabsales') = 3
            THEN 'PASS' ELSE 'FAIL' END AS result,
       (SELECT count(*) FROM postings WHERE source = 'reddit_homelabsales') AS detail;

-- c: decomposition — the two [FS] posts are multi-item sale posts.
--   t3_abc123: "4x 8TB Exos HDDs $280" + "980 Pro 2TB $110"  → 2 lines
--   t3_def456: "2x 20TB WD Gold $150 each" + "6x 12TB HGST $360" → 2 lines
WITH fs_lines AS (
    SELECT l.label, l.stated_quantity, l.attributes, l.separately_purchasable
    FROM lines l
    JOIN postings p ON p.id = l.posting_id
    JOIN v_current_extractions c ON c.posting_id = l.posting_id
         AND c.extraction_id = l.extraction_id
    WHERE p.source = 'reddit_homelabsales' AND p.url LIKE '%abc123%'
      AND l.parent_line_id IS NULL
)
SELECT '02_decomposition_abc123' AS check_name,
       CASE WHEN (SELECT count(*) FROM fs_lines) = 2 THEN 'PASS' ELSE 'FAIL' END AS result,
       (SELECT count(*) FROM fs_lines)                     AS top_lines,
       (SELECT string_agg(label, ' || ') FROM fs_lines)    AS labels;

WITH fs_lines AS (
    SELECT l.label
    FROM lines l
    JOIN postings p ON p.id = l.posting_id
    JOIN v_current_extractions c ON c.posting_id = l.posting_id
         AND c.extraction_id = l.extraction_id
    WHERE p.source = 'reddit_homelabsales' AND p.url LIKE '%def456%'
      AND l.parent_line_id IS NULL
)
SELECT '03_decomposition_def456' AS check_name,
       CASE WHEN (SELECT count(*) FROM fs_lines) = 2 THEN 'PASS' ELSE 'FAIL' END AS result,
       (SELECT count(*) FROM fs_lines)                     AS top_lines,
       (SELECT string_agg(label, ' || ') FROM fs_lines)    AS labels;

-- c: price honesty — no silent allocation. Exactly one price observation lands
-- (the single-unit Samsung $110); the three lot-priced groups are dropped by
-- the engine's S6 cross-check and recorded as quantity_conflict quarantines —
-- visible, never silently stored, never divided into unit prices.
WITH prices AS (
    SELECT po.price_basis, po.amount, po.quantity, po.price_kind
    FROM price_observations po
    JOIN postings p ON p.id = po.posting_id
    WHERE p.source = 'reddit_homelabsales' AND po.superseded_by IS NULL
)
SELECT '04_price_honesty' AS check_name,
       CASE WHEN count(*) = 1
            AND count(*) FILTER (WHERE pr.price_kind <> 'ask') = 0
            AND count(*) FILTER (WHERE pr.amount IS NULL) = 0
            AND count(*) FILTER (WHERE pr.price_basis <> 'explicit_unit') = 0
            THEN 'PASS' ELSE 'FAIL' END AS result,
       count(*)                              AS observations,
       string_agg(DISTINCT pr.price_basis, ', ')  AS bases,
       string_agg(pr.quantity::text, ', ')        AS quantity_units
FROM prices pr;

-- the stated amount lands exactly (110) — no drift, no fabrication.
WITH prices AS (
    SELECT po.amount::numeric(12,2) AS amt
    FROM price_observations po
    JOIN postings p ON p.id = po.posting_id
    WHERE p.source = 'reddit_homelabsales' AND po.superseded_by IS NULL
)
SELECT '05_stated_amounts' AS check_name,
       CASE WHEN count(*) = 1 AND max(amt) = 110.00 THEN 'PASS' ELSE 'FAIL' END AS result,
       max(amt) AS amount
FROM prices;

-- the 3 lot-priced groups that were dropped: visible quantity_conflict
-- quarantines with the stated contradiction in the detail (S6, not silent).
WITH qc AS (
    SELECT q.reason, q.detail
    FROM quarantine_events q
    JOIN postings p ON p.id = q.posting_id
    WHERE p.source = 'reddit_homelabsales' AND q.state = 'quarantined'
      AND q.reason = 'quantity_conflict'
)
SELECT '06_quantity_conflict_visible' AS check_name,
       CASE WHEN count(*) = 6
            AND count(*) FILTER (WHERE qc.detail LIKE '%contradicts%') = 6
            THEN 'PASS' ELSE 'FAIL' END AS result,
       count(*)                          AS quantity_conflict_events
FROM qc;

-- f: the [W] wanted post is quarantined, NEVER an ask — no price observation,
-- no line, no sale group may hang off t3_wanted1, and a quarantine event with
-- reason wanted_post must be visible.
WITH wanted AS (SELECT id FROM postings WHERE source = 'reddit_homelabsales' AND url LIKE '%wanted1%')
SELECT '07_wanted_quarantined' AS check_name,
       CASE WHEN (SELECT count(*) FROM quarantine_events q
                    JOIN wanted w ON w.id = q.posting_id
                    WHERE q.state = 'quarantined' AND q.reason = 'wanted_post') >= 1
            AND (SELECT count(*) FROM price_observations po JOIN wanted w ON w.id = po.posting_id) = 0
            AND (SELECT count(*) FROM lines l JOIN wanted w ON w.id = l.posting_id
                  JOIN v_current_extractions c ON c.posting_id = l.posting_id
                  WHERE c.extraction_id = l.extraction_id) = 0
            AND (SELECT count(*) FROM sale_groups sg JOIN wanted w ON w.id = sg.posting_id
                  JOIN v_current_extractions c ON c.posting_id = sg.posting_id
                  WHERE c.extraction_id = sg.extraction_id) = 0
            THEN 'PASS' ELSE 'FAIL' END AS result,
       (SELECT reason || ': ' || COALESCE(detail, '') FROM quarantine_events q
         JOIN wanted w ON w.id = q.posting_id
        WHERE q.state = 'quarantined' LIMIT 1) AS detail;

-- replay safety: the retry run appended a second extraction pass for the 3
-- postings with ZERO new postings and deduped identical observations.
SELECT '08_replay_safety' AS check_name,
       CASE WHEN (SELECT count(*) FROM postings WHERE source = 'reddit_homelabsales') = 3
            AND (SELECT count(*) FROM extractions e JOIN postings p ON p.id = e.posting_id
                  WHERE p.source = 'reddit_homelabsales') = 6
            THEN 'PASS' ELSE 'FAIL' END AS result,
       (SELECT count(*) FROM extractions e JOIN postings p ON p.id = e.posting_id
         WHERE p.source = 'reddit_homelabsales') AS extraction_rows;

-- Q4 accounting view agrees: wanted post shows as quarantined, FS posts are
-- extracted (the two lot-priced ones as extracted_unpriced after the S6 drop —
-- visible in the ladder, not hidden).
-- Q4 accounting view agrees: wanted post shows as quarantined; the two FS
-- posts surface with their current (correct, post-S6) state: the price-bearing
-- Samsung group shows priced_group_count=1 while the three dropped lot groups
-- keep the visible quantity_conflict quarantines.
SELECT '09_accounting_view' AS check_name,
       CASE WHEN count(*) FILTER (WHERE va.quarantine_state = 'quarantined' AND va.quarantine_reason = 'wanted_post') = 1
            AND count(*) FILTER (WHERE va.quarantine_reason = 'quantity_conflict'
                                   AND va.priced_group_count = 1) = 1
            AND count(*) FILTER (WHERE va.quarantine_reason = 'quantity_conflict'
                                   AND va.priced_group_count IS NULL) = 1
            THEN 'PASS' ELSE 'FAIL' END AS result,
       string_agg(va.reach_state || '/' || va.quarantine_reason || '/priced:' || COALESCE(va.priced_group_count,0), ', ') AS states
FROM v_accounting va
WHERE va.source = 'reddit_homelabsales';
