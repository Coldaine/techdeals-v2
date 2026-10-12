# 0001: Phase 0 Research Decisions

**Status:** accepted  
**Date:** 2026-10-12  
**Scope:** TechDeals v2 — core technical choices from Phase 0 research

---

## 1. LLM Extraction Framework

**Decision: Instructor (Python)**

- `Iterable[T]` for many-items-per-call; `BatchProcessor` for provider-native batch APIs (~50% discount)
- Works with any OpenAI-compatible endpoint (OpenRouter, LiteLLM, Kilo gateway)
- Pydantic validation + auto-retry handles cheap model quirks
- 3M+ downloads/month, actively maintained (Aug 2026)
- DELM (U Chicago, wraps Instructor with checkpointing/cost-tracking) worth monitoring — too young today (11 stars)

**Alternatives considered:** PydanticAI (no native batch), Outlines (local-only), LMQL (abandoned), Guidance (dormant), SGLang (self-hosted only), LangChain (overkill)

---

## 2. Batching Strategy

**Decision: Two-layer batching**

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| Prompt-level | `List[Item]` / `Iterable[T]` Pydantic models | Many listings per LLM call (target: dozens) |
| Provider-level | OpenRouter Batch API (Sep 2026, 50% off, 70+ models, 24h window) | Cost optimization for non-urgent re-extraction |

The brief's hard requirement is Layer 1 ("DONT FRICKING DO ONE AT A TIME"). Layer 2 is pure cost optimization.

---

## 3. Time-Series Storage

**Decision: TimescaleDB hypertables on Neon (Apache-2 features)**

- Neon supports TimescaleDB Apache-2 license: hypertables, `time_bucket()`, `first()`/`last()`, `drop_chunks()`
- **No compression on Neon** (requires TSL license) — acceptable: hardware marketplace data is low-volume (thousands/day, not millions)
- "Cheapest N available right now" = standard SQL with time filter, fast on hypertables
- "Price history over time" = `time_bucket()` aggregation, built-in
- Migration path if compression becomes necessary: Timescale Cloud or self-hosted

**Alternatives considered:** plain partitioning (more manual), pg_partman (available but less ergonomic), pg_mooncake (experimental)

---

## 4. Existing OSS to Reuse (learn from, not import)

| Project | Language | What to borrow |
|---------|----------|----------------|
| **server-price-tracker** | Go | Extraction schemas for hardware components — adapt Pydantic field patterns |
| **webclaw** | Rust | JSON-LD extraction from eBay listings — pre-processing step before LLM |
| **airbitrage** | TypeScript | Reddit `[H]/[W]` title parsing pattern |
| **shopping-deals-mcp-server** | — | Common listing schema across marketplaces |

No existing project does what TechDeals v2 needs: batch LLM parsing of heterogeneous hardware listings into a posting-first schema.

---

## 5. PR #222 Engine Semantics to Carry Forward

From `TechdealsHandoff` repo, `codex/llm-purchase-ingestion` branch:

- **Two-phase LLM interpretation:** (1) extract purchase structure, (2) enrich with hardware attributes
- **Graph model:** Options → Nodes via Memberships (roles: installed, included, optional, compatible, mentioned)
- **Amounts as decimal strings** — avoid float precision loss
- **Never allocate lot prices to components** — explicit anti-hallucination rule
- **Semantic evaluation fixtures** with custom assertion DSL (`$some`, `$any`, `$contains`, `$in`, `$number`)
- **Idempotent processing** with SHA-256 fingerprints; supersession, never deletion

> **CAUTION:** PR #222 is ONE LISTING PER CALL. Its semantics transfer; its calling pattern does NOT. The v2 engine's batched design is genuinely new work.

---

## 6. Explicit "Do Not Use" List

| Item | Reason |
|------|--------|
| LMQL | Abandoned (last release Oct 2023) |
| Guidance | Dormant (quiet since Feb 2026) |
| LangChain | Overkill for extraction-only use case |
| TimescaleDB full features on Neon | Apache-2 only; TSL features unavailable |
| Direct v1 schema migration | Wrong shape — product-first vs posting-first |