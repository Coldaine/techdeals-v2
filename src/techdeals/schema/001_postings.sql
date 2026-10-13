-- Posting is the center. Every captured listing becomes a posting.
-- Lines are the decomposed contents of a posting (a server posting has 8-10 lines).
-- Lines can be nested (parent_line_id) for hierarchical decomposition.

-- Required extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_bytes() for uuidv7

-- Enable TimescaleDB if available (Neon Apache-2)
-- Wrapped in DO block to silently skip if not available
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS timescaledb;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'TimescaleDB not available; continuing without it';
END $$;

-- uuidv7 generation function (RFC 9562).
-- Layout: 48-bit ms timestamp | ver(0111)+rand_a | var(10)+rand_b.
-- Verified against Postgres 18: version nibble is byte 6, variant byte 8.
CREATE OR REPLACE FUNCTION uuidv7() RETURNS uuid AS $$
  WITH r AS (SELECT gen_random_bytes(10) AS b)
  SELECT encode(
    substring(int8send((extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3 FOR 8)
    || (SELECT set_byte(
                 set_byte(b, 0, 112 | (get_byte(b, 0) & 15)),   -- 0x70 version 7
                         2, 128 | (get_byte(b, 2) & 63))        -- 0x80 RFC variant
        FROM r),
    'hex')::uuid;
$$ LANGUAGE SQL VOLATILE;

-- Raw captures — the pipeline's input boundary
CREATE TABLE IF NOT EXISTS raw_captures (
    id              UUID PRIMARY KEY DEFAULT uuidv7(),
    source          TEXT NOT NULL,
    source_listing_id TEXT NOT NULL,
    url             TEXT NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL,
    checksum        TEXT NOT NULL,  -- SHA-256 of raw_payload
    raw_payload     TEXT NOT NULL,
    payload_format  TEXT NOT NULL CHECK (payload_format IN ('html', 'json', 'xml', 'atom')),
    metadata        JSONB DEFAULT '{}',
    UNIQUE (source, source_listing_id, checksum)
);

-- Postings — the canonical representation of a marketplace listing
CREATE TABLE IF NOT EXISTS postings (
    id              UUID PRIMARY KEY DEFAULT uuidv7(),
    capture_id      UUID NOT NULL REFERENCES raw_captures(id),
    source          TEXT NOT NULL,
    source_listing_id TEXT NOT NULL,
    url             TEXT NOT NULL,
    title           TEXT,
    description     TEXT,
    seller          TEXT,
    location        TEXT,
    currency        TEXT NOT NULL DEFAULT 'USD',
    listing_format  TEXT CHECK (listing_format IN ('fixed', 'auction', 'lot', 'bundle', 'unknown')),
    status          TEXT NOT NULL DEFAULT 'raw' CHECK (status IN ('raw', 'extracting', 'extracted', 'failed', 'quarantined')),
    failure_mode    TEXT CHECK (failure_mode IN ('missed_url', 'partial_parse', 'price_ambiguous', 'out_of_scope', 'quarantine', 'parse_failed')),
    failure_details TEXT,
    parser_version  TEXT NOT NULL DEFAULT 'v1',  -- replay: re-extraction with a new parser is a NEW version, never a duplicate posting
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Replay safety (BRIEF 3.8): one posting per (capture, parser version).
CREATE UNIQUE INDEX IF NOT EXISTS ux_postings_capture_parser
    ON postings (capture_id, parser_version);

-- Lines — decomposed contents of a posting
-- A server posting produces 8-10 lines (CPU, RAM, drives, etc.)
-- Lines can nest: a configured server's DIMMs are children of the server line
CREATE TABLE IF NOT EXISTS lines (
    id              UUID PRIMARY KEY DEFAULT uuidv7(),
    posting_id      UUID NOT NULL REFERENCES postings(id) ON DELETE CASCADE,
    parent_line_id  UUID REFERENCES lines(id) ON DELETE CASCADE,
    line_number     INT NOT NULL,  -- ordinal within posting
    label           TEXT NOT NULL,  -- human-readable: "2x 32GB DDR4 RDIMM", "Samsung 990 PRO 4TB"
    category        TEXT,  -- dynamic, data-driven: "ram", "ssd", "hdd", "server", "cpu", etc.
    quantity         INT NOT NULL DEFAULT 1,
    separately_purchasable BOOLEAN NOT NULL DEFAULT true,
    raw_text        TEXT,  -- the source text this line was extracted from
    -- Spec attributes. These do not exist for their own sake: target query 1
    -- ("cheapest N units of spec S available right now") cannot be answered
    -- from a free-text label. Populated by the extractor when stated.
    manufacturer    TEXT,
    model_code      TEXT,
    capacity_gb     INT,
    speed_mhz       INT,
    interface       TEXT,  -- SATA, SAS, NVMe, DDR4, DDR5, SCSI, PCIe...
    form_factor     TEXT,  -- 2.5", 3.5", M.2, U.2, RDIMM, DIMM...
    UNIQUE (posting_id, line_number)
);

-- Spec lookup index: the "cheapest spec S right now" access path.
CREATE INDEX IF NOT EXISTS idx_lines_specs
    ON lines (category, interface, capacity_gb);

-- Sale groups/terms — what can actually be bought together
-- One posting may have multiple sale groups (e.g., "buy the whole server" vs "buy RAM separately")
CREATE TABLE IF NOT EXISTS sale_groups (
    id              UUID PRIMARY KEY DEFAULT uuidv7(),
    posting_id      UUID NOT NULL REFERENCES postings(id) ON DELETE CASCADE,
    label           TEXT,  -- "Full server", "RAM kit", etc.
    price_basis     TEXT NOT NULL CHECK (price_basis IN (
        'explicit_unit',        -- price is per unit, stated by seller
        'homogeneous_division', -- lot total divided evenly (recorded, not guessed)
        'bound_only',           -- only a bound (min/max) is known
        'allocated'             -- allocated from a lot total (with basis recorded)
    )),
    total_price_cents   BIGINT,  -- price in cents to avoid float
    total_currency      TEXT NOT NULL DEFAULT 'USD',
    quantity_in_group   INT NOT NULL DEFAULT 1,
    notes               TEXT,
    UNIQUE (posting_id, label)
);

-- Sale group membership — which lines belong to which sale group
CREATE TABLE IF NOT EXISTS sale_group_lines (
    sale_group_id   UUID NOT NULL REFERENCES sale_groups(id) ON DELETE CASCADE,
    line_id         UUID NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    quantity_in_group INT NOT NULL DEFAULT 1,
    PRIMARY KEY (sale_group_id, line_id)
);

-- Observations — append-only price/availability events
-- This is the time-series heart of the system
-- offer_key = sha256(natural key) for replay stability
-- Corrections via supersession, never UPDATE
CREATE TABLE IF NOT EXISTS observations (
    id              UUID PRIMARY KEY DEFAULT uuidv7(),
    posting_id      UUID NOT NULL REFERENCES postings(id),
    line_id         UUID REFERENCES lines(id),  -- NULL = posting-level observation
    sale_group_id   UUID REFERENCES sale_groups(id),  -- NULL = not tied to a sale group
    offer_key       TEXT NOT NULL,  -- SHA-256 of natural key, replay-stable
    observed_at     TIMESTAMPTZ NOT NULL,
    price_cents     BIGINT,
    price_kind      TEXT NOT NULL CHECK (price_kind IN ('ask', 'bid', 'sold', 'cost_basis', 'reference')),
    available       BOOLEAN,
    source          TEXT NOT NULL,
    superseded_by   UUID REFERENCES observations(id),  -- if corrected, points to new observation
    raw_evidence    JSONB,  -- the raw data that produced this observation
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Resolutions — candidate product matches
-- Confidence-scored, re-runnable, never a write gate
CREATE TABLE IF NOT EXISTS resolutions (
    id              UUID PRIMARY KEY DEFAULT uuidv7(),
    line_id         UUID NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    candidate_product TEXT NOT NULL,  -- the proposed product identity
    confidence      REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    match_method    TEXT NOT NULL,  -- 'llm', 'exact', 'fuzzy', 'manual'
    rationale       TEXT,
    superseded_by   UUID REFERENCES resolutions(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Categories — dynamic, data-driven
-- Adding a category is inserting data, not migrating schema
CREATE TABLE IF NOT EXISTS categories (
    name            TEXT PRIMARY KEY,
    description     TEXT,
    parent_category TEXT REFERENCES categories(name),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed initial categories
INSERT INTO categories (name, description) VALUES
    ('ram', 'Memory modules (DDR4, DDR5, etc.)'),
    ('ssd', 'Solid state drives'),
    ('hdd', 'Hard disk drives'),
    ('server', 'Complete server systems'),
    ('cpu', 'Processors'),
    ('gpu', 'Graphics cards'),
    ('networking', 'Network equipment'),
    ('psu', 'Power supplies'),
    ('enclosure', 'Drive enclosures, NAS'),
    ('other', 'Other hardware'),
    ('consumer', 'Consumer/non-hardware (quarantine)')
ON CONFLICT (name) DO NOTHING;