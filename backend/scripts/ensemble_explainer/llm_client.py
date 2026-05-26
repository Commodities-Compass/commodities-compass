"""OpenAI LLM client for the ensemble explainer. Single call, fail-loud."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import openai

from scripts.ensemble_explainer.config import MAX_TOKENS, MODEL_ID, TEMPERATURE
from scripts.llm_utils import extract_json

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    raw_text: str
    parsed: dict | None
    usage: dict
    success: bool
    error: str | None = None
    latency_ms: int = 0


async def call_openai(system_prompt: str, user_prompt: str) -> LLMResult:
    """Call OpenAI for ensemble commentary. Returns parsed JSON or error."""
    start = time.monotonic()
    try:
        client = openai.AsyncOpenAI()
        response = await client.chat.completions.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""
        usage = {
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": (
                response.usage.completion_tokens if response.usage else 0
            ),
        }
        latency = int((time.monotonic() - start) * 1000)
        logger.info(
            "OpenAI ensemble-explainer: %din/%dout, %dms",
            usage["input_tokens"],
            usage["output_tokens"],
            latency,
        )
        try:
            parsed = extract_json(raw)
        except ValueError as parse_err:
            logger.warning(
                "JSON parse failed — raw response (%d chars): %s",
                len(raw),
                raw[:2000],
            )
            return LLMResult(
                raw_text=raw,
                parsed=None,
                usage=usage,
                success=False,
                error=f"JSON parse failed: {parse_err}",
                latency_ms=latency,
            )
        return LLMResult(
            raw_text=raw,
            parsed=parsed,
            usage=usage,
            success=True,
            latency_ms=latency,
        )
    except Exception as exc:  # noqa: BLE001 (we want to surface any OpenAI error)
        latency = int((time.monotonic() - start) * 1000)
        logger.error("OpenAI call failed: %s", exc)
        return LLMResult(
            raw_text="",
            parsed=None,
            usage={},
            success=False,
            error=str(exc),
            latency_ms=latency,
        )
