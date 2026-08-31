"""The call shape follows the model family.

Reasoning models reject `temperature` and `top_p` with a 400 and take
`max_completion_tokens`. This client is shared with the brief's narrator, so a
regression here breaks the served narrative, not just the podcast.
"""

from __future__ import annotations

import pytest

from scripts._shared.llm_client import LLMClient, _is_reasoning_model


class _Capture:
    """Stands in for the OpenAI SDK and records the parameters it was given."""

    def __init__(self) -> None:
        self.params: dict = {}
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **params):
        self.params = params

        class _Msg:
            content = '{"ok": true}'

        class _Choice:
            message = _Msg()

        class _Usage:
            prompt_tokens = 1
            completion_tokens = 2

        class _Response:
            choices = [_Choice()]
            usage = _Usage()

        return _Response()


def _call_with(model: str, monkeypatch) -> dict:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = LLMClient(model=model)
    capture = _Capture()
    client._openai = capture  # type: ignore[assignment]
    client.call("prompt", temperature=0.4, max_tokens=1234)
    return capture.params


@pytest.mark.parametrize("model", ["o4-mini", "o3-mini", "o1-preview"])
def test_reasoning_models_get_no_sampling_params(model, monkeypatch):
    params = _call_with(model, monkeypatch)
    assert "temperature" not in params, "o-series rejects temperature with a 400"
    assert "top_p" not in params
    # The value is not the caller's budget: see the reasoning-allowance test.
    assert params["max_completion_tokens"] >= 1234
    assert "max_tokens" not in params


@pytest.mark.parametrize("model", ["gpt-4.1", "gpt-4-turbo"])
def test_chat_models_keep_the_sampling_params(model, monkeypatch):
    params = _call_with(model, monkeypatch)
    assert params["temperature"] == 0.4
    assert params["max_tokens"] == 1234
    assert params["top_p"] == 1
    assert "max_completion_tokens" not in params


@pytest.mark.parametrize(
    "model,expected",
    [("o4-mini", True), ("o1", True), ("gpt-4.1", False), ("gpt-5-turbo", False)],
)
def test_family_detection(model, expected):
    assert _is_reasoning_model(model) is expected


def test_reasoning_budget_covers_thinking_plus_answer(monkeypatch):
    """The caller's output budget is not the whole budget on an o-series model.

    Passing 3 000 straight through returned an empty message on o4-mini: the
    reasoning consumed it before a single output token was emitted.
    """
    params = _call_with("o4-mini", monkeypatch)
    assert params["max_completion_tokens"] >= 16000
