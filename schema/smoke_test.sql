-- Smoke test for the TechDeals v2 posting-first schema.
-- Runs entirely inside one transaction and ROLLs BACK: leaves nothing behind.
-- Run with: psql -v ON_ERROR_STOP=1 -f schema/smoke_test.sql
-- Expected outcome: NOTICE "smoke: all checks passed", then ROLLBACK, exit 0.
\set ON_ERROR_STOP on
BEGIN;

-- 1. All tables and views exist.
DO $smoke$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'extraction_batches', 'postings', 'extractions', 'lines',
        'sale_groups', 'sale_group_terms',
        'price_observations', 'availability_observations',
        'resolutions', 'quarantine_events', 'categories'
    ] LOOP
        IF to_regclass('public.' || t) IS NULL THEN
            RAISE EXCEPTION 'smoke fail: table % missing', t;
        END IF;
    END LOOP;
    FOREACH t IN ARRAY ARRAY[
        'v_current_extractions', 'v_cheapest_available', 'v_category_prices',
        'v_price_history', 'v_product_reference_price', 'v_lot_worth',
        'v_accounting'
    ] LOOP
        IF to_regclass('public.' || t) IS NULL THEN
            RAISE EXCEPTION 'smoke fail: view % missing', t;
        END IF;
    END LOOP;
END
$smoke$;

-- 2. uuidv7() produces RFC 9562 version 7 with variant 10xx.
DO $smoke$
DECLARE u text;
BEGIN
    SELECT translate(uuidv7()::text, '-', '') INTO u;
    IF substring(u FROM 13 FOR 1) <> '7' THEN
        RAISE EXCEPTION 'smoke fail: uuidv7 version nibble is %', substring(u FROM 13 FOR 1);
    END IF;
    IF substring(u FROM 17 FOR 1) !~ '[89ab]' THEN
        RAISE EXCEPTION 'smoke fail: uuidv7 variant nibble wrong';
    END IF;
END
$smoke$;

-- 3. Reject-mutation triggers fire on append-only tables, and insert guards
--    reject subjects from a foreign posting.
DO $smoke$
DECLARE
    v_posting  uuid;
    v_posting2 uuid;
    v_extract  uuid;
    v_extract2 uuid;
    v_line     uuid;
    v_line2    uuid;
    v_group    uuid;
    v_obs      uuid;
    v_caught   boolean;
BEGIN
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (repeat('a', 64), 'smoke', 'https://smoke.invalid/x', now(), repeat('b', 64), '{"smoke":true}')
    RETURNING id INTO v_posting;

    v_caught := false;
    BEGIN
        UPDATE postings SET checksum = repeat('c', 64) WHERE id = v_posting;
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: UPDATE on postings was allowed'; END IF;

    v_caught := false;
    BEGIN
        DELETE FROM postings WHERE id = v_posting;
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: DELETE on postings was allowed'; END IF;

    -- price observation on a line, then attempt to mutate it
    INSERT INTO extractions (posting_id, parser_name)
    VALUES (v_posting, 'smoke-parser') RETURNING id INTO v_extract;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label)
    VALUES (v_posting, v_extract, 1, 'smoke line') RETURNING id INTO v_line;
    INSERT INTO price_observations
        (offer_key, posting_id, subject_kind, line_id, observed_at,
         price_kind, price_basis, amount, currency, quantity)
    VALUES (repeat('d', 64), v_posting, 'line', v_line, now(),
            'ask', 'explicit_unit', 10.00, 'USD', 1)
    RETURNING id INTO v_obs;
    v_caught := false;
    BEGIN
        UPDATE price_observations SET amount = 99 WHERE id = v_obs;
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: UPDATE on price_observations was allowed'; END IF;

    -- a second posting: its line must not accept observations attributed to the first
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (repeat('e', 64), 'smoke', 'https://smoke.invalid/y', now(), repeat('f', 64), '{"smoke":true}')
    RETURNING id INTO v_posting2;
    INSERT INTO extractions (posting_id, parser_name)
    VALUES (v_posting2, 'smoke-parser') RETURNING id INTO v_extract2;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label)
    VALUES (v_posting2, v_extract2, 1, 'foreign line') RETURNING id INTO v_line2;

    v_caught := false;
    BEGIN
        INSERT INTO price_observations
            (offer_key, posting_id, subject_kind, line_id, observed_at,
             price_kind, price_basis, amount, currency, quantity)
        VALUES (repeat('1', 64), v_posting, 'line', v_line2, now(),
                'ask', 'explicit_unit', 5.00, 'USD', 1);
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: cross-posting price observation was allowed'; END IF;

    -- sale_group_terms guard: quantity cannot exceed stated_quantity
    INSERT INTO sale_groups (posting_id, extraction_id, label)
    VALUES (v_posting, v_extract, 'smoke lot') RETURNING id INTO v_group;
    v_caught := false;
    BEGIN
        INSERT INTO sale_group_terms (sale_group_id, line_id, line_quantity)
        VALUES (v_group, v_line, 5);  -- stated_quantity defaults to 1
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: line_quantity over stated_quantity was allowed'; END IF;
END
$smoke$;

-- 4. Every view parses and runs on an empty ledger.
DO $smoke$
DECLARE n bigint; v text;
BEGIN
    FOREACH v IN ARRAY ARRAY[
        'v_current_extractions', 'v_cheapest_available', 'v_category_prices',
        'v_price_history', 'v_product_reference_price', 'v_lot_worth',
        'v_accounting'
    ] LOOP
        EXECUTE 'SELECT count(*) FROM ' || v INTO n;
    END LOOP;
END
$smoke$;

DO $smoke$ BEGIN RAISE NOTICE 'smoke: all checks passed'; END $smoke$;
ROLLBACK;
