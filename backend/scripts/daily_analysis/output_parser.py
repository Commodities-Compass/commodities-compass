"""Pydantic models for parsing structured LLM output.

Replaces the fragile regex parsers from the Make.com blueprint with
validated JSON parsing via Pydantic.
"""

import logging
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

    Delegates to the shared llm_utils.extract_json which handles markdown
    fences, unescaped newlines/tabs/quotes, trailing commas, and truncated output.
    """
    from scripts.llm_utils import extract_json

    return extract_json(raw)
