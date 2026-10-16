from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine import extract


@pytest.mark.parametrize(
    "result",
    [
        {"id": "1"},
        {"id": "1", "outcome": None},
        {"id": "1", "outcome": "unknown"},
    ],
)
def test_validate_result_requires_a_valid_explicit_outcome(result: dict) -> None:
    with pytest.raises(ValueError, match="missing required outcome|bad outcome"):
        extract.validate_result(result)


def test_run_batch_call_marks_purchase_without_outcome_as_failed(tmp_path: Path) -> None:
    class FakeClient:
        model = extract.DEFAULT_MODEL

        def call(self, *args: object) -> tuple[list[dict], dict]:
            return [
                {
                    "id": "missing-outcome",
                    "sale_groups": [{
                        "label": "Server",
                        "availability": "available",
                        "price": {"amount": "100", "price_basis": "explicit_unit"},
                        "lines": [{"label": "CPU", "quantity": 1}],
                    }],
                },
                {
                    "id": "valid-empty",
                    "outcome": "no_purchase_information",
                    "sale_groups": [],
                },
            ], {
                "prompt_tokens": 10,
                "completion_tokens": 10,
                "cached_tokens": 0,
                "latency_s": 0.1,
                "truncated": False,
                "salvaged": False,
            }

    batch = [
        {"client_id": "missing-outcome", "condensed": {"title": "Server"}},
        {"client_id": "valid-empty", "condensed": {"title": "Unknown item"}},
    ]
    results, failed, row = extract.run_batch_call(
        FakeClient(), batch, 1000, str(tmp_path / "ledger.jsonl"), 0
    )

    assert "missing-outcome" not in results
    assert failed["missing-outcome"] == "invalid result: missing required outcome"
    assert results["valid-empty"]["outcome"] == "no_purchase_information"
    assert row["status"] == "partial"
    ledger_row = json.loads((tmp_path / "ledger.jsonl").read_text())
    assert ledger_row["failed_ids"] == ["missing-outcome"]
