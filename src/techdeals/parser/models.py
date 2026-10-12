from __future__ import annotations

import hashlib
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# --- Enums ---

class PriceKind(str, Enum):
    ASK = "ask"
    BID = "bid"
    SOLD = "sold"
    COST_BASIS = "cost_basis"
    REFERENCE = "reference"


class PriceBasis(str, Enum):
    EXPLICIT_UNIT = "explicit_unit"
    HOMOGENEOUS_DIVISION = "homogeneous_division"
    BOUND_ONLY = "bound_only"
    ALLOCATED = "allocated"


class ListingFormat(str, Enum):
    FIXED = "fixed"
    AUCTION = "auction"
    LOT = "lot"
    BUNDLE = "bundle"
    UNKNOWN = "unknown"


# --- Core extraction models ---

class ExtractedLine(BaseModel):
    """A single decomposed item from a posting."""
    line_number: int = Field(..., description="Ordinal position within the posting")
    label: str = Field(..., description="Human-readable: '2x 32GB DDR4 RDIMM'")
    category: Optional[str] = Field(
        None, description="Dynamic: ram, ssd, hdd, server, cpu, gpu, etc."
    )
    quantity: int = Field(default=1, ge=1)
    separately_purchasable: bool = Field(default=True)
    raw_text: Optional[str] = Field(None, description="Source text this line was extracted from")

    # Hardware attributes (populated by enrichment phase)
    manufacturer: Optional[str] = None
    model_code: Optional[str] = None
    capacity_gb: Optional[int] = None
    speed_mhz: Optional[int] = None
    interface: Optional[str] = None  # SATA, NVMe, DDR4, etc.
    form_factor: Optional[str] = None  # 2.5", 3.5", M.2, etc.


class ExtractedSaleGroup(BaseModel):
    """A group of lines that can be purchased together."""
    label: Optional[str] = Field(None, description="'Full server', 'RAM kit', etc.")
    price_basis: PriceBasis
    total_price_cents: Optional[int] = Field(None, description="Price in cents (integer)")
    total_currency: str = Field(default="USD")
    quantity_in_group: int = Field(default=1, ge=1)
    line_numbers: list[int] = Field(..., description="Which line_numbers are in this group")
    notes: Optional[str] = None


class ExtractedObservation(BaseModel):
    """A price/availability observation from the listing."""
    line_number: Optional[int] = Field(None, description="NULL = posting-level observation")
    sale_group_label: Optional[str] = None
    price_cents: Optional[int] = Field(None, description="Price in cents (integer)")
    price_kind: PriceKind
    available: Optional[bool] = None
    observed_at: Optional[str] = None  # ISO-8601, may come from source


class ExtractionResult(BaseModel):
    """The complete LLM extraction output for one posting."""
    title: Optional[str] = None
    description: Optional[str] = None
    seller: Optional[str] = None
    location: Optional[str] = None
    currency: str = Field(default="USD")
    listing_format: ListingFormat = Field(default=ListingFormat.UNKNOWN)

    lines: list[ExtractedLine] = Field(default_factory=list)
    sale_groups: list[ExtractedSaleGroup] = Field(default_factory=list)
    observations: list[ExtractedObservation] = Field(default_factory=list)

    # Extraction metadata
    parse_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: str = ""
    quarantine_reason: Optional[str] = None  # If not None, this posting is quarantined

    @field_validator("lines")
    @classmethod
    def validate_line_numbers(cls, v: list[ExtractedLine]) -> list[ExtractedLine]:
        """Ensure line numbers are sequential starting from 1."""
        for i, line in enumerate(v, 1):
            if line.line_number != i:
                raise ValueError(
                    f"Line numbers must be sequential: expected {i}, got {line.line_number}"
                )
        return v


class RawListingForExtraction(BaseModel):
    """A single listing prepared for LLM extraction."""
    capture_id: str
    source: str
    url: str
    title: Optional[str] = None
    raw_text: str  # The text to extract from (may be HTML stripped to text, or raw text)
    payload_format: str  # html, json, xml, atom


class BatchExtractionRequest(BaseModel):
    """A batch of listings to extract in one LLM call."""
    batch_id: str = Field(..., description="Unique batch identifier")
    listings: list[RawListingForExtraction] = Field(..., min_length=1, max_length=50)


class BatchExtractionResponse(BaseModel):
    """The LLM's response to a batch extraction request."""
    batch_id: str
    results: list[ExtractionResult]
    model: str  # Which LLM model was used
    prompt_version: str  # Version of the extraction prompt
    tokens_used: Optional[int] = None
    cost_cents: Optional[int] = None  # Cost in cents


# --- Offer key generation ---

def compute_offer_key(
    source: str,
    source_listing_id: str,
    line_number: int,
    sale_group_label: Optional[str] = None,
) -> str:
    """Compute a replay-stable offer key using SHA-256.

    The offer key is stable across parser replays: the same input always
    produces the same key, so re-ingesting the same capture with a new
    parser version creates a new extraction version, never duplicate postings.
    """
    parts = [source, source_listing_id, str(line_number)]
    if sale_group_label:
        parts.append(sale_group_label)
    natural_key = "|".join(parts)
    return hashlib.sha256(natural_key.encode()).hexdigest()
