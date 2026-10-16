from __future__ import annotations

import json

import pytest
from engine import extract


def test_default_model_is_an_allowlisted_zero_cost_model() -> None:
    assert extract.DEFAULT_MODEL in extract.MODEL_PRICES
    assert extract.MODEL_PRICES[extract.DEFAULT_MODEL] == (0.0, 0.0)
    assert all(rates == (0.0, 0.0) for rates in extract.MODEL_PRICES.values())


@pytest.mark.parametrize(
    "model",
    [
        "deepseek/deepseek-v4-flash-0731",
        "deepseek/deepseek-v4-flash",
        "openai/gpt-oss-120b",
        "some-provider/unknown-model:free",
    ],
)
def test_unlisted_models_are_rejected_before_any_api_client_or_call(
    model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_client(*args: object, **kwargs: object) -> None:
        pytest.fail("rejected model must not create an API client")

    def unexpected_urlopen(*args: object, **kwargs: object) -> None:
        pytest.fail("rejected model must not make an API request")

    monkeypatch.setattr(extract, "BatchClient", unexpected_client)
    monkeypatch.setattr(extract.urllib.request, "urlopen", unexpected_urlopen)

    with pytest.raises(SystemExit) as exc:
        extract.main(["--files", "/does/not/exist.json", "--model", model])

    assert exc.value.code == 2


def test_default_model_request_uses_prompt_schema_and_local_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    malformed_result = {
        "id": "capture-1",
        "outcome": "extracted",
        "sale_groups": [],
    }
    envelope = {
        "choices": [{"message": {"content": json.dumps({"results": [malformed_result]})}}],
    }

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps(envelope).encode()

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(extract.urllib.request, "urlopen", fake_urlopen)
    results, _meta = extract.BatchClient(extract.DEFAULT_MODEL, "test-key").call(
        extract.SYSTEM_PROMPT,
        {"listings": [{"id": "capture-1"}]},
        extract.OUTPUT_SCHEMA,
        100,
    )

    body = captured["body"]
    assert "response_format" not in body
    assert captured["timeout"] == 300.0
    system_message = body["messages"][0]["content"]
    assert json.dumps(extract.OUTPUT_SCHEMA, ensure_ascii=False, indent=2) in system_message
    assert results == [malformed_result]
    with pytest.raises(ValueError, match="extracted without sale groups"):
        extract.validate_result(results[0])
