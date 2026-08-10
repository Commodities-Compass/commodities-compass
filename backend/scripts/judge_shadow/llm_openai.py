"""OpenAI o4-mini adapter for ``judge.llm.JudgeLLM``.

Matches the press-review stack (openai SDK, o4-mini, ``reasoning_effort=medium``,
``response_format={"type":"json_object"}``, temp 0 — see
``scripts/press_review_agent/llm_client.py``). The verdict schema is validated
by ``judge.llm.verdict_from_dict`` (rubric-anchored: <2 evidence quotes forces
NEUTRAL/conf1); grounding + anti-hindsight rules live in the pinned prompt.

R&D suggests promoting to structured outputs (JSON-schema-enforced) later —
that is a drop-in swap on this adapter without touching the rest of judge.
"""

from __future__ import annotations

import json
import logging
import time

import openai
from judge.llm import verdict_from_dict  # type: ignore
from judge.schema import JudgeVerdict  # type: ignore

logger = logging.getLogger(__name__)

# Pinned for auditability. Every judge shadow row logs (prompt_version, model_id)
# so a rerun target is unambiguous. Kept in code (not DB) per R&D's guidance
# "retune config.py, not the prompt".
DEFAULT_MODEL_ID = "o4-mini"


class OpenAIJudgeLLM:
    """Prod path for judge — OpenAI o4-mini, temp 0, JSON object output."""

    def __init__(self, model_id: str = DEFAULT_MODEL_ID) -> None:
        self._model_id = model_id
        self._client = openai.OpenAI()

    def judge(self, rendered: dict[str, str], *, session_date: str) -> JudgeVerdict:
        start = time.monotonic()
        response = self._client.chat.completions.create(
            model=self._model_id,
            max_completion_tokens=2048,
            reasoning_effort="medium",
            response_format={"type": "json_object"},
            messages=[
                {"role": "developer", "content": rendered["system"]},
                {"role": "user", "content": rendered["user"]},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        usage = response.usage
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "judge(%s): %din/%dout, %dms, model=%s",
            session_date,
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
            latency_ms,
            self._model_id,
        )
        data = json.loads(raw)
        return verdict_from_dict(
            data,
            prompt_version=rendered.get("prompt_version", ""),
            model_id=self._model_id,
        )
