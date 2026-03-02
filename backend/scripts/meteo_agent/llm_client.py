"""OpenAI LLM client for meteo analysis."""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import openai

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


def _fix_unescaped_newlines(text: str) -> str:
    """Escape literal newlines/tabs inside JSON string values.

    LLMs often output literal newlines in JSON strings instead of \\n.
    """
    result: list[str] = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == "\\":
            result.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string:
            if ch == "\n":
                result.append("\\n")
                continue
            if ch == "\r":
                result.append("\\r")
                continue
            if ch == "\t":
                result.append("\\t")
                continue
        result.append(ch)
    return "".join(result)


def extract_json(raw: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown wrapping.

    Strategy:
    1. Strip markdown fences if present
    2. Extract content between first { and last }
    3. Fix unescaped newlines inside string values
    4. Parse with json.loads
    """
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace == -1 or last_brace <= first_brace:
        raise ValueError(f"No JSON object found in LLM response ({len(raw)} chars)")
    text = text[first_brace : last_brace + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fixed = _fix_unescaped_newlines(text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Could not parse JSON from LLM response ({len(raw)} chars): {e}"
        ) from e


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
