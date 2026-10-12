-- TechDeals v2 — posting-first schema, part 2: views
--
-- The four BRIEF §6 target queries, one view each:
--   Q1  v_cheapest_available   (+ v_category_prices, v_current_extractions)
--   Q2  v_price_history
--   Q3  v_lot_worth            (+ v_product_reference_price)
--   Q4  v_accounting
-- All derived values (per-unit price, current state, latest extraction,
-- component sums) are computed here in views — never stored.

BEGIN;

-- Q1/Q3 helper: which parse pass of each posting the read views read.
-- Replays append newer extractions; views read only the newest.
CREATE VIEW v_current_extractions AS
SELECT DISTINCT ON (posting_id)
       posting_id,
       id         AS extraction_id,
       created_at AS extracted_at
FROM extractions
ORDER BY posting_id, created_at DESC, id DESC;

COMMENT ON VIEW  v_current_extractions                    IS 'Q1/Q3 helper: newest extraction per posting, so replay passes never double-count lines.';
COMMENT ON COLUMN v_current_extractions.posting_id        IS 'Q1/Q3: posting being read.';
COMMENT ON COLUMN v_current_extractions.extraction_id     IS 'Q1/Q3: the parse pass whose lines/groups are current.';
COMMENT ON COLUMN v_current_extractions.extracted_at      IS 'Q4: when that pass ran.';

-- --------------------------------------------------------- Q1: cheapest N --

CREATE VIEW v_cheapest_available AS
WITH latest_ask AS (
    SELECT DISTINCT ON (COALESCE(line_id::text, sale_group_id::text))
           offer_key, subject_kind, line_id, sale_group_id,
           price_basis, currency, amount, quantity, bound_low, bound_high, observed_at
    FROM price_observations
    WHERE price_kind = 'ask' AND superseded_by IS NULL
    ORDER BY COALESCE(line_id::text, sale_group_id::text), observed_at DESC, id DESC
),
latest_avail AS (
    SELECT DISTINCT ON (offer_key) offer_key, state, observed_at
    FROM availability_observations
    ORDER BY offer_key, observed_at DESC, id DESC
)
SELECT l.id               AS line_id,
       l.posting_id,
       l.label,
       l.stated_quantity,
       l.attributes,
       p.source, p.url, p.fetched_at,
       r.product_key, r.product_name, r.confidence AS resolution_confidence,
       a.price_basis, a.currency,
       a.amount,
       a.quantity          AS amount_covers_units,
       a.amount / NULLIF(a.quantity, 0) AS unit_price,
       a.bound_low, a.bound_high,
       a.offer_key,
       av.state            AS availability_state,
       av.observed_at      AS availability_checked_at,
       a.observed_at       AS price_observed_at
FROM lines l
JOIN postings p                ON p.id = l.posting_id
JOIN v_current_extractions c   ON c.posting_id = l.posting_id
                              AND c.extraction_id = l.extraction_id
JOIN latest_ask a              ON a.subject_kind = 'line' AND a.line_id = l.id
JOIN latest_avail av           ON av.offer_key = a.offer_key AND av.state = 'available'
LEFT JOIN LATERAL (
    SELECT product_key, product_name, confidence
    FROM resolutions
    WHERE line_id = l.id AND superseded_by IS NULL
    ORDER BY created_at DESC, id DESC
    LIMIT 1
) r ON true
ORDER BY unit_price NULLS LAST, bound_low NULLS LAST;

