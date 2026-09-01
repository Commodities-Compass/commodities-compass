"""LLM client for the daily analysis pipeline.

Wraps OpenAI (default) with configurable provider support.
Uses synchronous calls since the pipeline is sequential.
"""

import logging
import os
import time
from dataclasses import dataclass

from openai import OpenAI, OpenAIError

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-4-turbo"


class LLMClientError(Exception):
    """Raised on LLM call failure."""


@dataclass
class LLMResponse:
    """Raw response from an LLM call."""

    raw_text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


# o1 / o3 / o4 families. Matched on the prefix so a new point release does not
# need a code change.
_REASONING_PREFIXES = ("o1", "o3", "o4", "o5")
# The answer has to fit alongside the reasoning in one budget.
_REASONING_ALLOWANCE = 4
_REASONING_MIN_TOKENS = 16000


def _is_reasoning_model(model: str) -> bool:
    """True for OpenAI reasoning models, which take a different parameter set."""
    head = model.split("-", 1)[0].lower()
    return head in _REASONING_PREFIXES


class LLMClient:
    """Synchronous LLM client. Fails fast — no retries."""

    def __init__(
        self,
        provider: str = DEFAULT_PROVIDER,
        model: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model or DEFAULT_MODEL

        if provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                raise LLMClientError("Missing OPENAI_API_KEY environment variable")
            self._openai = OpenAI(api_key=api_key)
        else:
            raise LLMClientError(f"Unsupported LLM provider: {provider}")

        logger.info("LLMClient initialised: provider=%s model=%s", provider, self.model)

    def call(
        self,
        prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Call the LLM with the given prompt. Fails immediately on error — no retries.

        Args:
            prompt: Full prompt text (system + user combined as assistant role,
                    matching the Make.com blueprint behaviour).
            temperature: Sampling temperature.
            max_tokens: Max response tokens.

        Returns:
            LLMResponse with raw text and usage stats.
        """
        try:
            return self._call_openai(
                prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except (OpenAIError, Exception) as exc:
            raise LLMClientError(f"LLM call failed: {exc}") from exc

    def _call_openai(
        self,
        prompt: str,
        *,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Execute a single OpenAI API call."""
        start = time.monotonic()

        # Reasoning models reject `temperature` and `top_p` outright and take
        # `max_completion_tokens` rather than `max_tokens`. Sending the sampling
        # params to one is a 400, not a silently ignored field, so the shape of
        # the call has to follow the model family.
        params: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if _is_reasoning_model(self.model):
            # On reasoning models the budget covers the hidden reasoning tokens
            # as well as the answer, so passing the caller's output budget
            # straight through spends it all on thinking and returns an empty
            # message — observed as "0 chars" with 3 000 on o4-mini.
            params["max_completion_tokens"] = max(
                max_tokens * _REASONING_ALLOWANCE, _REASONING_MIN_TOKENS
            )
        else:
            params["temperature"] = temperature
            params["max_tokens"] = max_tokens
            params["top_p"] = 1

        response = self._openai.chat.completions.create(**params)  # type: ignore[arg-type]

        elapsed_ms = int((time.monotonic() - start) * 1000)
        raw_text = response.choices[0].message.content or ""
        usage = response.usage

        result = LLMResponse(
            raw_text=raw_text,
            model=self.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=elapsed_ms,
        )

        logger.info(
            "LLM call OK: model=%s tokens=%d+%d latency=%dms",
            self.model,
            result.input_tokens,
            result.output_tokens,
            result.latency_ms,
        )
        return result
