"""Configuration for the daily analysis pipeline.

Environment variables:
    Required:
        GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON  Service account JSON (read+write scope)
        OPENAI_API_KEY                          OpenAI API key (for LLM calls)
    Optional:
        SENTRY_DSN                              Sentry monitoring DSN
        ENVIRONMENT                             Railway environment tag (default: production)
"""

import os

SPREADSHEET_ID = "16VXIrG9ybjjaorTeiR8sh5nrPIj9I7EFGr2iBSAjSSA"

# --- Sheet tab names ---
# Reads are ALWAYS from production. Writes go to the --sheet target.
INDICATOR_SHEETS: dict[str, str] = {
    "production": "INDICATOR",
    "staging": "INDICATOR_STAGING",
}

TECHNICALS_SHEETS: dict[str, str] = {
    "production": "TECHNICALS",
    "staging": "TECHNICALS_STAGING",
}

# Source sheets for reads (always production)
SOURCE_TECHNICALS = "TECHNICALS"
SOURCE_BIBLIO_ALL = "BIBLIO_ALL"
SOURCE_METEO_ALL = "METEO_ALL"

# --- TECHNICALS TOD/YES variable mapping ---
# Column index (0-based from column A) → variable name prefix.
# Each produces a TOD and YES pair (e.g., CLOSETOD / CLOSEYES).
TECHNICALS_VARIABLES: dict[int, str] = {
    1: "CLOSE",  # B
    2: "HIGH",  # C
    3: "LOW",  # D
    4: "VOL",  # E  (VOLUME)
    5: "OI",  # F  (OPEN INTEREST)
    6: "VOLIMP",  # G  (IMPLIED VOLATILITY)
    7: "STOCK",  # H  (STOCK US)
    8: "COMNET",  # I  (COM NET US)
    11: "R1",  # L
    12: "PIVOT",  # M
    13: "S1",  # N
    16: "EMA9",  # Q
    17: "EMA21",  # R
    18: "MACD",  # S
    19: "SIGN",  # T  (SIGNAL)
    20: "RSI14",  # U  (RSI 14D)
    30: "%K",  # AE (Stochastic %K)
    31: "%D",  # AF (Stochastic %D)
    35: "ATR",  # AJ
    37: "BSUP",  # AL (BANDE SUP)
    38: "BBINF",  # AM (BANDE INF)
}

# METEO_ALL: max historical rows to read for METEONEWS context
METEO_HISTORY_LIMIT = 100

# --- INDICATOR sheet formula templates ---
# Inline formulas written when a row is "frozen" (no longer live).
# {row} is replaced with the actual sheet row number.
FREEZE_Q_FORMULA = '=IF(N{row}="", "", N{row} + (O{row}*0.5))'
FREEZE_R_FORMULA = (
    '=IF(Q{row}="", "", IF(Q{row} > 2, "OPEN", IF(Q{row} < -2, "HEDGE", "MONITOR")))'
)

# HISTORIQUE reference formulas for "live" rows.
# {ref} is replaced with the HISTORIQUE sheet row number (e.g., 101 or 102).
HISTORIQUE_Q_FORMULA = "=HISTORIQUE!R{ref}"
HISTORIQUE_R_FORMULA = "=HISTORIQUE!T{ref}"

# Google Sheets API
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDENTIALS_ENV_VAR = "GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON"


def get_credentials_json() -> str:
    value = os.environ.get(CREDENTIALS_ENV_VAR, "")
    if not value:
        raise RuntimeError(f"Missing environment variable: {CREDENTIALS_ENV_VAR}")
    return value


# --- Required env vars per run mode ---
REQUIRED_ENV_VARS: dict[str, str] = {
    "GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON": "Google Sheets service account JSON (read+write)",
}

REQUIRED_ENV_VARS_LLM: dict[str, str] = {
    "OPENAI_API_KEY": "OpenAI API key for LLM calls",
}


def validate_env(*, require_llm: bool = True) -> list[str]:
    """Check all required env vars are set. Returns list of missing var names.

    Args:
        require_llm: If True, also check LLM-specific vars (skip for --inspect mode).
    """
    required = dict(REQUIRED_ENV_VARS)
    if require_llm:
        required.update(REQUIRED_ENV_VARS_LLM)

    missing = [var for var in required if not os.environ.get(var)]
    return missing