COMMENT ON VIEW  v_cheapest_available                  IS 'Q1: "cheapest N units of spec S available right now" — one row per top-level purchasable line, latest ask, latest availability = available. Filter on attributes for spec S; LIMIT N for cheapest-N. Unresolved lines appear with product_key NULL (unresolved is never filtered out).';
COMMENT ON COLUMN v_cheapest_available.line_id          IS 'Q1: the purchasable line.';
COMMENT ON COLUMN v_cheapest_available.label            IS 'Q1: seller''s stated description.';
COMMENT ON COLUMN v_cheapest_available.attributes       IS 'Q1: spec attributes to filter on (e.g. ''{"capacity_gb":32,"type":"DDR4"}'').';
COMMENT ON COLUMN v_cheapest_available.stated_quantity   IS 'Q1: units obtainable per purchase.';
COMMENT ON COLUMN v_cheapest_available.unit_price       IS 'Q1: derived per-unit price (amount / units covered) — computed here, never stored.';
COMMENT ON COLUMN v_cheapest_available.price_basis      IS 'Q1: basis of the ask (bound_only rows expose bounds instead of unit_price).';
COMMENT ON COLUMN v_cheapest_available.bound_low        IS 'Q1: lower bound when the ask is ambiguous — reported, not allocated.';
COMMENT ON COLUMN v_cheapest_available.bound_high       IS 'Q1: upper bound when the ask is ambiguous.';
COMMENT ON COLUMN v_cheapest_available.availability_state IS 'Q1: latest availability is ''available'' by the view''s join.';
COMMENT ON COLUMN v_cheapest_available.product_key      IS 'Q1: resolved identity (NULL when unresolved — still visible).';

-- Named-spec variant of Q1: categories are data rows, not DDL.
CREATE VIEW v_category_prices AS
SELECT c.id     AS category_id,
       c.name   AS category_name,
       ca.*
FROM categories c
JOIN v_cheapest_available ca ON ca.attributes @> c.spec
ORDER BY c.name, ca.unit_price NULLS LAST, ca.bound_low NULLS LAST;

COMMENT ON VIEW  v_category_prices               IS 'Q1: cheapest available lines per named category spec (adding a category = inserting a row into categories).';
COMMENT ON COLUMN v_category_prices.category_id   IS 'Q1: the named spec.';
COMMENT ON COLUMN v_category_prices.category_name IS 'Q1: category name consumers query by.';

-- ------------------------------------------------------- Q2: price history --

CREATE VIEW v_price_history AS
SELECT po.id,
       po.offer_key, po.posting_id,
       p.source, p.url, p.fetched_at,
       po.subject_kind, po.line_id, po.sale_group_id,
       po.price_kind, po.price_basis, po.currency,
       po.amount, po.quantity,
       po.amount / NULLIF(po.quantity, 0) AS unit_price,
       po.bound_low, po.bound_high, po.basis_note,
       po.superseded_by,
       (po.superseded_by IS NOT NULL) AS is_superseded,
       po.observed_at
FROM price_observations po
JOIN postings p ON p.id = po.posting_id
ORDER BY po.offer_key, po.observed_at;

COMMENT ON VIEW  v_price_history              IS 'Q2: "what did this cost over time" — every observation per offer, asks/bids/solds/cost basis/references as separate price_kind series; nothing rewritten, superseded rows flagged not deleted.';
COMMENT ON COLUMN v_price_history.price_kind   IS 'Q2: the series selector (ask/bid/sold/cost_basis/reference).';
COMMENT ON COLUMN v_price_history.unit_price   IS 'Q2: derived per-unit value of the observation.';
COMMENT ON COLUMN v_price_history.is_superseded IS 'Q2: corrections are visible in history, never erased.';

-- ---------------------------------------------------- Q3: what is a lot worth --

CREATE VIEW v_product_reference_price AS
SELECT product_key,
       min(unit_price) AS ref_unit_price,
       min(bound_low)  AS ref_bound_low,
       count(*)        AS comparable_count
FROM v_cheapest_available
WHERE product_key IS NOT NULL
GROUP BY product_key;

