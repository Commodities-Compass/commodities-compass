"""Shared LLM response utilities for all agents.

Provides JSON extraction from LLM responses with handling for common
issues: markdown fences, unescaped newlines/tabs inside JSON strings.
"""

from __future__ import annotations

import json
import re
from typing import Any


def fix_unescaped_newlines(text: str) -> str:
    """Escape literal newlines/tabs inside JSON string values.

    LLMs often output literal newlines in JSON strings instead of \\n.
    This is invalid JSON but common across Claude, GPT, and Gemini.
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

    fixed = fix_unescaped_newlines(text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Could not parse JSON from LLM response ({len(raw)} chars): {e}"
        ) from e
