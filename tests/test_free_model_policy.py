from __future__ import annotations

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