COMMENT ON VIEW  v_product_reference_price         IS 'Q3 helper: cheapest currently-available unit price per resolved product — the (1) that lot lines are priced against.';
COMMENT ON COLUMN v_product_reference_price.product_key     IS 'Q3: resolved product.';
COMMENT ON COLUMN v_product_reference_price.ref_unit_price  IS 'Q3: best available market unit price for that product.';
COMMENT ON COLUMN v_product_reference_price.ref_bound_low   IS 'Q3: best available lower bound when comps are bound_only.';
COMMENT ON COLUMN v_product_reference_price.comparable_count IS 'Q3: how many comps back the reference (small counts = weak reference).';

CREATE VIEW v_lot_worth AS
WITH lots AS (
    SELECT DISTINCT ON (sg.id)
           sg.id AS sale_group_id,
           sg.posting_id,
           sg.label AS lot_label,
           o.price_basis AS lot_price_basis,
           o.currency,
           o.amount AS lot_ask,
           o.quantity AS lot_ask_covers_units,
           o.bound_low AS lot_bound_low,
           o.bound_high AS lot_bound_high
    FROM sale_groups sg
    JOIN v_current_extractions c ON c.posting_id = sg.posting_id
                                 AND c.extraction_id = sg.extraction_id
    LEFT JOIN LATERAL (
        SELECT price_basis, currency, amount, quantity, bound_low, bound_high
        FROM price_observations
        WHERE subject_kind = 'sale_group' AND sale_group_id = sg.id
          AND price_kind = 'ask' AND superseded_by IS NULL
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
    ) o ON true
),
members AS (
    SELECT lt.sale_group_id,
           l.id  AS line_id,
           l.label AS line_label,
           t.line_quantity,
           r.product_key,
           ref.ref_unit_price,
           ref.ref_bound_low
    FROM lots lt
    JOIN sale_group_terms t ON t.sale_group_id = lt.sale_group_id
    JOIN lines l            ON l.id = t.line_id
    LEFT JOIN LATERAL (
        SELECT product_key
        FROM resolutions
        WHERE line_id = l.id AND superseded_by IS NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    ) r ON true
    LEFT JOIN v_product_reference_price ref ON ref.product_key = r.product_key
),
valuation AS (
    SELECT sale_group_id,
           sum(ref_unit_price * line_quantity) AS component_value,
           sum(ref_bound_low  * line_quantity) AS component_value_lower_bound,
           count(*) FILTER (WHERE ref_unit_price IS NOT NULL) AS lines_valued,
           count(*) AS lines_total
    FROM members
    GROUP BY sale_group_id
)
SELECT lt.sale_group_id,
       lt.posting_id,
       lt.lot_label,
       lt.lot_price_basis, lt.currency,
       lt.lot_ask, lt.lot_ask_covers_units,
       lt.lot_bound_low, lt.lot_bound_high,
       v.component_value,
       v.component_value_lower_bound,
       v.lines_valued, v.lines_total,
       (v.lines_valued < v.lines_total) AS valuation_incomplete,
       lt.lot_ask - v.component_value   AS ask_minus_component_value
FROM lots lt
LEFT JOIN valuation v ON v.sale_group_id = lt.sale_group_id
ORDER BY lt.sale_group_id;

COMMENT ON VIEW  v_lot_worth                              IS 'Q3: "what is this lot actually worth" — each sale group decomposed into member lines, each line priced against the cheapest available resolved comparable, summed and compared to the lot ask. bound_only comps contribute bounds, never silent allocations; valuation_incomplete flags honest gaps.';
COMMENT ON COLUMN v_lot_worth.lot_ask                     IS 'Q3: the ask on the lot (latest, non-superseded).';
COMMENT ON COLUMN v_lot_worth.component_value             IS 'Q3: sum of per-line reference prices — point estimate from comps.';
COMMENT ON COLUMN v_lot_worth.component_value_lower_bound IS 'Q3: sum of per-line lower bounds — conservative floor.';
COMMENT ON COLUMN v_lot_worth.lines_valued                IS 'Q3: how many lines got a reference price (resolution + comps existed).';
COMMENT ON COLUMN v_lot_worth.lines_total                 IS 'Q3: denominator — all member lines.';
COMMENT ON COLUMN v_lot_worth.valuation_incomplete        IS 'Q3: true when some lines could not be valued; the answer states its gaps instead of hiding them.';
COMMENT ON COLUMN v_lot_worth.ask_minus_component_value   IS 'Q3: deal premium/discount of the lot ask versus component values.';

