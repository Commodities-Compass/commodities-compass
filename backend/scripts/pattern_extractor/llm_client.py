"""OpenAI o4-mini client for pattern extraction."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import openai

from scripts.llm_utils import extract_json
from scripts.pattern_extractor.config import (
    MAX_COMPLETION_TOKENS,
    MODEL_ID,
    REASONING_EFFORT,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMResult:
    raw_text: str
    parsed: dict | None
    usage: dict[str, int]
    success: bool
    error: str | None = None
    latency_ms: int = 0


async def call_openai(system_prompt: str, user_prompt: str) -> LLMResult:
    """Call OpenAI o4-mini for extraction. No retry — fail loud."""
    start = time.monotonic()
    try:
        client = openai.AsyncOpenAI()
        response = await client.chat.completions.create(
            model=MODEL_ID,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
            reasoning_effort=REASONING_EFFORT,
            messages=[
                {"role": "developer", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content or ""
        usage = {
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": (
                response.usage.completion_tokens if response.usage else 0
            ),
        }
        parsed = extract_json(raw)
        latency = int((time.monotonic() - start) * 1000)
        logger.info(
            "OpenAI: %din/%dout, %dms",
            usage["input_tokens"],
            usage["output_tokens"],
            latency,
        )
        return LLMResult(
            raw_text=raw,
            parsed=parsed,
            usage=usage,
            success=True,
            latency_ms=latency,
        )
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        logger.error("OpenAI failed: %s", e)
        return LLMResult(
            raw_text="",
            parsed=None,
            usage={},
            success=False,
            error=str(e),
            latency_ms=latency,
        )
