"""Extract and parse 'À surveiller' items from pl_indicator_daily.conclusion text."""

import re
from datetime import date
from uuid import UUID

from .types import WatchlistItem

# Indicator text → (db_column, db_table)
# Derived from backend/scripts/daily_analysis/db_reader.py _DB_TO_PROMPT_VARS
INDICATOR_MAP: dict[str, tuple[str, str]] = {
    "RSI": ("rsi_14d", "derived_indicators"),
    "CLOSE": ("close", "contract_data"),
    "OI": ("oi", "contract_data"),
    "OPEN INTEREST": ("oi", "contract_data"),
    "VOLUME": ("volume", "contract_data"),
    "MACD": ("macd", "derived_indicators"),
    "R1": ("r1", "derived_indicators"),
    "RESISTANCE": ("r1", "derived_indicators"),
    "RESISTANCE 1": ("r1", "derived_indicators"),
    "S1": ("s1", "derived_indicators"),
    "SUPPORT": ("s1", "derived_indicators"),
    "SUPPORT 1": ("s1", "derived_indicators"),
    "PIVOT": ("pivot", "derived_indicators"),
    "ATR": ("atr_14d", "derived_indicators"),
    "%K": ("stochastic_k_14", "derived_indicators"),
    "STOCHASTIQUE": ("stochastic_k_14", "derived_indicators"),
    "STOCHASTIC": ("stochastic_k_14", "derived_indicators"),
    "BOLLINGER SUP": ("bollinger_upper", "derived_indicators"),
    "BOLLINGER INF": ("bollinger_lower", "derived_indicators"),
    "VOLATILITE": ("implied_volatility", "contract_data"),
    "VOLATILITÉ": ("implied_volatility", "contract_data"),
    "STOCK": ("stock_us", "contract_data"),
    "STOCK EU": ("stock_us", "contract_data"),
    "STOCK US": ("stock_us", "contract_data"),
    "COM NET": ("com_net_us", "contract_data"),
    "EMA9": ("ema12", "derived_indicators"),
    "EMA21": ("ema26", "derived_indicators"),
    "SIGNAL": ("macd_signal", "derived_indicators"),
}

# Keywords implying bearish direction
_BEARISH_KEYWORDS = [
    "baissière",
    "baissiere",
    "repli",
    "pression baissière",
    "survente",
    "déclin",
    "cassure baissière",
    "risque de cassure",
    "tombe",
    "chute",
]

# Keywords implying bullish direction
_BULLISH_KEYWORDS = [
    "haussière",
    "haussiere",
    "rebond",
    "signal haussier",
    "continuation",
    "confirmation.*haussière",
    "dépasse.*résistance",
]

# Keywords implying neutral (monitoring only)
_NEUTRAL_KEYWORDS = [
    "monitorer",
    "surveiller",
    "confirmation de direction",
    "confirmation de tendance",
    "évaluer",
]

# Regex for extracting numbers (handles "6 520", "6,520", "6520", "6520.33")
_NUMBER_RE = r"(\d[\d\s,.]*\d|\d+(?:[.,]\d+)?)"

# Build indicator pattern from keys (sorted longest first to avoid partial matches)
_INDICATOR_NAMES = sorted(INDICATOR_MAP.keys(), key=len, reverse=True)
_INDICATOR_PATTERN = "|".join(re.escape(name) for name in _INDICATOR_NAMES)


def extract_watchlist_section(conclusion: str) -> list[str]:
    """Extract raw bullet lines from the 'À surveiller' section of a conclusion.

    Returns empty list if no section found.
    """
    if not conclusion:
        return []

    # Split on the "a surveiller" / "à surveiller" header (case-insensitive)
    # Handles: "> A SURVEILLER AUJOURD'HUI:", "À SURVEILLER AUJOURD'HUI :", with/without >
    parts = re.split(r"[>]?\s*[AÀ]\s+SURVEILLER[^:]*:", conclusion, flags=re.IGNORECASE)
    if len(parts) < 2:
        return []

    watchlist_text = parts[1]

    # Extract bullet lines (• or - prefixed, with optional leading whitespace/tabs)
    lines = watchlist_text.split("\n")
    items: list[str] = []
    for line in lines:
        cleaned = line.strip()
        # Remove bullet markers (•, -, *, tab-prefixed bullets)
        cleaned = re.sub(r"^[\t\s]*[•\-\*]\s*", "", cleaned)
        cleaned = cleaned.strip()
        if cleaned and len(cleaned) > 5:
            items.append(cleaned)

    return items


def _parse_number(text: str) -> float | None:
    """Parse a number from French-formatted text (handles spaces, commas)."""
    match = re.search(_NUMBER_RE, text)
    if not match:
        return None
    raw = match.group(1)
    # Remove spaces (thousands separator in French)
    raw = raw.replace(" ", "")
    # Handle comma as decimal separator
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    elif "," in raw and "." in raw:
        # Both present: comma is thousands, dot is decimal
        raw = raw.replace(",", "")
    return float(raw)


