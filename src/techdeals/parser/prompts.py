"""Prompt templates for the LLM extraction engine.

The prompt must instruct the LLM to:
1. Decompose multi-item postings into individual lines
2. NEVER allocate lot prices to components (anti-hallucination rule)
3. Record price_basis honestly (explicit_unit, bound_only, etc.)
4. Quarantine out-of-scope items rather than force-fitting
5. Handle heterogeneous formats (eBay, Reddit, liquidation, retail)
"""
from __future__ import annotations

from techdeals.parser.models import RawListingForExtraction

EXTRACTION_SYSTEM_PROMPT = """You are a hardware marketplace listing parser. Your job is to extract structured data from hardware marketplace listings.

## Critical Rules

1. **DECOMPOSE multi-item postings**: A server listing with 8-10 components must produce 8-10 separate lines. A Reddit post with "4x 8TB Exos $280 / Samsung 980 Pro 2TB $110" must produce TWO lines.

2. **NEVER allocate lot prices to components**. If a listing says "Server $5000" with 8 DIMMs, the sale group price is $5000 for the WHOLE server. Do NOT divide $5000/8 to get a per-DIMM price. Use `price_basis: "bound_only"` if only a lot total is available.

3. **Record price_basis honestly**:
   - `explicit_unit`: seller states a per-unit price (e.g., "$35 per DIMM")
   - `homogeneous_division`: lot total divided evenly across identical items (e.g., "50 DIMMs for $1000" -> $20 each, but RECORD that this was divided)
   - `bound_only`: only a bound is known (lot total exists, per-unit does not)
   - `allocated`: allocated from a lot total with explicit basis

4. **QUARANTINE out-of-scope items**. Consumer electronics (phones, tablets, game consoles), non-hardware (software, services), and items you cannot parse should set `quarantine_reason` with a brief explanation. Do NOT force-fit them into hardware categories.

5. **Handle [W] / WTB posts** (Reddit "Want to Buy") -- these are NOT listings. They should be quarantined with reason "wanted_post".

6. **Prices are in CENTS (integers)**. $32.50 -> 3250. $1,200.00 -> 120000. If no price is available, leave null.

7. **Categories**: Use these categories when possible: ram, ssd, hdd, server, cpu, gpu, networking, psu, enclosure, other, consumer. If none fit, use "other".

8. **Confidence**: Set `parse_confidence` honestly:
   - 1.0: all fields clearly stated in the listing
   - 0.7-0.9: most fields clear, some inference needed
   - 0.4-0.6: significant ambiguity or missing data
   - 0.0-0.3: mostly guessing or very incomplete data

## What to Extract Per Listing

For each listing in the batch, extract:
- `title`: The listing title
- `description`: Brief description (1-2 sentences)
- `seller`: Seller name if available
- `location`: Location if available
- `currency`: 3-letter currency code (default USD)
- `listing_format`: One of: fixed, auction, lot, bundle, unknown
- `lines`: Each decomposed item (see above)
- `sale_groups`: What can be bought together, with price and basis
- `observations`: Price/availability observations
- `parse_confidence`: Your confidence in the extraction (0.0-1.0)
- `notes`: Any important notes about the extraction
- `quarantine_reason`: If the item should be quarantined, explain why

## Line Attributes (when available)

For each line, try to extract these hardware attributes:
- `manufacturer`: Brand name (Samsung, Intel, HPE, Dell, etc.)
- `model_code`: Specific model number
- `capacity_gb`: Storage or memory capacity in GB
- `speed_mhz`: Clock speed in MHz (for RAM)
- `interface`: Connection type (SATA, NVMe, DDR4, DDR5, PCIe, etc.)
- `form_factor`: Physical size (2.5", 3.5", M.2, DIMM, etc.)"""


def build_batch_user_prompt(listings: list[RawListingForExtraction]) -> str:
    """Build the user prompt containing all listings in the batch.

    Each listing is clearly delimited with its capture_id, source, and raw text.
    The LLM must return results in the same order as the input listings.
    """
    parts = [
        f"Extract structured data from the following {len(listings)} listings.",
        "Return results in the SAME ORDER as the input listings.",
        "Each listing is delimited by --- LISTING N --- markers.",
        "",
    ]

    for i, listing in enumerate(listings, 1):
        parts.append(f"--- LISTING {i} ---")
        parts.append(f"capture_id: {listing.capture_id}")
        parts.append(f"source: {listing.source}")
        parts.append(f"url: {listing.url}")
        if listing.title:
            parts.append(f"title: {listing.title}")
        parts.append(f"format: {listing.payload_format}")
        parts.append("")
        parts.append(listing.raw_text[:8000])
        parts.append("")
        parts.append(f"--- END LISTING {i} ---")
        parts.append("")

    return "\n".join(parts)
