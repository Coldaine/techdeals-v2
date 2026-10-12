-- TechDeals v2 — posting-first schema, part 1: tables, constraints, triggers
--
-- Layer shape (BRIEF §4, settled design — do not reopen):
--   posting -> lines -> sale groups/terms -> observations -> resolutions
--   (+ quarantine states and extraction provenance around them)
--
-- Every table and every column names the BRIEF §6 target query it serves.
-- Constructions that serve none of the four are deliberately absent.
-- Append-only ledgers: UPDATE/DELETE/TRUNCATE rejected outright EXCEPT the one
-- permitted correction write — setting superseded_by (supersede_only(),
-- 000_functions.sql) after the superseding row exists.

BEGIN;

-- ------------------------------------------------------- parse provenance --

CREATE TABLE extraction_batches (
    id             uuid PRIMARY KEY DEFAULT uuidv7(),
    model          text    NOT NULL,
    prompt_version text    NOT NULL,
    cost_usd       numeric CHECK (cost_usd IS NULL OR cost_usd >= 0),
    listing_count  integer NOT NULL DEFAULT 0 CHECK (listing_count >= 0),
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER extraction_batches_reject_mutation
    BEFORE UPDATE OR DELETE ON extraction_batches
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER extraction_batches_reject_truncate
    BEFORE TRUNCATE ON extraction_batches
    FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();

COMMENT ON TABLE  extraction_batches               IS 'One LLM parse call covering many postings at once (batch discipline: never one listing per call). Serves Q4: engine accounting and batch economics (BRIEF §3 acceptance 6).';
COMMENT ON COLUMN extraction_batches.id             IS 'Serves Q4: identity of the batch for cost accounting.';
COMMENT ON COLUMN extraction_batches.model          IS 'Serves Q4: which model ran the batch; batch-economics accounting.';
COMMENT ON COLUMN extraction_batches.prompt_version IS 'Serves Q4: reproducibility of extractions (replay safety relies on knowing which prompt produced which lines).';
COMMENT ON COLUMN extraction_batches.cost_usd       IS 'Serves Q4: cost per batch (NULL when unknown, 0 for free endpoints).';
COMMENT ON COLUMN extraction_batches.listing_count  IS 'Serves Q4: makes batch discipline auditable (dozens per call, not one).';
COMMENT ON COLUMN extraction_batches.created_at     IS 'Serves Q4: accounting timeline.';

-- --------------------------------------------------------------- postings --

CREATE TABLE postings (
    id         uuid PRIMARY KEY DEFAULT uuidv7(),
    offer_key  text NOT NULL CHECK (offer_key ~ '^[0-9a-f]{64}$'),
    source     text NOT NULL,
    url        text NOT NULL,
    fetched_at timestamptz NOT NULL,
    checksum   text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
    payload    jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX postings_offer_key_key ON postings (offer_key);
CREATE INDEX postings_fetched_at_idx ON postings (fetched_at);
-- No GIN index on payload: no target query filters raw payload JSON (guardrail:
-- schema additions need a query). Payload is evidence for re-extraction (Q4),
-- read whole-row by the engine, never pattern-matched in SQL.

CREATE TRIGGER postings_reject_mutation
    BEFORE UPDATE OR DELETE ON postings
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER postings_reject_truncate
    BEFORE TRUNCATE ON postings
    FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();

COMMENT ON TABLE  postings            IS 'The atomic unit of evidence: one captured listing (page payload + source + fetch time), whatever it contains. Posting is the center of the model (BRIEF §4). Serves all four; it IS the accounting unit for Q4 and the provenance anchor for Q1-Q3.';
COMMENT ON COLUMN postings.id         IS 'Serves Q4: every capture lands as exactly one posting row — nothing silently dropped.';
COMMENT ON COLUMN postings.offer_key  IS 'Serves Q4 (and replay-safety for Q1-Q3): sha256 of the natural key (source | url | fetched_at), stable across parser replays so re-ingesting a capture never invents a second posting (BRIEF §3 acceptance 5, 8).';
COMMENT ON COLUMN postings.source     IS 'Serves Q4: provenance — where it was seen (source name).';
COMMENT ON COLUMN postings.url        IS 'Serves Q4: provenance — where it was seen (URL).';
COMMENT ON COLUMN postings.fetched_at IS 'Serves Q2: provenance — when it was seen; anchors every price/availability time series.';
COMMENT ON COLUMN postings.checksum   IS 'Serves Q4: provenance — integrity checksum of the payload, so corrupted re-captures are detectable.';
COMMENT ON COLUMN postings.payload    IS 'Serves Q4: the raw capture kept intact so missed/mis-parsed/quarantined postings can be re-extracted (BRIEF §6 query 4: "parse failures surfaced with their payload intact").';
COMMENT ON COLUMN postings.created_at IS 'Serves Q4: when the posting row was written (ingest time, distinct from fetch time).';

CREATE TABLE extractions (
    id          uuid PRIMARY KEY DEFAULT uuidv7(),
    posting_id  uuid NOT NULL REFERENCES postings (id),
    batch_id    uuid REFERENCES extraction_batches (id),
    parser_name text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX extractions_posting_idx ON extractions (posting_id, created_at);

CREATE TRIGGER extractions_reject_mutation
    BEFORE UPDATE OR DELETE ON extractions
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER extractions_reject_truncate
    BEFORE TRUNCATE ON extractions
    FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();

COMMENT ON TABLE  extractions             IS 'One parse pass over one posting; re-running a parser appends a new extraction instead of mutating the old one (replay safety, BRIEF §3 acceptance 8). Serves Q4: the parse leg of the run->fetch->parse provenance chain.';
COMMENT ON COLUMN extractions.id          IS 'Serves Q4: identity of the parse pass; views read the newest extraction per posting.';
COMMENT ON COLUMN extractions.posting_id  IS 'Serves Q4: which capture was parsed.';
COMMENT ON COLUMN extractions.batch_id    IS 'Serves Q4: links the parse to its LLM batch for batch-economics accounting; NULL only for parses that ran outside a batch.';
COMMENT ON COLUMN extractions.parser_name IS 'Serves Q4: which parser produced the lines — replay safety requires identifying the producer.';
COMMENT ON COLUMN extractions.created_at  IS 'Serves Q4: ordering of parse passes; newest wins in the read views.';

-- ------------------------------------------------------------------ lines --

CREATE TABLE lines (
    id                     uuid PRIMARY KEY DEFAULT uuidv7(),
    posting_id             uuid NOT NULL REFERENCES postings (id),
    extraction_id          uuid NOT NULL REFERENCES extractions (id),
    parent_line_id         uuid REFERENCES lines (id),
    ordinal                integer NOT NULL CHECK (ordinal >= 1),
    label                  text    NOT NULL,
    stated_quantity        numeric CHECK (stated_quantity IS NULL OR stated_quantity > 0),
    separately_purchasable boolean NOT NULL DEFAULT false,
    attributes             jsonb   NOT NULL DEFAULT '{}'::jsonb
);
-- A line nests only under a line of the same posting and same extraction.
CREATE UNIQUE INDEX lines_ordinal_unique
    ON lines (extraction_id, COALESCE(parent_line_id, '00000000-0000-0000-0000-000000000000'::uuid), ordinal);
CREATE INDEX lines_posting_idx ON lines (posting_id, extraction_id);
CREATE INDEX lines_parent_idx ON lines (parent_line_id);
-- Consumer: v_category_prices (`ca.attributes @> c.spec`) — the GIN index makes
-- the Q1 spec filter index-supported.
CREATE INDEX lines_attributes_gin ON lines USING gin (attributes);

CREATE TRIGGER lines_reject_mutation
    BEFORE UPDATE OR DELETE ON lines
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER lines_reject_truncate
    BEFORE TRUNCATE ON lines
    FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();

CREATE OR REPLACE FUNCTION lines_parent_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_posting    uuid;
    v_extraction uuid;
BEGIN
    IF NEW.parent_line_id IS NOT NULL THEN
        SELECT posting_id, extraction_id INTO v_posting, v_extraction
        FROM lines WHERE id = NEW.parent_line_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'lines: parent_line_id % does not exist', NEW.parent_line_id;
        END IF;
        IF v_posting <> NEW.posting_id OR v_extraction <> NEW.extraction_id THEN
            RAISE EXCEPTION 'lines: parent line must belong to the same posting and extraction';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER lines_parent_guard BEFORE INSERT ON lines
    FOR EACH ROW EXECUTE FUNCTION lines_parent_guard();

COMMENT ON TABLE  lines                          IS 'One item decomposed out of a posting; contents nest via parent_line_id (a configured server, a lot manifest). Serves Q1 (the unit spec S matches), Q2 (the subject of history), Q3 (the valuation unit), Q4 (decomposition coverage).';
COMMENT ON COLUMN lines.id                      IS 'Serves Q1-Q3: identity of the decomposed item.';
COMMENT ON COLUMN lines.posting_id              IS 'Serves Q4: provenance — which capture this line was decomposed from.';
COMMENT ON COLUMN lines.extraction_id           IS 'Serves Q4 (protects Q1-Q3): which parse pass produced this line; a replay appends new lines, never mutates old ones (BRIEF §3 acceptance 8).';
COMMENT ON COLUMN lines.parent_line_id          IS 'Serves Q3: nested contents — components of a server line or manifest rows of a lot line.';
COMMENT ON COLUMN lines.ordinal                 IS 'Serves Q3 (and offer-key stability): position of the line within its parent; stable across replays, so writers hash it into the natural key behind offer_key.';
COMMENT ON COLUMN lines.label                   IS 'Serves Q1, Q3: the seller''s stated name/description, verbatim as parsed.';
COMMENT ON COLUMN lines.stated_quantity         IS 'Serves Q1 (the N units behind a price) and Q3 (lot decomposition: the 50-DIMM lot is one line with stated_quantity 50). NULL when the count is not stated — the engine also marks those lines attributes.quantity_stated = false; NULL is never a silent stand-in for 1 (unresolved counts must stay visible, BRIEF §6 "no silent allocation" spirit).';
COMMENT ON COLUMN lines.separately_purchasable  IS 'Serves Q1: whether the line can be bought on its own or only inside a sale group.';
COMMENT ON COLUMN lines.attributes              IS 'Serves Q1: extracted spec attributes (the indexed substrate for "spec S" and for dynamic categories — data, not DDL); also feeds Q3 valuation comps.';

-- ----------------------------------------------------------- sale groups --

CREATE TABLE sale_groups (
    id            uuid PRIMARY KEY DEFAULT uuidv7(),
    posting_id    uuid NOT NULL REFERENCES postings (id),
    extraction_id uuid NOT NULL REFERENCES extractions (id),
    position      integer NOT NULL CHECK (position >= 0),
    label         text
);
CREATE INDEX sale_groups_posting_idx ON sale_groups (posting_id, extraction_id);
-- The group's position is the stable half of its offer natural key
-- (offer_key = sha256(posting natural key | '|g' || position)) — the group
-- analogue of lines.ordinal. Offer-key stability across replays (H2, BRIEF
-- §3.5) requires recording it; it is part of the natural key, not a derived
-- value. One position per extraction pass.
CREATE UNIQUE INDEX sale_groups_position_key
    ON sale_groups (extraction_id, position);

CREATE TRIGGER sale_groups_reject_mutation
    BEFORE UPDATE OR DELETE ON sale_groups
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER sale_groups_reject_truncate
    BEFORE TRUNCATE ON sale_groups
    FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();

COMMENT ON TABLE  sale_groups               IS 'What can actually be bought together in one purchase (a configured server as one lot, or each DIMM separately — alternative purchasable shapes are separate groups). Serves Q1 (the purchasable unit) and Q3 (the lot being valued).';
COMMENT ON COLUMN sale_groups.id            IS 'Serves Q1, Q3: identity of the purchasable bundle.';
COMMENT ON COLUMN sale_groups.posting_id    IS 'Serves Q4: provenance of the group.';
COMMENT ON COLUMN sale_groups.extraction_id IS 'Serves Q4: which parse pass produced the group (replay safety).';
COMMENT ON COLUMN sale_groups.position      IS 'Serves Q1 (offer-key stability): the group''s zero-based position within its extraction pass — the stable half of the offer natural key behind offer_key (sha256(posting natural key | ''|g'' || position)), so replays hash the same logical offer regardless of parser-version group ids.';
COMMENT ON COLUMN sale_groups.label         IS 'Serves Q1, Q3: what the purchase shape is, as stated by the seller/parser.';

CREATE TABLE sale_group_terms (
    id            uuid PRIMARY KEY DEFAULT uuidv7(),
    sale_group_id uuid NOT NULL REFERENCES sale_groups (id),
    line_id       uuid NOT NULL REFERENCES lines (id),
    line_quantity numeric CHECK (line_quantity IS NULL OR line_quantity > 0)
);
CREATE INDEX sale_group_terms_group_idx ON sale_group_terms (sale_group_id);
-- H3: one membership term per (group, line). Without this, the per-row
-- quantity cap can be bypassed by splitting an allocation across several
-- terms (two 0.7 terms against a stated 1.0 -> 1.4 total). With the unique
-- index, the per-row guard against stated_quantity is also the aggregate
-- guard, because there is exactly one term to cap.
CREATE UNIQUE INDEX sale_group_terms_group_line_key
    ON sale_group_terms (sale_group_id, line_id);

CREATE TRIGGER sale_group_terms_reject_mutation
    BEFORE UPDATE OR DELETE ON sale_group_terms
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER sale_group_terms_reject_truncate
    BEFORE TRUNCATE ON sale_group_terms
    FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();

CREATE OR REPLACE FUNCTION sale_group_terms_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_group_posting    uuid;
    v_group_extraction uuid;
    v_line_posting     uuid;
    v_line_extraction  uuid;
    v_stated           numeric;
BEGIN
    SELECT posting_id, extraction_id INTO v_group_posting, v_group_extraction
    FROM sale_groups WHERE id = NEW.sale_group_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'sale_group_terms: sale_group_id % does not exist', NEW.sale_group_id;
    END IF;
    SELECT posting_id, extraction_id, stated_quantity INTO v_line_posting, v_line_extraction, v_stated
    FROM lines WHERE id = NEW.line_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'sale_group_terms: line_id % does not exist', NEW.line_id;
    END IF;
    IF v_group_posting <> v_line_posting OR v_group_extraction <> v_line_extraction THEN
        RAISE EXCEPTION 'sale_group_terms: line and group must belong to the same posting and extraction';
    END IF;
    -- Quantity discipline: a term may state a share only of a count the line
    -- actually states. An unstated line count stays NULL everywhere —
    -- never silently promoted to 1 — and it cannot back a stated term share.
    IF v_stated IS NULL AND NEW.line_quantity IS NOT NULL THEN
        RAISE EXCEPTION 'sale_group_terms: line_quantity % stated for a line whose own count is unstated (no silent unit assumption)',
            NEW.line_quantity;
    END IF;
    IF v_stated IS NOT NULL AND NEW.line_quantity IS NOT NULL AND NEW.line_quantity > v_stated THEN
        RAISE EXCEPTION 'sale_group_terms: line_quantity % exceeds the line''s stated_quantity % (no silent over-allocation)',
            NEW.line_quantity, v_stated;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER sale_group_terms_guard BEFORE INSERT ON sale_group_terms
    FOR EACH ROW EXECUTE FUNCTION sale_group_terms_guard();

COMMENT ON TABLE  sale_group_terms                 IS 'Membership and quantity terms of a sale group: which line, how many of its stated units are in this purchase. Serves Q1 (what is included in the purchasable unit) and Q3 (the decomposition being valued).';
COMMENT ON COLUMN sale_group_terms.id              IS 'Serves Q1, Q3: identity of the membership term.';
COMMENT ON COLUMN sale_group_terms.sale_group_id   IS 'Serves Q1, Q3: the purchase this term belongs to.';
COMMENT ON COLUMN sale_group_terms.line_id         IS 'Serves Q1, Q3: the included line.';
COMMENT ON COLUMN sale_group_terms.line_quantity   IS 'Serves Q1, Q3: how many of the line''s stated units are in this purchase (e.g. all 16 DIMMs, or 4 of the 8 drives). NULL when the share itself is not stated — it is never defaulted. DB-enforced guards: UNIQUE(sale_group_id, line_id) (one term per line per group, so splitting an allocation across terms cannot dodge the cap) plus the insert guard capping line_quantity at stated_quantity, and rejecting a stated share for a line whose own count is unstated — allocation cannot be silently inflated.';

-- -------------------------------------------------------- price ledger ----

-- Shared by both observation ledgers: the subject must exist and belong to the
-- observation's posting.
CREATE OR REPLACE FUNCTION observation_subject_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_posting uuid;
BEGIN
    IF NEW.subject_kind = 'line' THEN
        SELECT posting_id INTO v_posting FROM lines WHERE id = NEW.line_id;
    ELSIF NEW.subject_kind = 'sale_group' THEN
        SELECT posting_id INTO v_posting FROM sale_groups WHERE id = NEW.sale_group_id;
    END IF;
    IF v_posting IS NULL THEN
        RAISE EXCEPTION '%: subject does not exist', TG_TABLE_NAME;
    END IF;
    IF v_posting <> NEW.posting_id THEN
        RAISE EXCEPTION '%: subject belongs to a different posting', TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE price_observations (
    id           uuid PRIMARY KEY DEFAULT uuidv7(),
    offer_key    text NOT NULL CHECK (offer_key ~ '^[0-9a-f]{64}$'),
    subject_path text NOT NULL,
    posting_id   uuid NOT NULL REFERENCES postings (id),
    subject_kind text NOT NULL CHECK (subject_kind IN ('line', 'sale_group')),
    line_id      uuid REFERENCES lines (id),
    sale_group_id uuid REFERENCES sale_groups (id),
    observed_at  timestamptz NOT NULL,
    price_kind   text NOT NULL CHECK (price_kind IN ('ask', 'bid', 'sold', 'cost_basis', 'reference')),
    price_basis  text NOT NULL CHECK (price_basis IN ('explicit_unit', 'homogeneous_division', 'bound_only', 'allocated')),
    amount       numeric CHECK (amount IS NULL OR amount >= 0),
    currency     text NOT NULL DEFAULT 'USD' CHECK (currency ~ '^[A-Z]{3}$'),
    quantity     numeric CHECK (quantity IS NULL OR quantity > 0),
    bound_low    numeric CHECK (bound_low IS NULL OR bound_low >= 0),
    bound_high   numeric CHECK (bound_high IS NULL OR bound_high >= 0),
    basis_note   text,
    superseded_by uuid REFERENCES price_observations (id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT price_observations_subject_shape CHECK (
        (subject_kind = 'line'       AND line_id       IS NOT NULL AND sale_group_id IS NULL) OR
        (subject_kind = 'sale_group' AND sale_group_id IS NOT NULL AND line_id      IS NULL)
    ),
    CONSTRAINT price_observations_subject_path_shape CHECK (
        -- position path of the subject: 'g<group index>' for a group,
        -- 'g<group index>.<ordinal>[.<ordinal>...]' for a line (ordinals only)
        (subject_kind = 'sale_group' AND subject_path ~ '^g[0-9]+$') OR
        (subject_kind = 'line'       AND subject_path ~ '^g[0-9]+(\.[0-9]+)+$')
    ),
    CONSTRAINT price_observations_amount_present CHECK (
        price_basis = 'bound_only' OR amount IS NOT NULL
    ),
    -- bound_only with neither bound states nothing — reject at the door
    CONSTRAINT price_observations_bound_only_needs_bound CHECK (
        price_basis <> 'bound_only' OR bound_low IS NOT NULL OR bound_high IS NOT NULL
    ),
    CONSTRAINT price_observations_bound_order CHECK (
        bound_low IS NULL OR bound_high IS NULL OR bound_low <= bound_high
    )
);
CREATE INDEX price_observations_offer_idx   ON price_observations (offer_key, observed_at);
CREATE INDEX price_observations_line_idx    ON price_observations (line_id, observed_at);
CREATE INDEX price_observations_group_idx   ON price_observations (sale_group_id, observed_at);
CREATE INDEX price_observations_kind_idx    ON price_observations (price_kind, observed_at);
-- Replay-dedupe (H2): the same offer at the same instant with the same kind is
-- by construction a replay artifact, not a second observation — blocked here.
-- PARTIAL (live rows only): a replay whose value CHANGES must be recordable.
-- Because observed_at is pinned to the capture's fetch time, such a correction
-- is recorded by first superseding the live row (superseded_by set via
-- supersede_only()), which removes it from this index, then appending the new
-- live row. A full unique index would make that correction impossible forever.
CREATE UNIQUE INDEX price_observations_replay_dedupe
    ON price_observations (offer_key, observed_at, price_kind)
    WHERE superseded_by IS NULL;
-- Single supersession (L5): a superseded row is pointed at by at most one
-- superseder, so correction chains are linear.
CREATE UNIQUE INDEX price_observations_single_supersession
    ON price_observations (superseded_by) WHERE superseded_by IS NOT NULL;

CREATE TRIGGER price_observations_supersede_update
    BEFORE UPDATE ON price_observations
    FOR EACH ROW EXECUTE FUNCTION supersede_only();
CREATE TRIGGER price_observations_reject_delete
    BEFORE DELETE ON price_observations
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER price_observations_reject_truncate
    BEFORE TRUNCATE ON price_observations
    FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER price_observations_subject_guard BEFORE INSERT ON price_observations
    FOR EACH ROW EXECUTE FUNCTION observation_subject_guard();
CREATE TRIGGER price_observations_offer_key_guard BEFORE INSERT ON price_observations
    FOR EACH ROW EXECUTE FUNCTION observation_offer_key_guard();

COMMENT ON TABLE  price_observations                    IS 'Append-only ledger of price events on lines and sale groups; corrections append a superseding row and point the old row at it via superseded_by (the supersede_only update is the one permitted mutation — everything else is rejected). Serves Q2 (the time series), Q1 (current asks), Q3 (lot ask + per-line basis).';
COMMENT ON COLUMN price_observations.id                 IS 'Serves Q2: ledger identity; time-ordered by uuidv7.';
COMMENT ON COLUMN price_observations.offer_key          IS 'Serves Q1, Q2: replay-stable identity of the offer priced — sha256(posting offer_key | ''|'' | subject_path), enforced by the observation_offer_key_guard trigger. Same natural key as the availability ledger, so price and availability join on subject identity.';
COMMENT ON COLUMN price_observations.subject_path       IS 'Serves Q1, Q2 (offer-key stability): the subject''s stable position path in the capture — ''g<group index>'' for a sale group, ''g<group index>.<ordinal>[.<ordinal>...]'' for a line. Ordinal shifts across parser versions change the path, so a shifted line cannot silently alias the old offer; replays with stable structure hash identically.';
COMMENT ON COLUMN price_observations.posting_id         IS 'Serves Q2, Q4: provenance — which capture the price was observed in.';
COMMENT ON COLUMN price_observations.subject_kind       IS 'Serves Q1-Q3: whether the subject is a line or a sale group.';
COMMENT ON COLUMN price_observations.line_id            IS 'Serves Q1-Q3: the priced line when subject_kind = line.';
COMMENT ON COLUMN price_observations.sale_group_id      IS 'Serves Q1, Q3: the priced bundle when subject_kind = sale_group (e.g. the lot ask).';
COMMENT ON COLUMN price_observations.observed_at        IS 'Serves Q2: the time-series axis — when this price was in effect.';
COMMENT ON COLUMN price_observations.price_kind         IS 'Serves Q2 (and the acceptance rule behind Q3): ask/bid/sold/cost_basis/reference are separate series, never conflated (BRIEF §3 acceptance 3).';
COMMENT ON COLUMN price_observations.price_basis        IS 'Serves Q3: how the amount relates to units — explicit_unit, homogeneous_division, bound_only, allocated. A lot total is never divided into unit prices without homogeneous_division or allocated (BRIEF §3 acceptance 3, §6 guardrail).';
COMMENT ON COLUMN price_observations.amount             IS 'Serves Q1-Q3: the observed amount, covering `quantity` units. NULL only for bound_only rows.';
COMMENT ON COLUMN price_observations.currency           IS 'Serves Q1-Q3: currency of the amount.';
COMMENT ON COLUMN price_observations.quantity           IS 'Serves Q1, Q3: how many units `amount` covers — NULL when the unit count is not stated (never silently defaulted to 1); per-unit prices are derived in views and are NULL when quantity is unknown.';
COMMENT ON COLUMN price_observations.bound_low          IS 'Serves Q3: lower bound for bound_only rows — ambiguous cases are reported as bounds, never silently allocated; bound_only requires at least one bound (DB CHECK).';
COMMENT ON COLUMN price_observations.bound_high         IS 'Serves Q3: upper bound for bound_only rows.';
COMMENT ON COLUMN price_observations.basis_note         IS 'Serves Q3: the recorded basis of any apportionment (what was divided/allocated, and by what rationale).';
COMMENT ON COLUMN price_observations.superseded_by      IS 'Serves Q2: corrections point forward to the superseding observation, set once via the supersede_only update (superseder must be a strictly later row; single supersession enforced by unique index) — history is never rewritten.';
COMMENT ON COLUMN price_observations.created_at         IS 'Serves Q2, Q4: ingest time of the observation.';

-- ------------------------------------------------- availability ledger ----

CREATE TABLE availability_observations (
    id           uuid PRIMARY KEY DEFAULT uuidv7(),
    offer_key    text NOT NULL CHECK (offer_key ~ '^[0-9a-f]{64}$'),
    subject_path text NOT NULL,
    posting_id   uuid NOT NULL REFERENCES postings (id),
    subject_kind text NOT NULL CHECK (subject_kind IN ('line', 'sale_group')),
    line_id      uuid REFERENCES lines (id),
    sale_group_id uuid REFERENCES sale_groups (id),
    observed_at  timestamptz NOT NULL,
    state        text NOT NULL CHECK (state IN ('available', 'unavailable', 'unknown')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT availability_observations_subject_shape CHECK (
        (subject_kind = 'line'       AND line_id       IS NOT NULL AND sale_group_id IS NULL) OR
        (subject_kind = 'sale_group' AND sale_group_id IS NOT NULL AND line_id      IS NULL)
    ),
    CONSTRAINT availability_observations_subject_path_shape CHECK (
        (subject_kind = 'sale_group' AND subject_path ~ '^g[0-9]+$') OR
        (subject_kind = 'line'       AND subject_path ~ '^g[0-9]+(\.[0-9]+)+$')
    )
);
CREATE INDEX availability_observations_offer_idx ON availability_observations (offer_key, observed_at);
CREATE INDEX availability_observations_line_idx  ON availability_observations (line_id, observed_at);
CREATE INDEX availability_observations_group_idx ON availability_observations (sale_group_id, observed_at);
-- Replay-dedupe (H2): same offer, same instant, same state = replay artifact.
-- A state CHANGE at the same observed_at is kept (both rows are evidence of
-- the parser disagreement; the view reads the newest by id) — hence state in
-- the key. Availability has no supersession column: nothing is ever deleted,
-- and a differing-state replay stays visible rather than being blocked.
CREATE UNIQUE INDEX availability_observations_replay_dedupe
    ON availability_observations (offer_key, observed_at, state);

CREATE TRIGGER availability_observations_reject_mutation
    BEFORE UPDATE OR DELETE ON availability_observations
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER availability_observations_reject_truncate
    BEFORE TRUNCATE ON availability_observations
    FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER availability_observations_subject_guard BEFORE INSERT ON availability_observations
    FOR EACH ROW EXECUTE FUNCTION observation_subject_guard();
CREATE TRIGGER availability_observations_offer_key_guard BEFORE INSERT ON availability_observations
    FOR EACH ROW EXECUTE FUNCTION observation_offer_key_guard();

COMMENT ON TABLE  availability_observations               IS 'Append-only ledger of purchasability state over time. Serves Q1 ("available right now" is the latest state) and Q2 (availability history alongside price history); Q4 counts unchecked/unknown states.';
COMMENT ON COLUMN availability_observations.id            IS 'Serves Q1, Q2: ledger identity.';
COMMENT ON COLUMN availability_observations.offer_key     IS 'Serves Q1: same replay-stable offer identity as price_observations — sha256(posting offer_key | ''|'' | subject_path), trigger-enforced — so price and availability share subject identity.';
COMMENT ON COLUMN availability_observations.subject_path  IS 'Serves Q1 (offer-key stability): the subject''s stable position path in the capture, same vocabulary as price_observations.subject_path.';
COMMENT ON COLUMN availability_observations.posting_id    IS 'Serves Q2, Q4: provenance of the check.';
COMMENT ON COLUMN availability_observations.subject_kind  IS 'Serves Q1: line or sale group.';
COMMENT ON COLUMN availability_observations.line_id       IS 'Serves Q1: the line whose purchasability was checked.';
COMMENT ON COLUMN availability_observations.sale_group_id IS 'Serves Q1: the sale group whose purchasability was checked.';
COMMENT ON COLUMN availability_observations.observed_at   IS 'Serves Q2: when the check happened.';
COMMENT ON COLUMN availability_observations.state         IS 'Serves Q1, Q4: available/unavailable/unknown — unknown keeps failed checks visible instead of silently dropping them.';
COMMENT ON COLUMN availability_observations.created_at    IS 'Serves Q4: ingest time.';

-- ---------------------------------------------------------- resolutions ---

CREATE TABLE resolutions (
    id           uuid PRIMARY KEY DEFAULT uuidv7(),
    posting_id   uuid NOT NULL REFERENCES postings (id),
    line_id      uuid REFERENCES lines (id),
    product_key  text NOT NULL,
    product_name text NOT NULL,
    confidence   numeric NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    method       text NOT NULL,
    superseded_by uuid REFERENCES resolutions (id),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX resolutions_line_idx    ON resolutions (line_id, created_at);
CREATE INDEX resolutions_product_idx ON resolutions (product_key);
-- Single supersession (same discipline as price_observations, L5).
CREATE UNIQUE INDEX resolutions_single_supersession
    ON resolutions (superseded_by) WHERE superseded_by IS NOT NULL;

CREATE TRIGGER resolutions_supersede_update
    BEFORE UPDATE ON resolutions
    FOR EACH ROW EXECUTE FUNCTION supersede_only();
CREATE TRIGGER resolutions_reject_delete
    BEFORE DELETE ON resolutions
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER resolutions_reject_truncate
    BEFORE TRUNCATE ON resolutions
    FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();

COMMENT ON TABLE  resolutions              IS 'Candidate product matches, confidence-scored, re-runnable, never a write gate (BRIEF §4): a re-run appends new rows and points the old row at its superseder (the one permitted update — see supersede_only()); the newest non-superseded row per line is what views read. Unresolved postings stay visible everywhere. Serves Q1 (identity for spec grouping) and Q3 (comps matching); Q4 measures unresolved coverage.';
COMMENT ON COLUMN resolutions.id           IS 'Serves Q4: identity of the resolution pass result.';
COMMENT ON COLUMN resolutions.posting_id   IS 'Serves Q4: provenance — which posting the resolution belongs to.';
COMMENT ON COLUMN resolutions.line_id      IS 'Serves Q1, Q3: the line resolved; NULL for posting-level resolutions.';
COMMENT ON COLUMN resolutions.product_key  IS 'Serves Q1, Q2, Q3: stable identity of the proposed product — what history and comps are grouped on.';
COMMENT ON COLUMN resolutions.product_name IS 'Serves Q1, Q2: human-readable product identity.';
COMMENT ON COLUMN resolutions.confidence   IS 'Serves Q1, Q4: lets consumers weigh answers; scoring never blocks a posting from being visible.';
COMMENT ON COLUMN resolutions.method       IS 'Serves Q4: which scorer/model produced the match (re-runnable, reproducible).';
COMMENT ON COLUMN resolutions.superseded_by IS 'Serves Q4: a later pass supersedes — set once, only pointing at a strictly later row; nothing is rewritten or deleted.';
COMMENT ON COLUMN resolutions.created_at   IS 'Serves Q4: ordering of resolution passes.';

-- ----------------------------------------------------------- quarantine ---

CREATE TABLE quarantine_events (
    id         uuid PRIMARY KEY DEFAULT uuidv7(),
    posting_id uuid NOT NULL REFERENCES postings (id),
    line_id    uuid REFERENCES lines (id),
    state      text NOT NULL CHECK (state IN ('quarantined', 'released')),
    reason     text NOT NULL,
    detail     text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX quarantine_events_posting_idx ON quarantine_events (posting_id, created_at);

CREATE TRIGGER quarantine_events_reject_mutation
    BEFORE UPDATE OR DELETE ON quarantine_events
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER quarantine_events_reject_truncate
    BEFORE TRUNCATE ON quarantine_events
    FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();

COMMENT ON TABLE  quarantine_events              IS 'First-class quarantine states with reasons (BRIEF §4): wanted posts, out-of-scope items, parse failures — visible in counts, never force-fit and never silently dropped (BRIEF §3 acceptance 9). Serves Q4 entirely.';
COMMENT ON COLUMN quarantine_events.id           IS 'Serves Q4: event identity; quarantine->release is an appended event, not an update.';
COMMENT ON COLUMN quarantine_events.posting_id   IS 'Serves Q4: which capture was quarantined.';
COMMENT ON COLUMN quarantine_events.line_id      IS 'Serves Q4: a single out-of-scope line within an otherwise kept posting; NULL for posting-level quarantine.';
COMMENT ON COLUMN quarantine_events.state        IS 'Serves Q4: quarantined/released — the latest event per subject is its state.';
COMMENT ON COLUMN quarantine_events.reason       IS 'Serves Q4: why — wanted_post, out_of_scope_consumer, not_inventory, dead_page, duplicate, parse_failed, transport_failed (batch call could not reach the model), batch_call_failed (model/gateway rejected the call), price_ambiguous (stated price not confidently storable), quantity_conflict (stated unit count contradicts the group''s terms), ... (documented vocabulary; deliberately not a CHECK so new reasons are data, not migrations).';
COMMENT ON COLUMN quarantine_events.detail       IS 'Serves Q4: free-text explanation; the payload stays intact on the posting for re-extraction.';
COMMENT ON COLUMN quarantine_events.created_at   IS 'Serves Q4: when the state changed.';

-- ----------------------------------------------------------- categories ---

CREATE TABLE categories (
    id         uuid PRIMARY KEY DEFAULT uuidv7(),
    name       text NOT NULL,
    spec       jsonb NOT NULL,
    superseded_by uuid REFERENCES categories (id),
    created_at timestamptz NOT NULL DEFAULT now()
);
-- A bad or evolved spec is corrected by appending a new row with the same
-- (live) name and pointing the old row at it — categories stay append-only,
-- and only the live name is unique (L4 decision: supersession, not wontfix).
CREATE UNIQUE INDEX categories_live_name_key ON categories (name) WHERE superseded_by IS NULL;
CREATE UNIQUE INDEX categories_single_supersession ON categories (superseded_by) WHERE superseded_by IS NOT NULL;
CREATE INDEX categories_spec_gin ON categories USING gin (spec);

CREATE TRIGGER categories_supersede_update
    BEFORE UPDATE ON categories
    FOR EACH ROW EXECUTE FUNCTION supersede_only();
CREATE TRIGGER categories_reject_delete
    BEFORE DELETE ON categories
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER categories_reject_truncate
    BEFORE TRUNCATE ON categories
    FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();

COMMENT ON TABLE  categories            IS 'Named specs (dynamic categories) as DATA, not DDL: adding a category is an insert whose spec is a jsonb attribute predicate matched against line attributes (BRIEF §3 acceptance 7, §4 "categories are projections over line attributes"). A wrong spec is corrected by appending a replacement row (same name, live-unique) and superseding the old one via superseded_by — the old row stays as history, consumers read live rows only. Serves Q1 (the "spec S" side of cheapest-N).';
COMMENT ON COLUMN categories.id         IS 'Serves Q1: identity of the named spec.';
COMMENT ON COLUMN categories.name       IS 'Serves Q1: the category name consumers query by (e.g. 32GB DDR4 RDIMM); unique among LIVE rows only, so corrections can reuse the name.';
COMMENT ON COLUMN categories.spec       IS 'Serves Q1: jsonb attribute predicate (containment) that a line must satisfy to be in the category.';
COMMENT ON COLUMN categories.superseded_by IS 'Serves Q1, Q4: set once on the replaced row, pointing at its later replacement (supersede_only update); a superseded category is history, not a live spec.';
COMMENT ON COLUMN categories.created_at IS 'Serves Q4: when the category was added.';

COMMIT;
