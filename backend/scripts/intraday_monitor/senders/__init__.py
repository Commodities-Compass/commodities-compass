"""Sender factory — resolves the delivery channel from config."""

from __future__ import annotations

from scripts.intraday_monitor.config import (
    get_alert_channel,
    get_telegram_bot_token,
    get_telegram_chat_id,
)
from scripts.intraday_monitor.senders.base import (
    AlertPayload,
    AlertSender,
    DeliveryResult,
)
from scripts.intraday_monitor.senders.console import ConsoleSender
from scripts.intraday_monitor.senders.telegram import TelegramSender

__all__ = [
    "AlertPayload",
    "AlertSender",
    "DeliveryResult",
    "ConsoleSender",
    "TelegramSender",
    "build_sender",
]


def build_sender() -> AlertSender:
    """Build the sender for ALERT_CHANNEL ('console' default, 'telegram' prod)."""
    channel = get_alert_channel()
    if channel == "telegram":
        return TelegramSender(
            token=get_telegram_bot_token(), chat_id=get_telegram_chat_id()
        )
    if channel == "console":
        return ConsoleSender()
    raise RuntimeError(f"Unknown ALERT_CHANNEL: {channel!r}")
