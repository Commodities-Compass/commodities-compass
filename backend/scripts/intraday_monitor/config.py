"""Configuration for the intraday threshold monitor."""

from __future__ import annotations

import os
from datetime import time
from zoneinfo import ZoneInfo

# Logging
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# ICE London Cocoa session window (Europe/London wall clock, DST via zoneinfo).
# Official ICE Futures Europe hours (product 37089076): 09:30-16:55 London.
# Decision #7: constants for MVP; ref_exchange.session_open/close = P2.
LONDON_TZ = ZoneInfo("Europe/London")
LONDON_SESSION_OPEN = time(9, 30)
LONDON_SESSION_CLOSE = time(16, 55)

# Observation source label written to pl_contract_data_intraday.source.
SOURCE_LABEL = "barchart-delayed"

# Sanity range for the delayed price (GBP/tonne) — mirrors the daily
# barchart scraper's VALIDATION_RANGES["close"].
PRICE_RANGE = (1500.0, 20000.0)

# Barchart endpoints (same host as the daily scraper).
BARCHART_OVERVIEW_URL = "https://www.barchart.com/futures/quotes/{contract}/overview"
BARCHART_QUOTES_API_URL = "https://www.barchart.com/proxies/core-api/v1/quotes/get"
HTTP_TIMEOUT_SECONDS = 30.0

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Ensemble-preferred decision lookup (message context only).
ENSEMBLE_VERSION_NAME = "ensemble_v1_softgate_wrapper"


def get_alert_channel() -> str:
    """Delivery channel: 'console' (default, dev/dry-run) or 'telegram' (prod)."""
    return os.getenv("ALERT_CHANNEL", "console").strip().lower()


def get_telegram_bot_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set — required when ALERT_CHANNEL=telegram"
        )
    return token


def get_telegram_chat_id() -> str:
    chat_id = os.getenv("TELEGRAM_CHANNEL_ID", "")
    if not chat_id:
        raise RuntimeError(
            "TELEGRAM_CHANNEL_ID is not set — required when ALERT_CHANNEL=telegram"
        )
    return chat_id
