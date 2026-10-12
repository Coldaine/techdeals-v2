# TechDeals v2 — Domain Glossary

Canonical terms for the TechDeals v2 domain. Implementation details belong in code, not here.

## Core Entities

**Posting** — A marketplace listing at a point in time. One URL, one source, one capture. The center of the schema.

**Line** — A decomposed item within a posting. A server posting with 8 DIMMs produces 9 lines (1 server + 8 DIMMs). Lines can nest (`parent_line_id`).

**Sale Group** — A set of lines that can be purchased together. One posting may have multiple sale groups (e.g., "whole server" vs "RAM only").

**Observation** — An append-only price/availability event. Never mutated; corrections via supersession. The time-series heart of the system.

**Resolution** — A candidate product match for a line. Confidence-scored, re-runnable, never a write gate.

**Category** — A dynamic classification of lines. Adding a category is inserting data, not migrating schema.

## Identity

**Offer Key** — A replay-stable SHA-256 hash of the natural key (source, listing ID, line number, sale group). Same input always produces the same key. Re-ingesting with a new parser version creates a new extraction version, never duplicates.

**Capture Checksum** — SHA-256 of the raw payload. Used to detect duplicate captures.

## Pricing

**Price Kind** — What a price represents: `ask` (seller's asking price), `bid` (buyer's offer), `sold` (confirmed transaction), `cost_basis` (internal purchase), `reference` (third-party estimate).

**Price Basis** — How a price was determined: `explicit_unit` (seller stated per-unit), `homogeneous_division` (lot divided evenly), `bound_only` (only a bound known), `allocated` (allocated from lot total with recorded basis).

**Fabricated Price** — A unit price derived by dividing a lot total across components without recording the division. This is a defect, never acceptable.

## Pipeline States

**Raw** — A captured listing that has not been processed.

**Extracted** — A posting whose lines, sale groups, and observations have been populated by the LLM engine.

**Quarantined** — A posting that cannot be processed (out-of-scope, wanted-post, parse failure). Visible in counts, never silently dropped.

**Superseded** — An observation or resolution that has been replaced by a newer version. The original is preserved; the pointer `superseded_by` chains to the replacement.

## Source Types

**Capture** — The raw page payload (HTML/JSON/XML) plus source URL and fetch timestamp. The pipeline's only input boundary.

**Fixture** — A real captured listing used for testing the pipeline. Not synthetic data.

## Analysis

**Decomposition** — Breaking a multi-item posting into individual lines with honest pricing.

**Time Series** — Price and availability history for a posting or line, queryable via `time_bucket()`.