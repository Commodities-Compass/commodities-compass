"""Telegram sender tests — payload shape, message_id parsing, fail-loud."""

import json

import httpx
import pytest

from scripts.intraday_monitor.senders.base import AlertPayload
from scripts.intraday_monitor.senders.console import ConsoleSender
from scripts.intraday_monitor.senders.telegram import (
    TelegramSender,
    TelegramSendError,
)

TOKEN = "12345:TEST-TOKEN"
CHAT_ID = "-1001234567890"


def _payload() -> AlertPayload:
    return AlertPayload(
        text="<b>CAU26</b> test alert",
        rule_key="close_below_s1",
        variables={"contract": "CAU26"},
    )


def _sender_with(handler) -> TelegramSender:
    transport = httpx.MockTransport(handler)
    return TelegramSender(token=TOKEN, chat_id=CHAT_ID, transport=transport)


class TestTelegramSender:
    def test_send_posts_correct_payload_and_parses_message_id(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200, json={"ok": True, "result": {"message_id": 4242}}
            )

        result = _sender_with(handler).send(_payload())

        assert captured["path"] == f"/bot{TOKEN}/sendMessage"
        assert captured["body"]["chat_id"] == CHAT_ID
        assert captured["body"]["parse_mode"] == "HTML"
        assert "CAU26" in captured["body"]["text"]
        assert result.status == "sent"
        assert result.provider_message_id == "4242"
        assert result.channel == "telegram"

    def test_http_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403, json={"ok": False, "description": "bot was kicked"}
            )

        with pytest.raises(TelegramSendError, match="bot was kicked"):
            _sender_with(handler).send(_payload())

    def test_ok_false_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": False})

        with pytest.raises(TelegramSendError):
            _sender_with(handler).send(_payload())

    def test_non_json_body_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>gateway error</html>")

        with pytest.raises(TelegramSendError):
            _sender_with(handler).send(_payload())


class TestConsoleSender:
    def test_send_returns_sent_without_provider_id(self, caplog):
        with caplog.at_level("INFO"):
            result = ConsoleSender().send(_payload())
        assert result.status == "sent"
        assert result.provider_message_id is None
        assert result.channel == "console"
        assert any("CAU26" in r.message for r in caplog.records)
