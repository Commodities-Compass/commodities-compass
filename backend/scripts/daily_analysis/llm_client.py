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
    """Raised on LLM call failures after retries."""


@dataclass
class LLMResponse:
    """Raw response from an LLM call."""

    raw_text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class LLMClient:
    """Synchronous LLM client with retry logic."""

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
        max_retries: int = 2,
    ) -> LLMResponse:
        """Call the LLM with the given prompt. Retries once on failure.

        Args:
            prompt: Full prompt text (system + user combined as assistant role,
                    matching the Make.com blueprint behaviour).
            temperature: Sampling temperature.
            max_tokens: Max response tokens.
            max_retries: Total attempts (1 = no retry).

        Returns:
            LLMResponse with raw text and usage stats.
        """
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                return self._call_openai(
                    prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    attempt=attempt,
                )
            except (OpenAIError, Exception) as exc:
                last_error = exc
                logger.warning(
                    "LLM call attempt %d/%d failed: %s",
                    attempt,
                    max_retries,
                    exc,
                )
                if attempt < max_retries:
                    time.sleep(2**attempt)

        raise LLMClientError(
            f"LLM call failed after {max_retries} attempts: {last_error}"
        ) from last_error

    def _call_openai(
        self,
        prompt: str,
        *,
        temperature: float,
        max_tokens: int,
        attempt: int,
    ) -> LLMResponse:
        """Execute a single OpenAI API call."""
        start = time.monotonic()

        # Make.com blueprint uses role=assistant for the prompt (Module 19 & 6).
        # We replicate this exactly for output parity.
        response = self._openai.chat.completions.create(
            model=self.model,
            messages=[{"role": "assistant", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=1,
        )

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
            "LLM call #%d OK: model=%s tokens=%d+%d latency=%dms",
            attempt,
            self.model,
            result.input_tokens,
            result.output_tokens,
            result.latency_ms,
        )
        return result
