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
        'v_accounting', 'v_line_ram', 'v_stale_quarantine'
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
    v_key      text;
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

    -- price observation on a line (correct offer_key for its subject_path),
    -- then attempt to mutate it: only superseded_by may ever change
    INSERT INTO extractions (posting_id, parser_name)
    VALUES (v_posting, 'smoke-parser') RETURNING id INTO v_extract;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label, stated_quantity)
    VALUES (v_posting, v_extract, 1, 'smoke line', 1) RETURNING id INTO v_line;

    v_key := encode(sha256(convert_to(repeat('a', 64) || '|g0.1', 'UTF8')), 'hex');
    INSERT INTO price_observations
        (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
         price_kind, price_basis, amount, currency, quantity)
    VALUES (v_key, 'g0.1', v_posting, 'line', v_line, now(),
            'ask', 'explicit_unit', 10.00, 'USD', 1)
    RETURNING id INTO v_obs;
    v_caught := false;
    BEGIN
        UPDATE price_observations SET amount = 99 WHERE id = v_obs;
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: non-supersession UPDATE on price_observations was allowed'; END IF;

    -- a second posting: its line must not accept observations attributed to the first
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (repeat('e', 64), 'smoke', 'https://smoke.invalid/y', now(), repeat('f', 64), '{"smoke":true}')
    RETURNING id INTO v_posting2;
    INSERT INTO extractions (posting_id, parser_name)
    VALUES (v_posting2, 'smoke-parser') RETURNING id INTO v_extract2;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label, stated_quantity)
    VALUES (v_posting2, v_extract2, 1, 'foreign line', 1) RETURNING id INTO v_line2;

    v_caught := false;
    BEGIN
        INSERT INTO price_observations
            (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
             price_kind, price_basis, amount, currency, quantity)
        VALUES (repeat('1', 64), 'g0.1', v_posting, 'line', v_line2, now(),
                'ask', 'explicit_unit', 5.00, 'USD', 1);
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: cross-posting price observation was allowed'; END IF;

    -- sale_group_terms guard: quantity cannot exceed stated_quantity
    INSERT INTO sale_groups (posting_id, extraction_id, position, label)
    VALUES (v_posting, v_extract, 0, 'smoke lot') RETURNING id INTO v_group;
    v_caught := false;
    BEGIN
        INSERT INTO sale_group_terms (sale_group_id, line_id, line_quantity)
        VALUES (v_group, v_line, 5);  -- stated_quantity is 1
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: line_quantity over stated_quantity was allowed'; END IF;
END
$smoke$;

-- 4. offer_key writer contract (H2): the key must be sha256(posting key | '|'
--    | subject_path) — a wrong key is rejected, ordinal shifts change the key,
--    and identical replay observations are deduped by unique index.
DO $smoke$
DECLARE
    v_posting uuid;
    v_extract uuid;
    v_line1   uuid;
    v_line2   uuid;
    v_key1    text;
    v_key2    text;
    v_caught  boolean;
