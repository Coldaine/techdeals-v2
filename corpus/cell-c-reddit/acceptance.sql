-- Fixture cells (c) + (f) acceptance — Reddit multi-item [FS] posts and the
-- [W] wanted post, from sample_atom.xml via engine/adapters/atom.py.
-- BRIEF §3 style: plain SQL against the slice3-full branch. Run with psql -f.
-- Expects: the 3 reddit captures ingested with parser versions slice3-cell-c
-- (run 1) and slice3-cell-c-retry (replay), on the branch also holding cell-a
-- and fixture-zero data (hence the source filter everywhere).
--
-- batch-v2 price contract for this cell: a source line "N x item $P" with no
-- "each"/"per" is stored as homogeneous_division (the lot total, undivided).
-- "N x item $P each" stays explicit_unit with quantity 1. Older
-- quantity_conflict events from batch-v1 may still be in the ledger; the
-- checks below read the current extraction's prices, not those historical events.

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

-- Price honesty on the current pass. Four asks, none divided into a stored
-- unit price: 280 covers 4, 360 covers 6, 150 and 110 cover 1.
WITH prices AS (
    -- Live asks hang on the offer key (posting key + current group position).
    -- A replay that stores nothing new still prices the current groups.
    SELECT po.price_basis, po.amount::numeric(12,2) AS amount, po.quantity, po.price_kind,
           sg.position
    FROM sale_groups sg
    JOIN postings p ON p.id = sg.posting_id
    JOIN v_current_extractions c ON c.extraction_id = sg.extraction_id
    JOIN price_observations po
      ON po.superseded_by IS NULL
     AND po.price_kind = 'ask'
     AND po.offer_key = encode(sha256(convert_to(p.offer_key || '|g' || sg.position::text, 'UTF8')), 'hex')
    WHERE p.source = 'reddit_homelabsales'
)
SELECT '04_price_honesty' AS check_name,
       CASE WHEN count(*) = 4
            AND count(*) FILTER (WHERE pr.price_kind <> 'ask') = 0
            AND count(*) FILTER (WHERE pr.price_basis = 'homogeneous_division' AND pr.amount IN (280, 360) AND pr.quantity > 1) = 2
            AND count(*) FILTER (WHERE pr.price_basis = 'explicit_unit' AND pr.amount IN (110, 150) AND pr.quantity = 1) = 2
            THEN 'PASS' ELSE 'FAIL' END AS result,
       count(*) AS observations,
       string_agg(pr.price_basis || ':' || pr.amount::text || 'x' || pr.quantity::text, ', ' ORDER BY pr.amount) AS priced
FROM prices pr;

SELECT '05_stated_amounts' AS check_name,
       CASE WHEN (
            SELECT count(DISTINCT po.amount::numeric(12,2))
            FROM sale_groups sg
            JOIN postings p ON p.id = sg.posting_id
            JOIN v_current_extractions c ON c.extraction_id = sg.extraction_id
            JOIN price_observations po
              ON po.superseded_by IS NULL
             AND po.offer_key = encode(sha256(convert_to(p.offer_key || '|g' || sg.position::text, 'UTF8')), 'hex')
            WHERE p.source = 'reddit_homelabsales'
              AND po.amount::numeric(12,2) IN (110.00, 150.00, 280.00, 360.00)
       ) = 4 THEN 'PASS' ELSE 'FAIL' END AS result;

-- Lot totals are stored, not dropped. A current-pass quantity_conflict on
-- these three captures is a failure.
SELECT '06_lots_not_quarantined' AS check_name,
       CASE WHEN count(*) FILTER (
                WHERE q.reason = 'quantity_conflict'
                  AND q.created_at >= c.extracted_at
            ) = 0
            THEN 'PASS' ELSE 'FAIL' END AS result,
       count(*) FILTER (WHERE q.reason = 'quantity_conflict') AS historical_conflicts
FROM postings p
JOIN v_current_extractions c ON c.posting_id = p.id
LEFT JOIN quarantine_events q ON q.posting_id = p.id AND q.state = 'quarantined'
WHERE p.source = 'reddit_homelabsales' AND p.url NOT LIKE '%wanted1%';

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
                  WHERE p.source = 'reddit_homelabsales') >= 6
            THEN 'PASS' ELSE 'FAIL' END AS result,
       (SELECT count(*) FROM extractions e JOIN postings p ON p.id = e.posting_id
         WHERE p.source = 'reddit_homelabsales') AS extraction_rows;

-- Wanted post stays quarantined. Each FS post prices both of its groups.
SELECT '09_accounting_view' AS check_name,
       CASE WHEN count(*) FILTER (WHERE va.quarantine_state = 'quarantined' AND va.quarantine_reason = 'wanted_post') = 1
            AND count(*) FILTER (WHERE va.url NOT LIKE '%wanted1%' AND va.priced_group_count = 2) = 2
            THEN 'PASS' ELSE 'FAIL' END AS result,
       string_agg(va.reach_state || '/' || COALESCE(va.quarantine_reason, '-') || '/priced:' || COALESCE(va.priced_group_count, 0)::text, ', ') AS states
FROM v_accounting va
WHERE va.source = 'reddit_homelabsales';
