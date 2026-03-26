"""Multi-provider LLM client for press review generation."""

import asyncio
import logging
import os
import time
from dataclasses import dataclass

import anthropic
import openai
from google import genai

from scripts.llm_utils import extract_json
from scripts.press_review_agent.config import MODEL_IDS, Provider

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    provider: Provider
    raw_text: str
    parsed: dict[str, str] | None
    usage: dict[str, int]
    success: bool
    error: str | None = None
    latency_ms: int = 0


async def call_claude(system_prompt: str, user_prompt: str) -> LLMResult:
    """Call Anthropic Claude Sonnet 4.5."""
    provider = Provider.CLAUDE
    start = time.monotonic()
    try:
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=MODEL_IDS[provider],
            max_tokens=8192,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        parsed = extract_json(raw)
        latency = int((time.monotonic() - start) * 1000)
        logger.info(
            f"Claude: {usage['input_tokens']}in/{usage['output_tokens']}out, "
            f"{latency}ms"
        )
        return LLMResult(
            provider=provider,
            raw_text=raw,
            parsed=parsed,
            usage=usage,
            success=True,
            latency_ms=latency,
        )
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        logger.error(f"Claude failed: {e}")
        return LLMResult(
            provider=provider,
            raw_text="",
            parsed=None,
            usage={},
            success=False,
            error=str(e),
            latency_ms=latency,
        )


async def call_openai(system_prompt: str, user_prompt: str) -> LLMResult:
    """Call OpenAI o4-mini."""
    provider = Provider.OPENAI
    start = time.monotonic()
    try:
        client = openai.AsyncOpenAI()
        response = await client.chat.completions.create(
            model=MODEL_IDS[provider],
            max_completion_tokens=8192,
            reasoning_effort="medium",
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
            f"OpenAI: {usage['input_tokens']}in/{usage['output_tokens']}out, "
            f"{latency}ms"
        )
        return LLMResult(
            provider=provider,
            raw_text=raw,
            parsed=parsed,
            usage=usage,
            success=True,
            latency_ms=latency,
        )
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        logger.error(f"OpenAI failed: {e}")
        return LLMResult(
            provider=provider,
            raw_text="",
            parsed=None,
            usage={},
            success=False,
            error=str(e),
            latency_ms=latency,
        )


async def call_gemini(system_prompt: str, user_prompt: str) -> LLMResult:
    """Call Google Gemini 2.0 Flash."""
    provider = Provider.GEMINI
    start = time.monotonic()
    try:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=MODEL_IDS[provider],
                contents=user_prompt,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=8192,
                ),
            ),
        )
        raw = response.text
        usage = {
            "input_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
            "output_tokens": getattr(
                response.usage_metadata, "candidates_token_count", 0
            ),
        }
        parsed = extract_json(raw)
        latency = int((time.monotonic() - start) * 1000)
        logger.info(
            f"Gemini: {usage['input_tokens']}in/{usage['output_tokens']}out, "
            f"{latency}ms"
        )
        return LLMResult(
            provider=provider,
            raw_text=raw,
            parsed=parsed,
            usage=usage,
            success=True,
            latency_ms=latency,
        )
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        logger.error(f"Gemini failed: {e}")
        return LLMResult(
            provider=provider,
            raw_text="",
            parsed=None,
            usage={},
            success=False,
            error=str(e),
            latency_ms=latency,
        )


PROVIDER_FUNCTIONS = {
    Provider.CLAUDE: call_claude,
    Provider.OPENAI: call_openai,
    Provider.GEMINI: call_gemini,
}


async def call_providers(
    providers: list[Provider],
    system_prompt: str,
    user_prompt: str,
) -> list[LLMResult]:
    """Call multiple LLM providers in parallel."""
    tasks = [PROVIDER_FUNCTIONS[p](system_prompt, user_prompt) for p in providers]
    results = await asyncio.gather(*tasks)
    return list(results)
