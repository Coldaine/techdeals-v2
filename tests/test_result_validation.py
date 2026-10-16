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


def test_malformed_nonempty_sale_group_is_rejected() -> None:
    malformed = {"id": "bad", "outcome": "extracted", "sale_groups": [{}]}

    with pytest.raises(ValueError, match="sale group missing required fields"):
        extract.validate_result(malformed)


@pytest.mark.parametrize(
    ("field", "value"),
    [("label", 7), ("lines", {}), ("price", []), ("availability", [])],
)
def test_sale_group_fields_must_have_contract_types(field: str, value: object) -> None:
    group = {"label": None, "lines": [], "price": None, "availability": "unknown"}
    group[field] = value

    with pytest.raises(ValueError, match="sale group|price"):
        extract.validate_result({"id": "bad", "outcome": "quarantined", "sale_groups": [group]})


def test_extracted_result_requires_a_valid_line_in_each_sale_group() -> None:
    no_lines = {
        "id": "empty",
        "outcome": "extracted",
        "sale_groups": [{"label": None, "lines": [], "price": None, "availability": "unknown"}],
    }

    with pytest.raises(ValueError, match="no line or other purchase information"):
        extract.validate_result(no_lines)


def test_price_only_purchase_group_is_preserved_without_inventing_a_line() -> None:
    price = {
        "amount": "100.00", "currency": "USD", "price_kind": "ask",
        "price_basis": "explicit_unit", "quantity_units": 1,
        "bound_low": None, "bound_high": None, "basis_note": None,
    }
    result = extract.validate_result({
        "id": "price-only", "outcome": "extracted", "sale_groups": [{
            "label": None, "availability": "available", "price": price, "lines": [],
        }],
    })

    assert result["sale_groups"][0]["price"] == price
    assert result["sale_groups"][0]["lines"] == []


def test_nullable_price_provenance_stays_unknown_in_validated_result() -> None:
    price = {
        "amount": "100.00", "currency": None, "price_kind": None,
        "price_basis": "explicit_unit", "quantity_units": 1,
        "bound_low": None, "bound_high": None, "basis_note": None,
    }
    result = extract.validate_result({
        "id": "unknown-price-context", "outcome": "extracted", "sale_groups": [{
            "label": "Machine", "availability": "available", "price": price,
            "lines": [],
        }],
    })
    assert result["sale_groups"][0]["price"]["currency"] is None
    assert result["sale_groups"][0]["price"]["price_kind"] is None


def test_price_contract_rejects_wrong_types_missing_fields_and_unknown_kind() -> None:
    good = {
        "amount": "100.00", "currency": "USD", "price_kind": "ask",
        "price_basis": "explicit_unit", "quantity_units": 1,
        "bound_low": None, "bound_high": None, "basis_note": None,
    }
    base = {"id": "price", "outcome": "extracted", "sale_groups": [{
        "label": "Machine", "availability": "available", "price": good,
        "lines": [{"label": "Machine", "quantity": 1,
                   "separately_purchasable": True, "attributes": {}, "children": []}],
    }]}

    for field, value, message in (
        ("amount", 100, "price amount must be a string or null"),
        ("amount", "NaN", "amount must be a decimal string or null"),
        ("quantity_units", True, "quantity_units must be a positive number or null"),
        ("price_kind", "unknown", "bad price_kind"),
    ):
        bad = json.loads(json.dumps(base))
        bad["sale_groups"][0]["price"][field] = value
        with pytest.raises(ValueError, match=message):
            extract.validate_result(bad)

    bad = json.loads(json.dumps(base))
    del bad["sale_groups"][0]["price"]["currency"]
    with pytest.raises(ValueError, match="price missing required fields: currency"):
        extract.validate_result(bad)


@pytest.mark.parametrize("quantity", [float("nan"), float("inf"), float("-inf"), json.loads("1e999")])
def test_price_contract_rejects_nonfinite_quantity_units(quantity: float) -> None:
    result = {
        "id": "nonfinite", "outcome": "extracted", "sale_groups": [{
            "label": "Machine", "availability": "available",
            "price": {
                "amount": "100", "currency": "USD", "price_kind": "ask",
                "price_basis": "explicit_unit", "quantity_units": quantity,
                "bound_low": None, "bound_high": None, "basis_note": None,
            },
            "lines": [{"label": "Machine", "quantity": 1,
                       "separately_purchasable": True, "attributes": {}, "children": []}],
        }],
    }
    with pytest.raises(ValueError, match="quantity_units must be a positive number or null"):
        extract.validate_result(result)


@pytest.mark.parametrize(
    ("currency", "price_kind", "reason"),
    [(None, "ask", "currency unstated"), ("USD", None, "price kind unstated")],
)
def test_price_writer_does_not_default_unknown_currency_or_kind(
    currency: str | None, price_kind: str | None, reason: str
) -> None:
    group = {"price": {
        "amount": "100.00", "currency": currency, "price_kind": price_kind,
        "price_basis": "explicit_unit", "quantity_units": 1,
        "bound_low": None, "bound_high": None, "basis_note": None,
    }}
    observation, error = extract.price_observation(
        {"offer_key": "a" * 64, "posting_id": "posting", "fetched_at": "2026-10-15T00:00:00+00:00"},
        "g0", group,
    )
    assert observation is None
    assert error is not None and reason in error


def test_malformed_child_is_rejected_instead_of_silently_dropped() -> None:
    malformed_child = {
        "id": "child",
        "outcome": "extracted",
        "sale_groups": [{
            "label": "Server",
            "availability": "available",
            "price": None,
            "lines": [{
                "label": "System",
                "quantity": 1,
                "separately_purchasable": True,
                "attributes": {},
                "children": [{}],
            }],
        }],
    }

    with pytest.raises(ValueError, match="child 0 missing required fields"):
        extract.validate_result(malformed_child)


def test_child_fields_must_have_contract_types() -> None:
    malformed_child = {
        "id": "child",
        "outcome": "extracted",
        "sale_groups": [{
            "label": "Server",
            "availability": "available",
            "price": None,
            "lines": [{
                "label": "System",
                "quantity": 1,
                "separately_purchasable": True,
                "attributes": {},
                "children": [{
                    "label": "CPU",
                    "quantity": True,
                    "separately_purchasable": False,
                    "attributes": {},
                }],
            }],
        }],
    }

    with pytest.raises(ValueError, match="child 0 quantity must be a number or null"):
        extract.validate_result(malformed_child)


def test_quarantined_result_may_have_no_sale_groups() -> None:
    result = extract.validate_result({
        "id": "quarantine",
        "outcome": "quarantined",
        "sale_groups": [],
    })

    assert result["outcome"] == "quarantined"
    assert result["sale_groups"] == []
