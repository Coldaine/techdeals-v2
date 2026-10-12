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
-- rewriting history. Corrections happen by appending a superseding row
-- (superseded_by), never by mutating an existing one.
CREATE OR REPLACE FUNCTION reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only: % on % is not permitted; append a superseding row instead',
        TG_OP, TG_TABLE_NAME;
END;
$$;

COMMENT ON FUNCTION reject_mutation() IS
'Body of every reject-mutation trigger on append-only tables. Serves Q2 (history is never rewritten) and Q4 (evidence is never destroyed).';

COMMIT;
