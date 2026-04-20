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


def _fix_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] (common LLM JSON error)."""
    return re.sub(r",\s*([}\]])", r"\1", text)


def _fix_unclosed_braces(text: str) -> str:
    """Append missing closing braces if the JSON is truncated.

    Counts unmatched { and } outside of strings and appends the
    difference. Handles nested objects like theme_sentiments.
    """
    depth = 0
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
    if depth > 0:
        text = text.rstrip().rstrip(",") + ("}" * depth)
    return text


def extract_json(raw: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown wrapping.

    Strategy:
    1. Strip markdown fences if present
    2. Extract content between first { and last }
    3. Fix unescaped newlines inside string values
    4. Fix trailing commas and unclosed braces
    5. Parse with json.loads
    """
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace == -1 or last_brace <= first_brace:
        # No closing brace at all — try to fix truncated output
        if first_brace != -1:
            text = _fix_unclosed_braces(text[first_brace:])
        else:
            raise ValueError(f"No JSON object found in LLM response ({len(raw)} chars)")
    else:
        text = text[first_brace : last_brace + 1]

    # Attempt 1: parse as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt 2: fix newlines
    fixed = fix_unescaped_newlines(text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Attempt 3: fix trailing commas + unclosed braces
    fixed = _fix_trailing_commas(fixed)
    fixed = _fix_unclosed_braces(fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Could not parse JSON from LLM response ({len(raw)} chars): {e}"
        ) from e
