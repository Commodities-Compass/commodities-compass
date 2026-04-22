"""Shared LLM response utilities for all agents.

Provides JSON extraction from LLM responses with handling for common
issues: markdown fences, unescaped newlines/tabs, unescaped quotes,
and invalid escape sequences inside JSON strings.
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


def _fix_invalid_escapes(text: str) -> str:
    r"""Replace invalid JSON escape sequences produced by LLMs.

    JSON only allows: \" \\ \/ \b \f \n \r \t \uXXXX.
    LLMs sometimes emit Python-style escapes like \' or \x41.
    """
    # \' → ' (Python-ism)
    text = text.replace("\\'", "'")
    # \xNN → \\xNN (not valid JSON escape — neutralize the backslash)
    text = re.sub(r"\\x([0-9a-fA-F]{2})", r"\\\\x\1", text)
    # \a, \v, \0 — not valid JSON escapes
    text = re.sub(r"\\([av0])", r"\1", text)
    return text


def _fix_unescaped_quotes(text: str) -> str:
    """Escape double quotes inside JSON string values.

    Detects unescaped " inside strings using structural context:
    a quote that isn't followed by a JSON structural char (,:{}[])
    or whitespace is likely an embedded quote, not a string terminator.
    """
    # JSON structural chars that legitimately follow a closing quote
    _STRUCT_AFTER_QUOTE = set(",}]: \n\r\t")

    result: list[str] = []
    in_string = False
    escape_next = False
    i = 0
    while i < len(text):
        ch = text[i]
        if escape_next:
            result.append(ch)
            escape_next = False
            i += 1
            continue
        if ch == "\\":
            result.append(ch)
            escape_next = True
            i += 1
            continue
        if ch == '"':
            if not in_string:
                # Opening quote — always emit as-is
                in_string = True
                result.append(ch)
            else:
                # We're inside a string and hit a quote.
                # Peek at next non-space char to decide: is this the
                # real closing quote, or an embedded quote?
                j = i + 1
                while j < len(text) and text[j] in " \t":
                    j += 1
                next_ch = text[j] if j < len(text) else ""
                if next_ch in _STRUCT_AFTER_QUOTE or next_ch == "" or j >= len(text):
                    # Looks like a real closing quote
                    in_string = False
                    result.append(ch)
                else:
                    # Embedded quote — escape it
                    result.append('\\"')
            i += 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def extract_json(raw: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown wrapping.

    Strategy (4-attempt cascade):
    1. Strip markdown fences, extract between first { and last }
    2. Parse as-is
    3. Fix unescaped newlines inside string values
    4. Fix trailing commas + unclosed braces
    5. Fix invalid escapes + unescaped quotes (heaviest repair)
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
    except json.JSONDecodeError:
        pass

    # Attempt 4: fix invalid escapes + unescaped quotes (heaviest repair)
    fixed = _fix_invalid_escapes(fixed)
    fixed = _fix_unescaped_quotes(fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Could not parse JSON from LLM response ({len(raw)} chars): {e}"
        ) from e
