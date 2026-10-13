-- TechDeals v2 — posting-first schema, part 0: functions
-- See BRIEF.md §4 (settled design) and §6 (target queries).
--
-- Target-query shorthand used in every COMMENT across this schema:
--   Q1  cheapest N units of spec S available right now
--   Q2  what did this cost over time (price history, kinds separated)
--   Q3  what is this lot actually worth (decomposition + honest price basis)
--   Q4  what did we miss (every capture accounted for; quarantine visible)
-- Conventions (BRIEF §4): uuidv7 PKs, timestamptz everywhere,
-- text + CHECK (never enum types), append-only ledgers with reject-mutation
-- triggers, derived values in views only.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- uuidv7: PostgreSQL 18+ ships pg_catalog.uuidv7() natively and that is what
-- every PK DEFAULT below resolves to (pg_catalog precedes public in the search
-- path). On pre-18 servers this block installs an equivalent public.uuidv7()
-- fallback so the schema still applies unchanged.
DO $$
BEGIN
    IF to_regprocedure('pg_catalog.uuidv7()') IS NULL THEN
        EXECUTE $exec$
            CREATE OR REPLACE FUNCTION public.uuidv7() RETURNS uuid
            LANGUAGE sql VOLATILE PARALLEL SAFE AS $fn$
            SELECT (''
                || lpad(to_hex(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint), 12, '0')
                || '7'
                || lpad(to_hex(floor(random() * 4096)::int), 3, '0')
                || to_hex(8 + floor(random() * 4)::int)
                || lpad(to_hex(floor(random() * 1152921504606846976)::bigint), 15, '0')
            )::uuid
            $fn$;
            COMMENT ON FUNCTION public.uuidv7() IS
            'RFC 9562 version-7 UUID generator (fallback for pre-PG18 servers); default for every PK. Serves Q1-Q4: gives every row a time-ordered identity without a stored sequence.';
        $exec$;
    END IF;
END
$$;

-- Guard for append-only ledgers: any UPDATE/DELETE/TRUNCATE raises instead of
-- rewriting history. Corrections happen by appending a superseding row and
-- then setting the old row's superseded_by pointer (see supersede_only()).
CREATE OR REPLACE FUNCTION reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only: % on % is not permitted; append a superseding row instead',
        TG_OP, TG_TABLE_NAME;
END;
$$;

COMMENT ON FUNCTION reject_mutation() IS
'Body of every reject-mutation trigger on append-only tables (DELETE and TRUNCATE; UPDATE rows that have only the superseded_by pointer see supersede_only()). Serves Q2 (history is never rewritten) and Q4 (evidence is never destroyed).';

-- Append-only rows are immutable EXCEPT for one deliberate write: pointing an
-- old row at its superseder (superseded_by). Every other column must be
-- unchanged, the pointer can be set at most once (single supersession), and
-- the superseder must be a strictly later row (uuidv7 ordering makes
-- greater-than equivalent to created-later).
CREATE OR REPLACE FUNCTION supersede_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF to_jsonb(NEW) - 'superseded_by' IS DISTINCT FROM to_jsonb(OLD) - 'superseded_by' THEN
        RAISE EXCEPTION 'append-only: % on % may only set superseded_by (append a superseding row first, then point back)',
            TG_OP, TG_TABLE_NAME;
    END IF;
    IF OLD.superseded_by IS NOT NULL THEN
        RAISE EXCEPTION 'append-only: %.% is already superseded — single supersession only',
            TG_TABLE_NAME, OLD.id;
    END IF;
    IF NEW.superseded_by IS NULL OR NEW.superseded_by = OLD.id THEN
        RAISE EXCEPTION 'append-only: %.% superseded_by must name a different row',
            TG_TABLE_NAME, OLD.id;
    END IF;
    IF NEW.superseded_by < OLD.id THEN
        RAISE EXCEPTION 'append-only: %.% superseder % is not a later row than the superseded row',
            TG_TABLE_NAME, OLD.id, NEW.superseded_by;
    END IF;
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION supersede_only() IS
'UPDATE trigger body for tables with a superseded_by pointer (price_observations, resolutions, categories): permits only NULL->later-row supersession, once. Serves Q2: corrections are appended rows linked forward; nothing else on history is mutable.';

-- Writer-contract guard for the observation offer_key: the writer must derive
-- offer_key = sha256(posting.offer_key || '|' || subject_path). subject_path is
-- the stable position path of the subject inside the capture ('g<group index>'
-- for a sale group, 'g<group index>.<ordinal>[.<ordinal>...]' for a line), so
-- parser replays of the same capture hash to the same key regardless of the
-- model's random group ids. Serves Q1/Q2: offer stability across replays.
CREATE OR REPLACE FUNCTION observation_offer_key_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_posting_key text;
BEGIN
    SELECT offer_key INTO v_posting_key FROM postings WHERE id = NEW.posting_id;
    IF NEW.offer_key IS DISTINCT FROM
       encode(sha256(convert_to(v_posting_key || '|' || NEW.subject_path, 'UTF8')), 'hex') THEN
        RAISE EXCEPTION '%: offer_key must be sha256(posting offer_key | ''|'' | subject_path %)',
            TG_TABLE_NAME, NEW.subject_path;
    END IF;
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION observation_offer_key_guard() IS
'INSERT guard on price_observations and availability_observations: enforces the offer_key derivation from the posting natural key plus the subject position path, so a replay cannot mint a second logical offer and a shifted ordinal cannot silently alias one. Serves Q1/Q2.';

COMMIT;
