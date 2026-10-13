-- Batch economics (BRIEF 3.6 / 4): every LLM batch records model + prompt version + cost.
-- One row per LLM call. This is the audit trail that makes "batched, cheap parsing"
-- verifiable instead of aspirational.

CREATE TABLE IF NOT EXISTS extraction_batches (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    batch_key           TEXT,               -- engine-side batch id (e.g. batch_1728...)
    model               TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    listing_count       INT NOT NULL CHECK (listing_count > 0),
    tokens_used         BIGINT,
    cost_cents          BIGINT,
    status              TEXT NOT NULL DEFAULT 'succeeded'
                            CHECK (status IN ('running', 'succeeded', 'failed')),
    error               TEXT,
    provider            TEXT,               -- 'openrouter' | 'kilo' | 'litellm' | 'offline'
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_extraction_batches_started
    ON extraction_batches (started_at DESC);

-- Sanity: the brief's hard rule is "batched, never one at a time" (issuing a call per
-- listing is a defect). Surface any batch that carried a single listing so the
-- guardrail is queryable rather than merely stated.
CREATE OR REPLACE VIEW v_batch_economics AS
SELECT
    COUNT(*)                            AS batch_count,
    SUM(listing_count)                  AS listings_processed,
    ROUND(AVG(listing_count), 2)        AS avg_listings_per_call,
    MIN(listing_count)                  AS min_listings_per_call,
    SUM(tokens_used)                    AS total_tokens,
    SUM(cost_cents)                     AS total_cost_cents,
    COUNT(*) FILTER (WHERE listing_count = 1) AS single_listing_calls
FROM extraction_batches
WHERE status = 'succeeded';
