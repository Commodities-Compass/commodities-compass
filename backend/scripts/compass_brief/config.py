"""Configuration for the Compass Brief generator.

Reads market data from Google Sheets and uploads a structured text brief
to Google Drive, replacing the manual Looker Studio PDF export.
"""

import os

SPREADSHEET_ID = "16VXIrG9ybjjaorTeiR8sh5nrPIj9I7EFGr2iBSAjSSA"

# Source sheets (always production)
SOURCE_TECHNICALS = "TECHNICALS"
SOURCE_INDICATOR = "INDICATOR"
SOURCE_BIBLIO_ALL = "BIBLIO_ALL"
SOURCE_METEO_ALL = "METEO_ALL"

# Google API scopes
SCOPES_SHEETS = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SCOPES_DRIVE = ["https://www.googleapis.com/auth/drive"]

# TECHNICALS column mapping (0-based index -> label)
# Range A:AR covers all needed columns including DECISION/SCORE in AO-AR.
TECHNICALS_COLS: dict[int, str] = {
    1: "CLOSE",
    2: "HIGH",
    3: "LOW",
    4: "VOLUME",
    5: "OI",
    6: "IV",
    7: "STOCK US",
    8: "COM NET US",
    11: "R1",
    12: "PIVOT",
    13: "S1",
    16: "EMA9",
    17: "EMA21",
    18: "MACD",
    19: "SIGNAL",
    20: "RSI 14D",
    30: "%K",
    31: "%D",
    35: "ATR",
    37: "BANDE SUP",
    38: "BANDE INF",
    40: "DECISION",
    41: "CONFIANCE",
    42: "DIRECTION",
    43: "SCORE",
}

# INDICATOR column mapping (0-based index -> label)
# Range A:T covers all scores, normalised values, and conclusion.
INDICATOR_COLS: dict[int, str] = {
    1: "RSI SCORE",
    2: "MACD SCORE",
    3: "STOCHASTIC SCORE",
    4: "ATR SCORE",
    5: "CLOSE/PIVOT",
    6: "VOLUME/OI",
    7: "RSI NORM",
    8: "MACD NORM",
    9: "STOCH %K NORM",
    10: "ATR NORM",
    11: "CLOSE/PIVOT NORM",
    12: "VOL/OI NORM",
    13: "INDICATOR",
    14: "MOMENTUM",
    15: "MACROECO BONUS",
    16: "FINAL INDICATOR",
    17: "CONCLUSION",
    18: "MACROECO SCORE",
    19: "ECO",
}

# Environment variable names
CREDENTIALS_ENV_VAR = "GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON"
DRIVE_BRIEFS_FOLDER_ENV_VAR = "GOOGLE_DRIVE_BRIEFS_FOLDER_ID"


def get_credentials_json() -> str:
    value = os.environ.get(CREDENTIALS_ENV_VAR, "")
    if not value:
        raise RuntimeError(f"Missing environment variable: {CREDENTIALS_ENV_VAR}")
    return value


def get_drive_briefs_folder_id() -> str:
    value = os.environ.get(DRIVE_BRIEFS_FOLDER_ENV_VAR, "")
    if not value:
        raise RuntimeError(
            f"Missing environment variable: {DRIVE_BRIEFS_FOLDER_ENV_VAR}\n"
            "Create a 'Compass Briefs' folder in Google Drive, share it with "
            "the service account as Editor, then set the folder ID in .env."
        )
    return value
