"""Pydantic models for parsing structured LLM output.

Replaces the fragile regex parsers from the Make.com blueprint with
validated JSON parsing via Pydantic.
"""

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MacroAnalysisOutput(BaseModel):
    """Output of LLM Call #1 — Macro/Weather impact analysis."""

    date: str
    macroeco_bonus: float = Field(ge=-0.10, le=0.10)
    eco: str = Field(max_length=300)


class TradingDecisionOutput(BaseModel):
    """Output of LLM Call #2 — Trading decision and recommendation."""

    decision: Literal["OPEN", "MONITOR", "HEDGE"]
    confiance: int = Field(ge=1, le=5)
    direction: Literal["HAUSSIERE", "BAISSIERE", "NEUTRE"]
    conclusion: str


def parse_macro_output(raw: str) -> MacroAnalysisOutput:
    """Parse Call #1 raw LLM response into MacroAnalysisOutput."""
    data = _extract_json(raw)
    return MacroAnalysisOutput(**data)


def parse_trading_output(raw: str) -> TradingDecisionOutput:
    """Parse Call #2 raw LLM response into TradingDecisionOutput."""
    data = _extract_json(raw)
    # Normalize decision/direction to uppercase
    if "decision" in data:
        data["decision"] = str(data["decision"]).upper().strip()
    if "direction" in data:
        data["direction"] = (
            str(data["direction"])
            .upper()
            .strip()
            .replace("È", "E")  # HAUSSIÈRE → HAUSSIERE
            .replace("É", "E")
        )
    return TradingDecisionOutput(**data)


def _extract_json(raw: str) -> dict:
    """Extract a JSON object from LLM response text.

    Handles markdown fences, surrounding text, and unescaped newlines.
    """
    text = raw.strip()

    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)

    # Find the outermost brace pair
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last <= first:
        raise ValueError(f"No JSON object found in LLM response: {text[:200]}")
    text = text[first : last + 1]

    # Fast path
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fix unescaped newlines inside JSON string values
    fixed = _fix_unescaped_newlines(text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse JSON from LLM response: {exc}\n{text[:500]}"
        ) from exc


def _fix_unescaped_newlines(text: str) -> str:
    """Escape literal newlines and tabs inside JSON string values."""
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
            if ch == "\t":
                result.append("\\t")
                continue
        result.append(ch)

    return "".join(result)
