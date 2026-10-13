"""The batching contract: many listings per LLM call, never one at a time."""
from __future__ import annotations

import pytest

from techdeals.parser import engine
from techdeals.parser.models import ExtractionResult, RawListingForExtraction


def _listing(i: int) -> RawListingForExtraction:
    return RawListingForExtraction(
        capture_id=str(i),
        source="test",
        url=f"https://example.com/{i}",
        raw_text=f"listing {i}",
        payload_format="json",
    )


@pytest.mark.asyncio
async def test_extract_batches_batches_many_listings_per_call(monkeypatch) -> None:
    calls: list[int] = []

    async def fake_extract_batch(listings, **kwargs):
        from techdeals.parser.engine import BatchListingsResponse

        calls.append(len(listings))
        return BatchListingsResponse(
            results=[ExtractionResult(title=f"l{i}") for i, _ in enumerate(listings, 1)]
        )

    monkeypatch.setattr(engine, "extract_batch", fake_extract_batch)

    responses = await engine.extract_batches(
        [_listing(i) for i in range(45)], batch_size=20, model="test-model"
    )

    # 45 listings / batch_size 20 -> 3 calls of 20, 20, 5. Never 45 calls of 1.
    assert calls == [20, 20, 5]
    assert len(responses) == 3


@pytest.mark.asyncio
async def test_batch_size_never_yields_one_listing_per_call(monkeypatch) -> None:
    calls: list[int] = []

    async def fake_extract_batch(listings, **kwargs):
        from techdeals.parser.engine import BatchListingsResponse

        calls.append(len(listings))
        return BatchListingsResponse(results=[ExtractionResult() for _ in listings])

    monkeypatch.setattr(engine, "extract_batch", fake_extract_batch)
    await engine.extract_batches([_listing(i) for i in range(60)], batch_size=15)
    assert calls == [15, 15, 15, 15]
    assert all(n > 1 for n in calls)
