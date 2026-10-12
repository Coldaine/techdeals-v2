from __future__ import annotations

import pytest

from techdeals.parser.models import (
    ExtractedLine,
    ExtractedSaleGroup,
    ExtractionResult,
    ListingFormat,
    PriceBasis,
    compute_offer_key,
)


def test_extracted_line_model() -> None:
    line = ExtractedLine(
        line_number=1,
        label="2x 32GB DDR4 RDIMM",
        category="ram",
        quantity=2,
    )
    assert line.line_number == 1
    assert line.quantity == 2
    assert line.separately_purchasable is True


def test_extracted_listing_model() -> None:
    result = ExtractionResult(
        title="Test Server",
        listing_format=ListingFormat.FIXED,
        lines=[
            ExtractedLine(line_number=1, label="CPU", category="cpu"),
            ExtractedLine(line_number=2, label="RAM", category="ram"),
        ],
        sale_groups=[
            ExtractedSaleGroup(
                price_basis=PriceBasis.EXPLICIT_UNIT,
                total_price_cents=150000,
                line_numbers=[1, 2],
            ),
        ],
    )
    assert result.title == "Test Server"
    assert len(result.lines) == 2
    assert result.sale_groups[0].price_basis == PriceBasis.EXPLICIT_UNIT


def test_offer_key_deterministic() -> None:
    k1 = compute_offer_key("ebay", "12345", 1, "Full server")
    k2 = compute_offer_key("ebay", "12345", 1, "Full server")
    assert k1 == k2
    assert len(k1) == 64  # SHA-256 hex digest


def test_offer_key_varies_by_input() -> None:
    k1 = compute_offer_key("ebay", "12345", 1)
    k2 = compute_offer_key("ebay", "12345", 2)
    assert k1 != k2


@pytest.mark.asyncio
async def test_extract_batch_empty_input(monkeypatch: pytest.MonkeyPatch) -> None:
    from techdeals.parser.engine import extract_batch

    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://localhost/test")
    response = await extract_batch([])
    assert response.results == []
    assert response.model  # model is populated
