"""Telegram delivery — one sendMessage to the channel, Telegram fans out.

Fail-loud: any non-200, ok=false, or malformed body raises TelegramSendError
(no retry, no fallback — pipeline-error-handling rule).
"""

from __future__ import annotations

import logging

import httpx

from scripts.intraday_monitor.senders.base import AlertPayload, DeliveryResult

logger = logging.getLogger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT_SECONDS = 15.0


class TelegramSendError(Exception):
    """Raised when Telegram rejects or fails to deliver the message."""


class TelegramSender:
    channel = "telegram"

    def __init__(
        self,
        *,
        token: str,
        chat_id: str,
        transport: httpx.BaseTransport | None = None,
    ):
        self._token = token
        self._chat_id = chat_id
        self._transport = transport

    def send(self, payload: AlertPayload) -> DeliveryResult:
        with httpx.Client(
            timeout=_TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            response = client.post(
                _API_URL.format(token=self._token),
                json={
                    "chat_id": self._chat_id,
                    "text": payload.text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramSendError(
                f"Telegram returned non-JSON body (HTTP {response.status_code})"
            ) from exc

        if response.status_code != 200 or not body.get("ok"):
            description = body.get("description", "no description")
            raise TelegramSendError(
                f"Telegram sendMessage failed (HTTP {response.status_code}): "
                f"{description}"
            )

        message_id = body.get("result", {}).get("message_id")
        logger.info("Telegram alert delivered (message_id=%s)", message_id)
        return DeliveryResult(
            channel=self.channel,
            status="sent",
            provider_message_id=str(message_id) if message_id is not None else None,
        )
