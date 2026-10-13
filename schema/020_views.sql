-- TechDeals v2 — posting-first schema, part 2: views
--
-- The four BRIEF §6 target queries, one view each:
--   Q1  v_cheapest_available   (+ v_category_prices, v_current_extractions,
--                                v_line_ram)
--   Q2  v_price_history
--   Q3  v_lot_worth            (+ v_product_reference_price)
--   Q4  v_accounting           (+ v_stale_quarantine)
-- All derived values (per-unit price, current state, latest extraction,
-- ram totals, component sums) are computed here in views — never stored.

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
--
-- Two kinds of purchasable offers feed Q1 (H1 fix):
--   * line-priced offers — the ask sits on a top-level line;
--   * group-priced offers — the ask sits on a sale group (a configured server
--     bundle, a lot). These were invisible before; they come in as their own
--     rows with a rollup of member-line attributes for spec filtering, the
--     member count, and single-member groups carrying their one line's
--     honest stated quantity / resolution.
-- Every row carries its latest availability state — 'unchecked' when the
-- subject was never checked (M1). Consumers of "cheapest AVAILABLE" filter
-- WHERE availability_state = 'available'; the unfiltered view is what the Q4
-- accounting reads.
CREATE VIEW v_cheapest_available AS
WITH latest_ask AS (
    -- newest LIVE ask per OFFER (offer_key = posting natural key + subject
    -- position path): the offer is the stable identity across replays, so
    -- grouping by offer_key — not by subject row — is what makes a deduped
    -- replay (identical re-observation skipped by the H2 index) still see the
    -- one logical offer instead of an empty or doubled answer.
    SELECT DISTINCT ON (offer_key)
           offer_key, subject_kind, line_id, sale_group_id,
           price_basis, currency, amount, quantity, bound_low, bound_high, observed_at
    FROM price_observations
    WHERE price_kind = 'ask' AND superseded_by IS NULL
    ORDER BY offer_key, observed_at DESC, id DESC
),
latest_avail AS (
    SELECT DISTINCT ON (offer_key) offer_key, state, observed_at
    FROM availability_observations
    ORDER BY offer_key, observed_at DESC, id DESC
),
line_offers AS (
    SELECT l.id              AS line_id,
           NULL::uuid        AS sale_group_id,
           'line'::text      AS subject_kind,
           l.posting_id,
           p.source, p.url, p.fetched_at,
           l.label,
           l.stated_quantity,
           l.attributes,
           NULL::integer     AS member_line_count,
           l.id              AS single_member_line_id,
           a.offer_key, a.price_basis, a.currency, a.amount,
           a.quantity        AS amount_covers_units,
           a.amount / NULLIF(a.quantity, 0) AS unit_price,
           a.bound_low, a.bound_high,
           a.observed_at     AS price_observed_at,
           COALESCE(av.state, 'unchecked') AS availability_state,
           av.observed_at    AS availability_checked_at,
           r.product_key, r.product_name, r.confidence AS resolution_confidence
    FROM lines l
    JOIN postings p             ON p.id = l.posting_id
    JOIN v_current_extractions c ON c.posting_id = l.posting_id
                                 AND c.extraction_id = l.extraction_id
    JOIN latest_ask a            ON a.subject_kind = 'line' AND a.line_id = l.id
    LEFT JOIN latest_avail av    ON av.offer_key = a.offer_key
    LEFT JOIN LATERAL (
        SELECT product_key, product_name, confidence
        FROM resolutions
        WHERE line_id = l.id AND superseded_by IS NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    ) r ON true
),
group_offers AS (
    -- H1: group-priced offers (configured servers / lots). The offer is
    -- resolved by its stable key computed from the CURRENT pass's group
    -- position — sha256(posting natural key | '|g' || position) — so a deduped
    -- replay (whose identical observations hang on an earlier pass's subject
    -- rows) still surfaces the offer against the newest parse.
    SELECT NULL::uuid       AS line_id,
           sg.id            AS sale_group_id,
           'sale_group'::text AS subject_kind,
           sg.posting_id,
           p.source, p.url, p.fetched_at,
           sg.label         AS label,
           (CASE WHEN mem.member_line_count = 1
                 THEN (SELECT l.stated_quantity
                       FROM sale_group_terms t JOIN lines l ON l.id = t.line_id
                       WHERE t.sale_group_id = sg.id LIMIT 1) END) AS stated_quantity,
           mem.attributes,
           mem.member_line_count,
           (CASE WHEN mem.member_line_count = 1
                 THEN (SELECT t.line_id FROM sale_group_terms t WHERE t.sale_group_id = sg.id LIMIT 1) END)
                            AS single_member_line_id,
           a.offer_key, a.price_basis, a.currency, a.amount,
           a.quantity        AS amount_covers_units,
           a.amount / NULLIF(a.quantity, 0) AS unit_price,
           a.bound_low, a.bound_high,
           a.observed_at     AS price_observed_at,
           COALESCE(av.state, 'unchecked') AS availability_state,
           av.observed_at    AS availability_checked_at,
           r.product_key, r.product_name, r.confidence AS resolution_confidence
    FROM sale_groups sg
    JOIN postings p             ON p.id = sg.posting_id
    JOIN v_current_extractions c ON c.posting_id = sg.posting_id
                                 AND c.extraction_id = sg.extraction_id
    JOIN latest_ask a            ON a.subject_kind = 'sale_group'
                                 AND a.offer_key = encode(sha256(convert_to(p.offer_key || '|g' || sg.position::text, 'UTF8')), 'hex')
    LEFT JOIN latest_avail av    ON av.offer_key = a.offer_key
    LEFT JOIN LATERAL (
        SELECT count(*)                     AS member_line_count,
               -- deterministic spec rollup: per attribute key, the value from
               -- the highest-ordinal member line wins (jsonb_each over each
               -- member, DISTINCT ON the key)
               (SELECT jsonb_object_agg(kv.k, kv.v)
                  FROM (
                      SELECT DISTINCT ON (je.k) je.k AS k, je.v AS v
                      FROM sale_group_terms t2
                      JOIN lines m ON m.id = t2.line_id
                      CROSS JOIN LATERAL jsonb_each(m.attributes) je(k, v)
                      WHERE t2.sale_group_id = sg.id
                      ORDER BY je.k, m.ordinal DESC
                  ) kv) AS attributes
        FROM sale_group_terms t
        JOIN lines m ON m.id = t.line_id
        WHERE t.sale_group_id = sg.id
    ) mem ON true
    LEFT JOIN LATERAL (
        SELECT product_key, product_name, confidence
        FROM resolutions
        WHERE line_id = (SELECT t.line_id FROM sale_group_terms t WHERE t.sale_group_id = sg.id LIMIT 1)
          AND superseded_by IS NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    ) r ON mem.member_line_count = 1
)
SELECT line_id, sale_group_id, subject_kind, posting_id, source, url, fetched_at,
       label, stated_quantity, attributes, member_line_count, single_member_line_id,
       offer_key, price_basis, currency, amount, amount_covers_units, unit_price,
       bound_low, bound_high, price_observed_at, availability_state,
       availability_checked_at, product_key, product_name, resolution_confidence