-- -------------------------------------------- Q4: what did we miss / accounting --

CREATE VIEW v_accounting AS
WITH line_stats AS (
    SELECT l.posting_id, count(*) AS line_count
    FROM lines l
    JOIN v_current_extractions c ON c.posting_id = l.posting_id
                                 AND c.extraction_id = l.extraction_id
    GROUP BY l.posting_id
),
priced AS (
    SELECT l.posting_id, count(DISTINCT l.id) AS priced_line_count
    FROM lines l
    JOIN price_observations po ON po.subject_kind = 'line'
                              AND po.line_id = l.id
                              AND po.price_kind = 'ask'
                              AND po.superseded_by IS NULL
    GROUP BY l.posting_id
),
resolved AS (
    SELECT l.posting_id, count(DISTINCT l.id) AS resolved_line_count
    FROM lines l
    JOIN resolutions r ON r.line_id = l.id AND r.superseded_by IS NULL
    GROUP BY l.posting_id
),
quarantine AS (
    SELECT DISTINCT ON (posting_id) posting_id, state, reason, detail
    FROM quarantine_events
    ORDER BY posting_id, created_at DESC, id DESC
)
SELECT p.id          AS posting_id,
       p.source, p.url, p.fetched_at, p.offer_key,
       (SELECT count(*) FROM extractions e WHERE e.posting_id = p.id) AS extraction_count,
       ls.line_count,
       ps.priced_line_count,
       rs.resolved_line_count,
       q.state       AS quarantine_state,
       q.reason      AS quarantine_reason,
       q.detail      AS quarantine_detail,
       CASE
           WHEN q.state = 'quarantined'    THEN 'quarantined'
           WHEN ls.line_count IS NULL      THEN 'captured_unextracted'
           WHEN ps.priced_line_count = 0   THEN 'extracted_unpriced'
           WHEN rs.resolved_line_count < ls.line_count THEN 'priced_unresolved'
           ELSE 'fully_queryable'
       END AS reach_state
FROM postings p
LEFT JOIN line_stats ls ON ls.posting_id = p.id
LEFT JOIN priced ps     ON ps.posting_id = p.id
LEFT JOIN resolved rs   ON rs.posting_id = p.id
LEFT JOIN quarantine q  ON q.posting_id = p.id
ORDER BY p.fetched_at;

COMMENT ON VIEW  v_accounting                        IS 'Q4: "what did we miss" — every capture with its parse/price/resolve coverage and quarantine state, NO default filtering: captured_unextracted, extracted_unpriced, quarantined and unresolved postings are all visible rows (BRIEF §6 guardrail: unresolved is visible).';
COMMENT ON COLUMN v_accounting.line_count            IS 'Q4: lines in the current extraction; NULL when the capture was never extracted.';
COMMENT ON COLUMN v_accounting.priced_line_count     IS 'Q4: lines with a current ask — the priced leg of coverage.';
COMMENT ON COLUMN v_accounting.resolved_line_count   IS 'Q4: lines with a current resolution — explicitly-unresolved is the honest default state.';
COMMENT ON COLUMN v_accounting.quarantine_state      IS 'Q4: latest quarantine state (NULL = never quarantined).';
COMMENT ON COLUMN v_accounting.quarantine_reason     IS 'Q4: why — wanted post, out of scope, parse failure, ...';
COMMENT ON COLUMN v_accounting.reach_state           IS 'Q4: computed coverage stage; drops and quarantines count as long as they are visible with reasons.';

COMMIT;