BEGIN
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (repeat('c', 64), 'smoke', 'https://smoke.invalid/k', now(), repeat('d', 64), '{"smoke":true}')
    RETURNING id INTO v_posting;
    INSERT INTO extractions (posting_id, parser_name)
    VALUES (v_posting, 'smoke-parser') RETURNING id INTO v_extract;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label, stated_quantity)
    VALUES (v_posting, v_extract, 1, 'line one', 1) RETURNING id INTO v_line1;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label, stated_quantity)
    VALUES (v_posting, v_extract, 2, 'line two', 1) RETURNING id INTO v_line2;

    v_key1 := encode(sha256(convert_to(repeat('c', 64) || '|g0.1', 'UTF8')), 'hex');
    v_key2 := encode(sha256(convert_to(repeat('c', 64) || '|g0.2', 'UTF8')), 'hex');
    IF v_key1 = v_key2 THEN
        RAISE EXCEPTION 'smoke fail: ordinal shift did not change the offer_key';
    END IF;

    -- wrong key for the stated subject_path: rejected
    v_caught := false;
    BEGIN
        INSERT INTO price_observations
            (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
             price_kind, price_basis, amount, currency, quantity)
        VALUES (repeat('2', 64), 'g0.1', v_posting, 'line', v_line1, now(),
                'ask', 'explicit_unit', 9.00, 'USD', 1);
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: wrong offer_key accepted'; END IF;

    -- correct keys for paths g0.1 / g0.2: accepted, distinct
    INSERT INTO price_observations
        (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
         price_kind, price_basis, amount, currency, quantity)
    VALUES (v_key1, 'g0.1', v_posting, 'line', v_line1, now(),
            'ask', 'explicit_unit', 9.00, 'USD', 1);
    INSERT INTO price_observations
        (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
         price_kind, price_basis, amount, currency, quantity)
    VALUES (v_key2, 'g0.2', v_posting, 'line', v_line2, now(),
            'ask', 'explicit_unit', 7.00, 'USD', 1);

    -- replay dedupe (price): same offer_key + observed_at + price_kind is blocked
    v_caught := false;
    BEGIN
        INSERT INTO price_observations
            (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
             price_kind, price_basis, amount, currency, quantity)
        VALUES (v_key1, 'g0.1', v_posting, 'line', v_line1, now(),
                'ask', 'explicit_unit', 9.00, 'USD', 1);
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: duplicate replay price observation accepted'; END IF;

    -- replay dedupe (availability): same offer_key + observed_at + state is blocked
    INSERT INTO availability_observations
        (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at, state)
    VALUES (v_key1, 'g0.1', v_posting, 'line', v_line1, now(), 'available');
    v_caught := false;
    BEGIN
        INSERT INTO availability_observations
            (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at, state)
        VALUES (v_key1, 'g0.1', v_posting, 'line', v_line1, now(), 'available');
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: duplicate replay availability observation accepted'; END IF;

    -- M4: bound_only with neither bound is rejected
    v_caught := false;
    BEGIN
        INSERT INTO price_observations
            (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
             price_kind, price_basis, amount, currency, quantity)
        VALUES (encode(sha256(convert_to(repeat('c', 64) || '|g0.3', 'UTF8')), 'hex'),
                'g0.3', v_posting, 'line', v_line1, now(),
                'ask', 'bound_only', NULL, 'USD', 1);
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: bound_only without bounds accepted'; END IF;
END
$smoke$;

-- 5. Supersession is the ONLY permitted update (L5): set once, to a strictly
--    later row; any other column change is rejected; single supersession.
DO $smoke$
DECLARE
    v_posting uuid;
    v_extract uuid;
    v_line    uuid;
    v_old     uuid;
    v_new     uuid;
    v_caught  boolean;
BEGIN
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (repeat('9', 64), 'smoke', 'https://smoke.invalid/s', now(), repeat('a', 64), '{"smoke":true}')
    RETURNING id INTO v_posting;
    INSERT INTO extractions (posting_id, parser_name)
    VALUES (v_posting, 'smoke-parser') RETURNING id INTO v_extract;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label, stated_quantity)
    VALUES (v_posting, v_extract, 1, 'supersede line', 1) RETURNING id INTO v_line;

    INSERT INTO price_observations
        (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
         price_kind, price_basis, amount, currency, quantity)
    VALUES (encode(sha256(convert_to(repeat('9', 64) || '|g0.1', 'UTF8')), 'hex'),
            'g0.1', v_posting, 'line', v_line, now(),
            'ask', 'explicit_unit', 10.00, 'USD', 1)
    RETURNING id INTO v_old;
    -- a uuidv7 ms tick later so the superseder is provably the later row
    PERFORM pg_sleep(0.003);
    INSERT INTO price_observations
        (offer_key, subject_path, posting_id, subject_kind, line_id, observed_at,
         price_kind, price_basis, amount, currency, quantity)
    VALUES (encode(sha256(convert_to(repeat('9', 64) || '|g0.1', 'UTF8')), 'hex'),
            'g0.1', v_posting, 'line', v_line, now() + interval '1 hour',
            'ask', 'explicit_unit', 12.00, 'USD', 1)
    RETURNING id INTO v_new;

    -- the one permitted update: point the old row at its later superseder
    UPDATE price_observations SET superseded_by = v_new WHERE id = v_old;

    -- second supersession attempt (already superseded) is rejected
    v_caught := false;
    BEGIN
        UPDATE price_observations SET superseded_by = NULL WHERE id = v_old;
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: double supersession allowed'; END IF;

    -- changing anything other than superseded_by is rejected
    v_caught := false;
    BEGIN
        UPDATE price_observations SET amount = 99 WHERE id = v_new;
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: non-pointer UPDATE on price_observations allowed'; END IF;
END
$smoke$;