FROM (
    SELECT * FROM line_offers
    UNION ALL
    SELECT * FROM group_offers
) u
ORDER BY unit_price NULLS LAST, bound_low NULLS LAST;

COMMENT ON VIEW  v_cheapest_available                  IS 'Q1: "cheapest N units of spec S available right now" — one row per currently-asked subject, LINE-priced or GROUP-priced (configured servers / lots are visible: H1). Rows carry the latest availability state, ''unchecked'' when never checked (M1); filter WHERE availability_state = ''available'' for the literal cheapest-available query, filter attributes for spec S, LIMIT N. Unresolved lines appear with product_key NULL (unresolved is never filtered out). bound_only rows expose bounds instead of unit_price; unit_price is NULL when the unit count is unstated.';
COMMENT ON COLUMN v_cheapest_available.line_id          IS 'Q1: the purchasable line (NULL for group-priced offers).';
COMMENT ON COLUMN v_cheapest_available.sale_group_id    IS 'Q1: the purchasable bundle when the ask sits on a sale group (H1).';
COMMENT ON COLUMN v_cheapest_available.subject_kind     IS 'Q1: line | sale_group — which kind of subject the row prices.';
COMMENT ON COLUMN v_cheapest_available.source           IS 'Q1: provenance — where the offer was seen.';
COMMENT ON COLUMN v_cheapest_available.url              IS 'Q1: provenance URL.';
COMMENT ON COLUMN v_cheapest_available.fetched_at       IS 'Q1: provenance — when the capture was fetched.';
COMMENT ON COLUMN v_cheapest_available.label            IS 'Q1: seller''s stated description (line or group label).';
COMMENT ON COLUMN v_cheapest_available.attributes       IS 'Q1: spec attributes to filter on — the line''s own, or the deterministic rollup of member-line attributes for group rows (highest-ordinal value per key).';
COMMENT ON COLUMN v_cheapest_available.member_line_count IS 'Q1 (H1 honesty): how many lines the group-priced bundle includes; NULL for line-priced rows.';
COMMENT ON COLUMN v_cheapest_available.single_member_line_id IS 'Q1 (H1 honesty): the one member line when the bundle is a single line (lot of N identical units) — the only case where per-line detail is honest; NULL for multi-line bundles.';
COMMENT ON COLUMN v_cheapest_available.stated_quantity   IS 'Q1: units obtainable per purchase; NULL when not stated — group rows carry it only for single-line bundles.';
COMMENT ON COLUMN v_cheapest_available.unit_price       IS 'Q1: derived per-unit price (amount / units covered) — computed here, never stored; NULL when the unit count is unstated (not confidently per-unit).';
COMMENT ON COLUMN v_cheapest_available.price_basis      IS 'Q1: basis of the ask (bound_only rows expose bounds instead of unit_price).';
COMMENT ON COLUMN v_cheapest_available.bound_low        IS 'Q1: lower bound when the ask is ambiguous — reported, not allocated.';
COMMENT ON COLUMN v_cheapest_available.bound_high       IS 'Q1: upper bound when the ask is ambiguous.';
COMMENT ON COLUMN v_cheapest_available.availability_state IS 'Q1: latest availability — available | unavailable | unknown | unchecked (M1: never-checked subjects are visible as unchecked, not dropped).';
COMMENT ON COLUMN v_cheapest_available.product_key      IS 'Q1: resolved identity (NULL when unresolved — still visible); for group rows, resolved only for single-line bundles.';

