-- View: Current availability and pricing (Query 1: "Cheapest N units of spec S available right now")
CREATE OR REPLACE VIEW v_available_now AS
SELECT
    l.id AS line_id,
    l.label,
    l.category,
    l.quantity,
    p.source,
    p.url,
    p.title AS posting_title,
    sg.price_basis,
    o.price_cents,
    o.price_kind,
    o.observed_at,
    o.offer_key
FROM lines l
JOIN postings p ON l.posting_id = p.id
LEFT JOIN sale_group_lines sgl ON sgl.line_id = l.id
LEFT JOIN sale_groups sg ON sg.id = sgl.sale_group_id
LEFT JOIN observations o ON o.line_id = l.id
    AND o.superseded_by IS NULL
    AND o.available = true
    AND o.price_kind = 'ask'
WHERE p.status = 'extracted'
    AND l.separately_purchasable = true
    AND o.price_cents IS NOT NULL;

-- View: Price history (Query 2: "What did this cost over time")
CREATE OR REPLACE VIEW v_price_history AS
SELECT
    o.line_id,
    o.posting_id,
    o.offer_key,
    o.price_cents,
    o.price_kind,
    o.available,
    o.observed_at,
    o.superseded_by,
    l.label,
    l.category,
    p.source
FROM observations o
LEFT JOIN lines l ON l.id = o.line_id
JOIN postings p ON p.id = o.posting_id
WHERE o.superseded_by IS NULL
ORDER BY o.observed_at DESC;

-- View: Lot decomposition (Query 3: "What is this lot actually worth")
CREATE OR REPLACE VIEW v_lot_decomposition AS
SELECT
    p.id AS posting_id,
    p.title,
    p.url,
    sg.id AS sale_group_id,
    sg.label AS sale_group_label,
    sg.price_basis,
    sg.total_price_cents,
    sg.total_currency,
    l.id AS line_id,
    l.label AS line_label,
    l.category,
    l.quantity,
    sgl.quantity_in_group
FROM postings p
JOIN sale_groups sg ON sg.posting_id = p.id
JOIN sale_group_lines sgl ON sgl.sale_group_id = sg.id
JOIN lines l ON l.id = sgl.line_id
WHERE p.status = 'extracted';

-- View: Quarantine and failures (Query 4: "What did we miss")
CREATE OR REPLACE VIEW v_quarantine AS
SELECT
    p.id,
    p.source,
    p.url,
    p.title,
    p.status,
    p.failure_mode,
    p.failure_details,
    p.created_at,
    rc.raw_payload
FROM postings p
JOIN raw_captures rc ON rc.id = p.capture_id
WHERE p.status IN ('failed', 'quarantined')
ORDER BY p.created_at DESC;