"""Console delivery — logs the rendered message (dev / dry-run / tests)."""

from __future__ import annotations

import logging

from scripts.intraday_monitor.senders.base import AlertPayload, DeliveryResult

logger = logging.getLogger(__name__)


class ConsoleSender:
    channel = "console"

    def send(self, payload: AlertPayload) -> DeliveryResult:
        logger.info("[CONSOLE ALERT] rule=%s\n%s", payload.rule_key, payload.text)
        return DeliveryResult(channel=self.channel, status="sent")
