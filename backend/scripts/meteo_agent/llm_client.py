"""OpenAI LLM client for meteo analysis."""

import logging
import time
from dataclasses import dataclass

import openai

from scripts.llm_utils import extract_json
from scripts.meteo_agent.config import MAX_TOKENS, MODEL_ID

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    raw_text: str
    parsed: dict[str, str] | None
    usage: dict[str, int]
    success: bool
    error: str | None = None
    latency_ms: int = 0


async def call_openai(system_prompt: str, user_prompt: str) -> LLMResult:
    """Call OpenAI GPT-4.1 for meteo analysis."""
    start = time.monotonic()
    try:
        client = openai.AsyncOpenAI()
        response = await client.chat.completions.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            temperature=0.5,
            messages=[
                {"role": "system", "content": system_prompt},
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
        logger.error("OpenAI call failed: %s", e)
        return LLMResult(
            raw_text="",
            parsed=None,
            usage={},
            success=False,
            error=str(e),
            latency_ms=latency,
        )