-- 6. H3: one membership term per (group, line) — splitting an allocation
--    across two terms cannot dodge the stated-quantity cap.
DO $smoke$
DECLARE
    v_posting uuid;
    v_extract uuid;
    v_line    uuid;
    v_group   uuid;
    v_caught  boolean;
BEGIN
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (repeat('7', 64), 'smoke', 'https://smoke.invalid/m', now(), repeat('8', 64), '{"smoke":true}')
    RETURNING id INTO v_posting;
    INSERT INTO extractions (posting_id, parser_name)
    VALUES (v_posting, 'smoke-parser') RETURNING id INTO v_extract;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label, stated_quantity)
    VALUES (v_posting, v_extract, 1, 'one stated unit', 1.0) RETURNING id INTO v_line;
    INSERT INTO sale_groups (posting_id, extraction_id, position, label)
    VALUES (v_posting, v_extract, 0, 'split lot') RETURNING id INTO v_group;

    -- first 0.7 term passes the per-row cap...
    INSERT INTO sale_group_terms (sale_group_id, line_id, line_quantity)
    VALUES (v_group, v_line, 0.7);
    -- ...but the second term for the SAME (group, line) must fail: total would
    -- be 1.4 against a stated 1.0
    v_caught := false;
    BEGIN
        INSERT INTO sale_group_terms (sale_group_id, line_id, line_quantity)
        VALUES (v_group, v_line, 0.7);
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: second term for the same (group, line) accepted'; END IF;
END
$smoke$;

-- 7. S5: unstated quantities stay NULL — a term cannot claim a share of a
--    count the line never stated.
DO $smoke$
DECLARE
    v_posting uuid;
    v_extract uuid;
    v_line    uuid;
    v_group   uuid;
    v_caught  boolean;
BEGIN
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (repeat('5', 64), 'smoke', 'https://smoke.invalid/q', now(), repeat('6', 64), '{"smoke":true}')
    RETURNING id INTO v_posting;
    INSERT INTO extractions (posting_id, parser_name)
    VALUES (v_posting, 'smoke-parser') RETURNING id INTO v_extract;
    -- no stated_quantity: NULL is stored, never silently 1
    INSERT INTO lines (posting_id, extraction_id, ordinal, label)
    VALUES (v_posting, v_extract, 1, 'unstated count') RETURNING id INTO v_line;
    IF (SELECT stated_quantity FROM lines WHERE id = v_line) IS NOT NULL THEN
        RAISE EXCEPTION 'smoke fail: unstated quantity did not stay NULL';
    END IF;

    INSERT INTO sale_groups (posting_id, extraction_id, position, label)
    VALUES (v_posting, v_extract, 0, 'unknown-share lot') RETURNING id INTO v_group;
    v_caught := false;
    BEGIN
        INSERT INTO sale_group_terms (sale_group_id, line_id, line_quantity)
        VALUES (v_group, v_line, 1);  -- claims a share of an unstated count
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: stated term share for an unstated-count line accepted'; END IF;

    -- a term that honestly records the share as unknown is fine
    INSERT INTO sale_group_terms (sale_group_id, line_id, line_quantity)
    VALUES (v_group, v_line, NULL);
END
$smoke$;

-- 8. v_line_ram: deterministic ram_total from stated factors (8 x 64 -> 512);
--    an unstated child count yields NULL, never a guess.
DO $smoke$
DECLARE
    v_posting uuid;
    v_extract uuid;
    v_top     uuid;
    v_child   uuid;
    v_top2    uuid;
    n numeric;
