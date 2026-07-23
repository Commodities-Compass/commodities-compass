"""Delivery abstraction — the engine never knows the transport.

Swappable: TelegramSender (prod), ConsoleSender (dev/dry-run/tests),
WhatsAppSender addable later without touching the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class AlertPayload:
    """Rendered message + provenance variables (audited in aud_alert_event)."""

    text: str
    rule_key: str
    variables: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryResult:
    channel: str
    status: str  # 'sent' | 'failed'
    provider_message_id: str | None = None


class AlertSender(Protocol):
    channel: str

    def send(self, payload: AlertPayload) -> DeliveryResult: ...
