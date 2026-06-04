"""Tests for the daily seasonal-score refresh wired into the meteo agent.

Covers the isolation contract: `_refresh_seasonal_scores` recomputes the
campaign scores via `bootstrap_campaign`, but a failure (e.g. Open-Meteo
archive outage) must NOT propagate — it is logged loud to Sentry and
swallowed so the caller still writes the daily weather observation.
"""

from datetime import date
from unittest.mock import patch

from scripts.meteo_agent.main import _refresh_seasonal_scores

TARGET = date(2026, 6, 3)


def test_refresh_success_calls_bootstrap_with_session_and_target():
    """Happy path: bootstrap_campaign runs against the opened session + date."""
    with (
        patch("scripts.db.get_session") as get_session,
        patch(
            "scripts.meteo_agent.seasonal_memory.bootstrap_campaign"
        ) as bootstrap_campaign,
        patch("scripts.meteo_agent.main.sentry_sdk.capture_message") as capture,
    ):
        session = get_session.return_value.__enter__.return_value

        _refresh_seasonal_scores(TARGET)

        bootstrap_campaign.assert_called_once_with(session, TARGET)
        capture.assert_not_called()


def test_refresh_failure_is_isolated_and_reported():
    """A refresh failure is swallowed (no raise) and reported to Sentry once."""
    with (
        patch("scripts.db.get_session"),
        patch(
            "scripts.meteo_agent.seasonal_memory.bootstrap_campaign",
            side_effect=RuntimeError("archive down"),
        ),
        patch("scripts.meteo_agent.main.sentry_sdk.capture_message") as capture,
    ):
        # Must not raise — the daily weather observation must still proceed.
        _refresh_seasonal_scores(TARGET)

        capture.assert_called_once()
        assert capture.call_args.kwargs.get("level") == "error"
        assert "archive down" in capture.call_args.args[0]
