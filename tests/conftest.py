from __future__ import annotations

import os

import pytest

os.environ.setdefault("NEON_DATABASE_URL", "postgresql://localhost/test")


@pytest.fixture
def sample_listing() -> dict:
    """Return a minimal sample listing for testing."""
    return {
        "source": "ebay",
        "url": "https://example.com/listing/123",
        "title": "NVIDIA RTX 4090 Founders Edition",
        "price": 1599.99,
        "currency": "USD",
        "raw_text": "Brand new NVIDIA RTX 4090 FE, 24GB GDDR6X.",
    }