BEGIN
    INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
    VALUES (repeat('3', 64), 'smoke', 'https://smoke.invalid/r', now(), repeat('4', 64), '{"smoke":true}')
    RETURNING id INTO v_posting;
    INSERT INTO extractions (posting_id, parser_name)
    VALUES (v_posting, 'smoke-parser') RETURNING id INTO v_extract;
    INSERT INTO lines (posting_id, extraction_id, ordinal, label)
    VALUES (v_posting, v_extract, 1, 'server with stated ram') RETURNING id INTO v_top;
    INSERT INTO lines (posting_id, extraction_id, parent_line_id, ordinal, label, stated_quantity, attributes)
    VALUES (v_posting, v_extract, v_top, 1, 'DDR4 RDIMM', 8, '{"ram_dimm_gb":64,"ram_type":"DDR4"}');
    SELECT ram_total_gb INTO n FROM v_line_ram WHERE line_id = v_top;
    IF n IS DISTINCT FROM 512 THEN
        RAISE EXCEPTION 'smoke fail: v_line_ram expected 512, got %', n;
    END IF;

    -- same shape but one child count unstated -> NULL, no silent sum
    INSERT INTO lines (posting_id, extraction_id, ordinal, label)
    VALUES (v_posting, v_extract, 2, 'server with unstated ram count') RETURNING id INTO v_top2;
    INSERT INTO lines (posting_id, extraction_id, parent_line_id, ordinal, label, stated_quantity, attributes)
    VALUES (v_posting, v_extract, v_top2, 1, 'DDR4 RDIMM', 8, '{"ram_dimm_gb":64,"ram_type":"DDR4"}');
    INSERT INTO lines (posting_id, extraction_id, parent_line_id, ordinal, label, attributes)
    VALUES (v_posting, v_extract, v_top2, 2, 'DDR4 RDIMM', '{"ram_dimm_gb":64,"ram_type":"DDR4"}');
    SELECT ram_total_gb INTO n FROM v_line_ram WHERE line_id = v_top2;
    IF n IS NOT NULL THEN
        RAISE EXCEPTION 'smoke fail: v_line_ram guessed a total despite an unstated child count';
    END IF;
END
$smoke$;

-- 9. Category correction is appended + superseded (L4), live name unique only.
DO $smoke$
DECLARE
    v_cat1 uuid;
    v_cat2 uuid;
    v_caught boolean;
BEGIN
    INSERT INTO categories (name, spec) VALUES ('32GB DDR4 RDIMM', '{"capacity_gb":32}'::jsonb)
    RETURNING id INTO v_cat1;
    -- same live name: rejected
    v_caught := false;
    BEGIN
        INSERT INTO categories (name, spec) VALUES ('32GB DDR4 RDIMM', '{"capacity_gb":32,"type":"DDR4"}'::jsonb);
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: duplicate live category name accepted'; END IF;

    -- correction: append replacement, then supersede the old row (the one
    -- permitted update; name uniqueness frees up once the old row is history)
    INSERT INTO categories (name, spec) VALUES ('32GB DDR4 RDIMM v2', '{"capacity_gb":32,"type":"DDR4"}'::jsonb)
    RETURNING id INTO v_cat2;
    PERFORM pg_sleep(0.003);
    UPDATE categories SET superseded_by = v_cat2 WHERE id = v_cat1;
    v_caught := false;
    BEGIN
        UPDATE categories SET superseded_by = v_cat2 WHERE id = v_cat1;  -- again
    EXCEPTION WHEN OTHERS THEN v_caught := true; END;
    IF NOT v_caught THEN RAISE EXCEPTION 'smoke fail: category double-supersession allowed'; END IF;
END
$smoke$;

-- 10. Every view parses and runs on the smoke data.
DO $smoke$
DECLARE n bigint; v text;
BEGIN
    FOREACH v IN ARRAY ARRAY[
        'v_current_extractions', 'v_cheapest_available', 'v_category_prices',
        'v_price_history', 'v_product_reference_price', 'v_lot_worth',
        'v_accounting', 'v_line_ram', 'v_stale_quarantine'
    ] LOOP
        EXECUTE 'SELECT count(*) FROM ' || v INTO n;
    END LOOP;
END
$smoke$;

DO $smoke$ BEGIN RAISE NOTICE 'smoke: all checks passed'; END $smoke$;
ROLLBACK;
