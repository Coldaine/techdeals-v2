-- Indexes for the posting-first schema
CREATE INDEX IF NOT EXISTS idx_raw_captures_source ON raw_captures(source);
CREATE INDEX IF NOT EXISTS idx_raw_captures_checksum ON raw_captures(checksum);
CREATE INDEX IF NOT EXISTS idx_postings_capture ON postings(capture_id);
CREATE INDEX IF NOT EXISTS idx_postings_source ON postings(source);
CREATE INDEX IF NOT EXISTS idx_postings_status ON postings(status);
CREATE INDEX IF NOT EXISTS idx_lines_posting ON lines(posting_id);
CREATE INDEX IF NOT EXISTS idx_lines_parent ON lines(parent_line_id);
CREATE INDEX IF NOT EXISTS idx_lines_category ON lines(category);
CREATE INDEX IF NOT EXISTS idx_sale_groups_posting ON sale_groups(posting_id);
CREATE INDEX IF NOT EXISTS idx_observations_posting ON observations(posting_id);
CREATE INDEX IF NOT EXISTS idx_observations_line ON observations(line_id);
CREATE INDEX IF NOT EXISTS idx_observations_offer_key ON observations(offer_key);
CREATE INDEX IF NOT EXISTS idx_observations_observed_at ON observations(observed_at);
CREATE INDEX IF NOT EXISTS idx_observations_price_kind ON observations(price_kind);
CREATE INDEX IF NOT EXISTS idx_resolutions_line ON resolutions(line_id);

-- Make observations a TimescaleDB hypertable for time-series queries
-- This will silently succeed if TimescaleDB is not available (plain table fallback)
DO $$
BEGIN
    PERFORM create_hypertable('observations', by_range('observed_at'), if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    -- TimescaleDB not available; observations is a plain table
    NULL;
END $$;