def _find_indicator(text: str) -> tuple[str, str, str] | None:
    """Find the first known indicator in text.

    Returns (indicator_name, db_column, db_table) or None.
    """
    text_upper = text.upper()
    for name in _INDICATOR_NAMES:
        if name in text_upper:
            col, table = INDICATOR_MAP[name]
            return name, col, table
    return None


def _infer_direction(text: str) -> str:
    """Infer implied market direction from French context words."""
    text_lower = text.lower()

    # Check bearish first (more specific patterns)
    for keyword in _BEARISH_KEYWORDS:
        if re.search(keyword, text_lower):
            return "BAISSIERE"

    # Check bullish
    for keyword in _BULLISH_KEYWORDS:
        if re.search(keyword, text_lower):
            return "HAUSSIERE"

    # Check neutral
    for keyword in _NEUTRAL_KEYWORDS:
        if re.search(keyword, text_lower):
            return "NEUTRE"

    return "NEUTRE"


def _infer_comparator(text: str, direction: str) -> str:
    """Infer the comparator (BELOW, ABOVE, NEAR, CROSS_*) from text."""
    text_lower = text.lower()

    # Explicit "sous", "en dessous", "au-dessous", "tombe sous"
    if re.search(
        r"(sous|en dessous|au-dessous|tombe sous|passe sous|inférieur)", text_lower
    ):
        return "BELOW"

    # Explicit "au-dessus", "dépasse", "franchit", "au dessus"
    if re.search(
        r"(au-dessus|au dessus|dépasse|franchit|supérieur|passe au-dessus)", text_lower
    ):
        return "ABOVE"

    # "Cassure" patterns
    if re.search(r"cassure", text_lower):
        if direction == "HAUSSIERE":
            return "CROSS_ABOVE"
        return "CROSS_BELOW"

    # "Monitorer", "surveiller" → NEAR
    if re.search(r"(monitorer|surveiller|autour|proche|niveau)", text_lower):
        return "NEAR"

    # Default based on direction
    if direction == "HAUSSIERE":
        return "ABOVE"
    if direction == "BAISSIERE":
        return "BELOW"
    return "NEAR"


def _extract_threshold_near_indicator(text: str, indicator_name: str) -> float | None:
    """Extract the numeric threshold from the text.

    Strategy: prefer the number after "à" or "de" (e.g., "résistance à 2438"),
    then fall back to the last large number in the text (> 10 likely = price level).
    """
    # Strategy 1: look for "à NUMBER" pattern (most common: "résistance à 2438", "support à 5800")
    a_match = re.search(r"(?:à|a)\s+" + _NUMBER_RE, text)
    if a_match:
        val = _parse_number(a_match.group(0))
        if val is not None:
            return val

    # Strategy 2: look for "de NUMBER" at end of phrase
    de_match = re.search(r"de\s+" + _NUMBER_RE, text)
    if de_match:
        val = _parse_number(de_match.group(0))
        if val is not None and val > 10:  # Skip small numbers like "de 50" for RSI
            return val
        # Still return for small thresholds (RSI, %K)
        if val is not None:
            return val

    # Strategy 3: find all numbers and pick the most likely threshold
    # (largest number if multiple, or single number)
    all_numbers = re.findall(_NUMBER_RE, text)
    if not all_numbers:
        return None

    parsed = []
    for raw in all_numbers:
        clean = raw.replace(" ", "").replace(",", ".")
        try:
            parsed.append(float(clean))
        except ValueError:
            continue

    if not parsed:
        return None

    # If indicator is a price-level indicator, prefer the largest number
    price_indicators = {
        "CLOSE",
        "R1",
        "S1",
        "SUPPORT",
        "SUPPORT 1",
        "RESISTANCE",
        "RESISTANCE 1",
        "PIVOT",
        "BOLLINGER SUP",
        "BOLLINGER INF",
    }
    if indicator_name in price_indicators and len(parsed) > 1:
        # Return the largest number (likely price, not "1" from "résistance 1")
        return max(parsed)

    # Otherwise return the last number found
    return parsed[-1]


def parse_item(
    raw_text: str,
    item_date: date,
    contract_id: UUID,
) -> WatchlistItem | None:
    """Parse a raw watchlist text line into a structured WatchlistItem.

    Returns None only if the text is completely unparseable (no indicator found).
    """
    # Find the indicator
    indicator_info = _find_indicator(raw_text)
    if not indicator_info:
        return None

    indicator_name, db_column, db_table = indicator_info

    # Infer direction from context
    implied_direction = _infer_direction(raw_text)

    # Infer comparator
    comparator = _infer_comparator(raw_text, implied_direction)

    # Extract threshold
    threshold = _extract_threshold_near_indicator(raw_text, indicator_name)

    # Determine parse confidence
    if threshold is not None and implied_direction != "NEUTRE":
        confidence = "HIGH"
    elif threshold is not None:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return WatchlistItem(
        date=item_date,
        contract_id=contract_id,
        raw_text=raw_text,
        indicator=indicator_name,
        db_column=db_column,
        db_table=db_table,
        comparator=comparator,
        threshold=threshold,
        implied_direction=implied_direction,
        parse_confidence=confidence,
    )
