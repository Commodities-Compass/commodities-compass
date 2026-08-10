"""The one non-reproducible seam, quarantined behind an interface.

`JudgeLLM` turns a rendered prompt into a :class:`JudgeVerdict`. Two impls:

- :class:`GoldenJudgeLLM` — replays recorded verdicts by session date. Used by
  tests and offline replay; fully deterministic.
- :class:`AnthropicJudgeLLM` — the prod path: pinned model, temperature 0,
  structured output. Imported lazily so the package works without the SDK.

Everything around this seam (parsing, drift, policy, scoring, logging) is
deterministic and unit-tested. Only the judgment itself varies — by design.
"""

from __future__ import annotations

import json
from typing import Protocol

from . import config
from .schema import Direction, JudgeVerdict, Stance


class JudgeLLM(Protocol):
    def judge(self, rendered: dict[str, str], *, session_date: str) -> JudgeVerdict: ...


def verdict_from_dict(
    data: dict, *, prompt_version: str = "", model_id: str = ""
) -> JudgeVerdict:
    """Validate + coerce a raw judge dict into a :class:`JudgeVerdict`."""
    conf = int(data["confidence"])
    if not 1 <= conf <= 5:
        raise ValueError(f"confidence out of range: {conf}")
    evidence = tuple(str(e) for e in data.get("evidence", []))
    direction = Direction(data["suggested_direction"])
    stance = Stance(data["stance"])

    # Grounding guard: fewer than two cited facts -> forced NEUTRAL/conf1.
    if len(evidence) < 2:
        direction, stance, conf = Direction.NONE, Stance.NEUTRAL, 1

    return JudgeVerdict(
        suggested_direction=direction,
        confidence=conf,
        stance=stance,
        is_anomaly=bool(data.get("is_anomaly", False)),
        evidence=evidence,
        drift_summary=str(data.get("drift_summary", "")),
        disconfirming_case=str(data.get("disconfirming_case", "")),
        key_risk=str(data.get("key_risk", "")),
        prompt_version=prompt_version,
        model_id=model_id,
    )


class GoldenJudgeLLM:
    """Replay verdicts recorded in a {session_date: verdict_dict} map."""

    def __init__(self, golden: dict[str, dict]):
        self._golden = golden

    def judge(self, rendered: dict[str, str], *, session_date: str) -> JudgeVerdict:
        if session_date not in self._golden:
            raise KeyError(f"no golden verdict for session {session_date}")
        return verdict_from_dict(
            self._golden[session_date],
            prompt_version=rendered.get("prompt_version", ""),
            model_id="golden",
        )

    @classmethod
    def from_file(cls, path: str) -> "GoldenJudgeLLM":
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))


class AnthropicJudgeLLM:
    """Prod path. Pinned model, temp 0, JSON output. Lazy SDK import."""

    def __init__(self, model_id: str = config.JUDGE_MODEL_ID):
        self._model_id = model_id

    def judge(self, rendered: dict[str, str], *, session_date: str) -> JudgeVerdict:
        # PROD: swap the provider here to match the press-review stack if desired
        # (o4-mini via the OpenAI SDK). For stronger guarantees, enforce the
        # schema from judge.prompt.verdict_json_schema() via tool/structured
        # output instead of parsing free-form JSON. Keep temperature at 0 and the
        # model id pinned (config.JUDGE_MODEL_ID) so every call is auditable.
        import anthropic  # lazy: only needed on the live path

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=self._model_id,
            max_tokens=1024,
            temperature=config.JUDGE_TEMPERATURE,
            system=rendered["system"],
            messages=[{"role": "user", "content": rendered["user"]}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        data = json.loads(text)
        return verdict_from_dict(
            data,
            prompt_version=rendered.get("prompt_version", ""),
            model_id=self._model_id,
        )
