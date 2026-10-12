"""Batched LLM extraction engine using Instructor.

Key design constraints from the brief:
- NEVER one listing per call. Batching is a requirement, not an optimization.
- Works with any OpenAI-compatible endpoint (OpenRouter, Kilo gateway, LiteLLM).
- Records model + prompt version + cost per batch.
- Pydantic validation + auto-retry handles cheap model quirks.
"""
from __future__ import annotations

import asyncio
import logging
import time

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from techdeals.config import get_settings
from techdeals.parser.models import (
    BatchExtractionResponse,
    ExtractionResult,
    RawListingForExtraction,
)
from techdeals.parser.prompts import EXTRACTION_SYSTEM_PROMPT, build_batch_user_prompt

logger = logging.getLogger(__name__)


class BatchListingsResponse(BaseModel):
    """The LLM's structured response for a batch of listings."""

    results: list[ExtractionResult] = Field(
        ..., description="Extraction results, one per listing in the batch"
    )


async def extract_batch(
    listings: list[RawListingForExtraction],
    *,
    model: str | None = None,
    prompt_version: str = "v1",
    max_retries: int = 3,
) -> BatchExtractionResponse:
    """Run batched LLM extraction on a list of raw listings.

    This is the core of the extraction engine. It:
    1. Builds a prompt containing ALL listings in the batch
    2. Calls the LLM once with Instructor for structured output
    3. Returns ExtractionResults for each listing

    Args:
        listings: The listings to extract from (1-50 per batch)
        model: Override the default LLM model
        prompt_version: Version of the extraction prompt (for tracking)
        max_retries: Max retries on validation failure

    Returns:
        BatchExtractionResponse with results for each listing
    """
    settings = get_settings()
    model = model or settings.llm_model
    batch_id = f"batch_{int(time.time() * 1000)}"

    if not listings:
        return BatchExtractionResponse(
            batch_id=batch_id,
            results=[],
            model=model,
            prompt_version=prompt_version,
        )

    if len(listings) > 50:
        raise ValueError(f"Batch size {len(listings)} exceeds maximum of 50")

    system_prompt = EXTRACTION_SYSTEM_PROMPT
    user_prompt = build_batch_user_prompt(listings)

    logger.info(
        "Extracting batch of %d listings with model=%s prompt_version=%s",
        len(listings),
        model,
        prompt_version,
    )

    client = instructor.from_openai(
        AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
        ),
        mode=instructor.Mode.JSON,
    )

    start_time = time.monotonic()

    try:
        response = await client.chat.completions.create(
            model=model,
            response_model=BatchListingsResponse,
            max_retries=max_retries,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )

        elapsed = time.monotonic() - start_time
        logger.info(
            "Batch %s completed in %.1fs: %d results",
            batch_id,
            elapsed,
            len(response.results),
        )

        results = list(response.results)
        while len(results) < len(listings):
            results.append(
                ExtractionResult(
                    notes=f"No extraction returned for listing {len(results) + 1}",
                    parse_confidence=0.0,
                )
            )

        return BatchExtractionResponse(
            batch_id=batch_id,
            results=results[: len(listings)],
            model=model,
            prompt_version=prompt_version,
        )

    except Exception:
        elapsed = time.monotonic() - start_time
        logger.exception("Batch %s failed after %.1fs", batch_id, elapsed)

        return BatchExtractionResponse(
            batch_id=batch_id,
            results=[
                ExtractionResult(
                    notes="Extraction failed due to LLM error",
                    parse_confidence=0.0,
                    quarantine_reason="parse_failed",
                )
                for _ in listings
            ],
            model=model,
            prompt_version=prompt_version,
        )


async def extract_batches(
    listings: list[RawListingForExtraction],
    *,
    batch_size: int | None = None,
    model: str | None = None,
    prompt_version: str = "v1",
    max_concurrent: int = 5,
) -> list[BatchExtractionResponse]:
    """Extract from many listings by splitting into batches.

    This is the high-level entry point. It:
    1. Splits listings into batches of `batch_size`
    2. Runs batches concurrently (up to max_concurrent)
    3. Returns all responses

    Args:
        listings: All listings to process
        batch_size: Listings per batch (default from config)
        model: Override the default LLM model
        prompt_version: Version of the extraction prompt
        max_concurrent: Max concurrent LLM calls

    Returns:
        List of BatchExtractionResponse, one per batch
    """
    settings = get_settings()
    batch_size = batch_size or settings.llm_batch_size

    batches = [listings[i : i + batch_size] for i in range(0, len(listings), batch_size)]

    logger.info(
        "Processing %d listings in %d batches (batch_size=%d, max_concurrent=%d)",
        len(listings),
        len(batches),
        batch_size,
        max_concurrent,
    )

    semaphore = asyncio.Semaphore(max_concurrent)

    async def run_batch(batch: list[RawListingForExtraction]) -> BatchExtractionResponse:
        async with semaphore:
            return await extract_batch(batch, model=model, prompt_version=prompt_version)

    responses = await asyncio.gather(*[run_batch(b) for b in batches])

    total_results = sum(len(r.results) for r in responses)
    logger.info(
        "All batches complete: %d results from %d batches", total_results, len(responses)
    )

    return list(responses)