-- Named-spec variant of Q1: categories are data rows, not DDL.
-- Only LIVE (non-superseded) category rows are read — superseded specs are
-- history (L4: category corrections are appended rows, not updates).
CREATE VIEW v_category_prices AS
SELECT c.id     AS category_id,
       c.name   AS category_name,
       ca.*
FROM categories c
JOIN v_cheapest_available ca ON ca.attributes @> c.spec
WHERE c.superseded_by IS NULL
ORDER BY c.name, ca.unit_price NULLS LAST, ca.bound_low NULLS LAST;

COMMENT ON VIEW  v_category_prices               IS 'Q1: cheapest offers per named category spec (adding a category = inserting a row into categories; a corrected category = appended replacement + superseded old row, read live-only here).';
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
-- M2: priced/resolved counts read only the CURRENT extraction's lines.
priced AS (
    SELECT l.posting_id,
           count(DISTINCT l.id) AS priced_line_count,
           -- M1: the accounting view reads availability too — how many priced
           -- lines are actually available right now (latest per-line state,
           -- 'unchecked' when never checked).
           count(DISTINCT l.id) FILTER (WHERE COALESCE(av.state, 'unchecked') = 'available') AS available_line_count
    FROM lines l
    JOIN v_current_extractions c ON c.posting_id = l.posting_id
                                 AND c.extraction_id = l.extraction_id
    JOIN price_observations po ON po.subject_kind = 'line'
                              AND po.line_id = l.id
                              AND po.price_kind = 'ask'
                              AND po.superseded_by IS NULL
    LEFT JOIN LATERAL (
        SELECT state
        FROM availability_observations
        WHERE line_id = l.id
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
    ) av ON true
    GROUP BY l.posting_id
),
-- group-priced coverage (H1): postings whose purchasable units are priced at
-- sale-group level count as priced for the reach ladder. Offers resolve by
-- their stable key (posting key + group position) — a deduped replay's
-- observations hang on the earlier pass's subject rows, and the CURRENT pass's
-- groups must still count as priced.
priced_groups AS (
    SELECT sg.posting_id, count(DISTINCT sg.id) AS priced_group_count
    FROM sale_groups sg
    JOIN postings p ON p.id = sg.posting_id
    JOIN v_current_extractions c ON c.posting_id = sg.posting_id
                                 AND c.extraction_id = sg.extraction_id
    WHERE EXISTS (
        SELECT 1 FROM price_observations po
        WHERE po.subject_kind = 'sale_group'
          AND po.offer_key = encode(sha256(convert_to(p.offer_key || '|g' || sg.position::text, 'UTF8')), 'hex')
          AND po.price_kind = 'ask' AND po.superseded_by IS NULL
    )
    GROUP BY sg.posting_id
),
resolved AS (
    SELECT l.posting_id, count(DISTINCT l.id) AS resolved_line_count
    FROM lines l
    JOIN v_current_extractions c ON c.posting_id = l.posting_id
                                 AND c.extraction_id = l.extraction_id
    JOIN resolutions r ON r.line_id = l.id AND r.superseded_by IS NULL
    GROUP BY l.posting_id
),
-- M3: line-level quarantines affect the counts — a line whose latest event is
-- 'quarantined' is excluded from the resolved/available denominators rather
-- than silently counting as unresolved.
line_quarantine AS (
    SELECT l.posting_id, count(*) AS quarantined_line_count
    FROM (
        SELECT DISTINCT ON (line_id) line_id, state
        FROM quarantine_events
        WHERE line_id IS NOT NULL
        ORDER BY line_id, created_at DESC, id DESC
    ) ql
    JOIN lines l             ON l.id = ql.line_id
    JOIN v_current_extractions c ON c.posting_id = l.posting_id
                                 AND c.extraction_id = l.extraction_id
    WHERE ql.state = 'quarantined'
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
       ps.available_line_count,
       pg.priced_group_count,
       rs.resolved_line_count,
       ql.quarantined_line_count,
       q.state       AS quarantine_state,
       q.reason      AS quarantine_reason,
       q.detail      AS quarantine_detail,
       CASE
           WHEN q.state = 'quarantined'    THEN 'quarantined'
           WHEN ls.line_count IS NULL      THEN 'captured_unextracted'
           WHEN ls.line_count = 0          THEN 'extracted_empty'
           WHEN COALESCE(ps.priced_line_count, 0) = 0
                AND COALESCE(pg.priced_group_count, 0) = 0 THEN 'extracted_unpriced'
           WHEN COALESCE(rs.resolved_line_count, 0) < ls.line_count - COALESCE(ql.quarantined_line_count, 0) THEN 'priced_unresolved'
           ELSE 'fully_queryable'
       END AS reach_state
FROM postings p
LEFT JOIN line_stats ls     ON ls.posting_id = p.id
LEFT JOIN priced ps         ON ps.posting_id = p.id
LEFT JOIN priced_groups pg  ON pg.posting_id = p.id
LEFT JOIN resolved rs       ON rs.posting_id = p.id
LEFT JOIN line_quarantine ql ON ql.posting_id = p.id
LEFT JOIN quarantine q      ON q.posting_id = p.id
ORDER BY p.fetched_at;

COMMENT ON VIEW  v_accounting                        IS 'Q4: "what did we miss" — every capture with its parse/price/resolve coverage and quarantine state, NO default filtering: captured_unextracted, extracted_empty (M3: a zero-line extraction is not the same as never extracted), extracted_unpriced, quarantined and unresolved postings are all visible rows (BRIEF §6 guardrail: unresolved is visible). Line-priced AND group-priced coverage both count toward the priced leg (H1). Stale parse-failure quarantines (subject re-extracted successfully later, never released) are caught by v_stale_quarantine.';
COMMENT ON COLUMN v_accounting.line_count            IS 'Q4: lines in the current extraction; NULL when the capture was never extracted (0 = extracted, but nothing decomposed).';
COMMENT ON COLUMN v_accounting.priced_line_count     IS 'Q4: current-extraction lines with a live ask — the line-priced leg of coverage.';
COMMENT ON COLUMN v_accounting.available_line_count  IS 'Q4 (M1): priced lines whose latest availability state is ''available'' — the view reads availability, not just price.';
COMMENT ON COLUMN v_accounting.priced_group_count    IS 'Q4 (H1): current-extraction sale groups with a live ask — the group-priced leg of coverage (a configured server priced as a bundle is priced, not unpriced).';
COMMENT ON COLUMN v_accounting.resolved_line_count   IS 'Q4: current-extraction lines with a live resolution — explicitly-unresolved is the honest default state.';
COMMENT ON COLUMN v_accounting.quarantined_line_count IS 'Q4 (M3): current-extraction lines whose latest quarantine event is ''quarantined'' — visible in the counts, subtracted from the unresolved denominator.';
COMMENT ON COLUMN v_accounting.quarantine_state      IS 'Q4: latest posting-level quarantine state (NULL = never quarantined).';
COMMENT ON COLUMN v_accounting.quarantine_reason     IS 'Q4: why — wanted post, out of scope, parse failure, ...';
COMMENT ON COLUMN v_accounting.reach_state           IS 'Q4: computed coverage stage; drops and quarantines count as long as they are visible with reasons. quarantined > captured_unextracted > extracted_empty (M3) > extracted_unpriced > priced_unresolved > fully_queryable.';

-- Q4 hygiene companion: quarantine events that were never released even
-- though the subject was later re-extracted successfully (an extraction AFTER
-- the quarantine that decomposed into lines). These are the stale
-- parse_failed events bring-up runs left behind; the Q4 accounting query
-- catches them so they can be marked 'released'.
CREATE VIEW v_stale_quarantine AS
SELECT q.id        AS quarantine_event_id,
       q.posting_id, q.line_id, q.reason, q.detail,
       q.created_at AS quarantined_at,
       (SELECT max(e.created_at) FROM extractions e WHERE e.posting_id = q.posting_id) AS latest_extraction_at
FROM quarantine_events q
WHERE q.state = 'quarantined'
  AND NOT EXISTS (
      SELECT 1 FROM quarantine_events r
      WHERE r.posting_id = q.posting_id
        AND r.line_id IS NOT DISTINCT FROM q.line_id
        AND r.created_at > q.created_at
        AND r.state = 'released'
  )
  AND EXISTS (
      SELECT 1 FROM extractions e
      WHERE e.posting_id = q.posting_id
        AND e.created_at > q.created_at
        AND EXISTS (SELECT 1 FROM lines l WHERE l.extraction_id = e.id)
  );

COMMENT ON VIEW  v_stale_quarantine                IS 'Q4 hygiene: still-quarantined subjects (posting or line) whose posting has a LATER extraction that produced lines, with no later release event — i.e. quarantine state that success has overtaken. Each row is a quarantine event that should be marked ''released''.';
COMMENT ON COLUMN v_stale_quarantine.quarantine_event_id IS 'Q4: the stale event itself.';
COMMENT ON COLUMN v_stale_quarantine.quarantined_at      IS 'Q4: when the stale quarantine was recorded.';
COMMENT ON COLUMN v_stale_quarantine.latest_extraction_at IS 'Q4: proof of the later successful extraction (quarantined_at < latest_extraction_at by the view''s predicate).';

-- Q1 helper: deterministic RAM total, computed — never stored (BRIEF §6
-- "no stored derivations"). The pilot's three ram_total_gb misses are exactly
-- this: quantity (count) and ram_dimm_gb (per-module size) are both stated;
-- the product is a derivation, so it lives in a view. Deliberately NOT a
-- prompt change: aggregation from stated factors is deterministic, and an LLM
-- doing arithmetic is a trust risk for zero gain (ram_total decision, 2026-10-12).
-- Only stated factors multiply: a line with unstated count or missing/unparsed
-- per-module size yields NULL — no silent 8×64GB guesses.
CREATE VIEW v_line_ram AS
WITH child_agg AS (
    SELECT l.id AS line_id, l.posting_id, l.label, l.stated_quantity, l.attributes,
           count(m.id) AS child_count,
           count(m.id) FILTER (WHERE m.stated_quantity IS NOT NULL
                                 AND m.attributes ? 'ram_dimm_gb'
                                 AND m.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$') AS stated_child_count,
           sum(m.stated_quantity * (m.attributes->>'ram_dimm_gb')::numeric)
               FILTER (WHERE m.stated_quantity IS NOT NULL
                        AND m.attributes ? 'ram_dimm_gb'
                        AND m.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$') AS child_ram_total_gb
    FROM lines l
    JOIN v_current_extractions c ON c.posting_id = l.posting_id
                                 AND c.extraction_id = l.extraction_id
    LEFT JOIN lines m ON m.parent_line_id = l.id
    WHERE l.parent_line_id IS NULL
    GROUP BY l.id
)
SELECT line_id, posting_id, label, stated_quantity, attributes,
       CASE
           -- the line states both factors itself (e.g. one DIMM line: 1 × 64)
           WHEN stated_quantity IS NOT NULL AND attributes ? 'ram_dimm_gb'
                AND attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$'
               THEN stated_quantity * (attributes->>'ram_dimm_gb')::numeric
           -- every child states its count and its per-module size (8 × 64)
           WHEN child_count > 0 AND child_count = stated_child_count
               THEN child_ram_total_gb
       END AS ram_total_gb
FROM child_agg;

COMMENT ON VIEW  v_line_ram                     IS 'Q1: ram_total_gb derived from stated factors only — own (stated_quantity × ram_dimm_gb) or the all-children sum when every child states both factors. NULL when anything is unstated; serves the spec-S filter for RAM capacity without storing a derived attribute.';
COMMENT ON COLUMN v_line_ram.line_id             IS 'Q1: the top-level line the RAM total belongs to.';
COMMENT ON COLUMN v_line_ram.ram_total_gb        IS 'Q1: derived total GB — own factors when the line states them, else the sum over children when ALL children state count × per-module size; NULL otherwise (never guessed).';

-- Mixed DIMM lines are siblings (8×32 and 8×16), not parent/child. Sum only
-- the member lines that state both factors. A member that states a module
-- size but no count blocks the total — a partial sum would invent the rest.
CREATE VIEW v_group_ram AS
SELECT sg.id AS sale_group_id,
       sg.posting_id,
       CASE
           WHEN count(*) FILTER (
                    WHERE m.attributes ? 'ram_dimm_gb'
                      AND m.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$'
                      AND m.stated_quantity IS NULL
                ) = 0
            AND count(*) FILTER (
                    WHERE m.attributes ? 'ram_dimm_gb'
                      AND m.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$'
                      AND m.stated_quantity IS NOT NULL
                ) > 0
           THEN sum(m.stated_quantity * (m.attributes->>'ram_dimm_gb')::numeric)
                FILTER (
                    WHERE m.stated_quantity IS NOT NULL
                      AND m.attributes ? 'ram_dimm_gb'
                      AND m.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$'
                )
       END AS ram_total_gb
FROM sale_groups sg
JOIN v_current_extractions c ON c.extraction_id = sg.extraction_id
JOIN sale_group_terms t ON t.sale_group_id = sg.id
JOIN lines m ON m.id = t.line_id
GROUP BY sg.id;

COMMENT ON VIEW v_group_ram IS 'Q1: RAM total across sibling member lines of one sale group (8×32 + 8×16). NULL when any DIMM line leaves its count unstated.';

-- Q3 part-out. Two numbers, kept apart:
--   exact_value  — stated quantity × cheapest standalone ask for the same product_key.
--   ram_rate_value — stated RAM gigabytes × the cheapest DDR4 $/GB from single-module comps.
-- The rate is an implication (one module size standing in for another). It is not
-- added into exact_value. A line with a total and no stick count gets a rate or nothing,
-- never a fabricated stick count. Lines with neither stay unpriced.
CREATE OR REPLACE VIEW v_ddr4_gb_rate AS
SELECT min(ca.unit_price / (ca.attributes->>'ram_dimm_gb')::numeric) AS usd_per_gb,
       count(*) AS comps,
       count(*) FILTER (WHERE ca.availability_state = 'available') AS comps_available
FROM v_cheapest_available ca
WHERE ca.unit_price IS NOT NULL
  AND ca.price_basis IN ('explicit_unit', 'homogeneous_division')
  AND (ca.member_line_count IS NULL OR ca.member_line_count = 1)
  AND ca.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$'
  AND (ca.attributes->>'ram_dimm_gb')::numeric > 0
  AND COALESCE(ca.attributes->>'ram_type', ca.product_key, '') ILIKE '%ddr4%';

COMMENT ON VIEW v_ddr4_gb_rate IS 'Q3: cheapest observed dollars per gigabyte among standalone DDR4 modules. A rate, not a quote for a different size.';

CREATE OR REPLACE VIEW v_partout AS
WITH exact_comp AS (
    SELECT product_key,
           min(unit_price) AS unit_price,
           count(*)        AS comps,
           count(*) FILTER (WHERE availability_state = 'available') AS comps_available
    FROM v_cheapest_available
    WHERE unit_price IS NOT NULL
      AND price_basis IN ('explicit_unit', 'homogeneous_division')
      AND (member_line_count IS NULL OR member_line_count = 1)
      AND product_key IS NOT NULL
    GROUP BY product_key
),
lines AS (
    SELECT sg.id AS sale_group_id,
           sg.posting_id,
           sg.label AS lot_label,
           l.id AS line_id,
           l.label AS line_label,
           l.stated_quantity,
           l.attributes,
           r.product_key,
           c.unit_price AS exact_unit,
           c.comps AS exact_comps,
           c.comps_available AS exact_comps_available,
           CASE
               WHEN l.stated_quantity IS NOT NULL
                    AND l.attributes->>'ram_dimm_gb' ~ '^[0-9]+(\.[0-9]+)?$'
                   THEN l.stated_quantity * (l.attributes->>'ram_dimm_gb')::numeric
               WHEN l.attributes->>'ram_total_gb' ~ '^[0-9]+(\.[0-9]+)?$'
                   THEN (l.attributes->>'ram_total_gb')::numeric
           END AS ram_gb
    FROM sale_groups sg
    JOIN v_current_extractions cur ON cur.extraction_id = sg.extraction_id
    JOIN sale_group_terms t ON t.sale_group_id = sg.id
    JOIN lines l ON l.id = t.line_id
    LEFT JOIN LATERAL (
        SELECT product_key
        FROM resolutions
        WHERE line_id = l.id AND superseded_by IS NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    ) r ON true
    LEFT JOIN exact_comp c ON c.product_key = r.product_key
),
priced AS (
    SELECT ln.*,
           CASE WHEN ln.exact_unit IS NOT NULL AND ln.stated_quantity IS NOT NULL
                THEN ln.exact_unit * ln.stated_quantity END AS exact_value,
           CASE WHEN ln.ram_gb IS NOT NULL
                     AND COALESCE(ln.attributes->>'ram_type', '') ILIKE '%ddr4%'
                     AND rate.usd_per_gb IS NOT NULL
                THEN ln.ram_gb * rate.usd_per_gb END AS ram_rate_value,
           rate.usd_per_gb,
           rate.comps AS ram_rate_comps
    FROM lines ln
    LEFT JOIN v_ddr4_gb_rate rate ON true
)
SELECT p.sale_group_id,
       p.posting_id,
       p.lot_label,
       ask.amount AS lot_ask,
       ask.price_basis AS lot_price_basis,
       sum(p.exact_value) AS exact_value,
       sum(p.ram_rate_value) AS ram_rate_value,
       count(*) FILTER (WHERE p.exact_value IS NOT NULL) AS lines_exact,
       count(*) FILTER (WHERE p.ram_rate_value IS NOT NULL AND p.exact_value IS NULL) AS lines_ram_rate_only,
       count(*) AS lines_total,
       count(*) FILTER (WHERE p.exact_value IS NULL AND p.ram_rate_value IS NULL) AS lines_unpriced,
       ask.amount - sum(p.exact_value) AS ask_minus_exact,
       bool_and(p.exact_value IS NULL OR p.exact_comps_available > 0) AS exact_refs_in_stock
FROM priced p
LEFT JOIN LATERAL (
    SELECT amount, price_basis
    FROM price_observations po
    WHERE po.sale_group_id = p.sale_group_id
      AND po.price_kind = 'ask'
      AND po.superseded_by IS NULL
    ORDER BY po.observed_at DESC, po.id DESC
    LIMIT 1
) ask ON true
GROUP BY p.sale_group_id, p.posting_id, p.lot_label, ask.amount, ask.price_basis;

COMMENT ON VIEW v_partout IS 'Q3: part-out of a sale group. exact_value is stated quantity times a same-key standalone ask. ram_rate_value is stated DDR4 gigabytes times v_ddr4_gb_rate and is not folded into exact_value. lines_unpriced are the gap. A complete deal verdict requires lines_unpriced = 0.';

COMMIT;
