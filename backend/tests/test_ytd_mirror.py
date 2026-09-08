"""The YTD figure the podcast says must equal the one the dashboard shows.

`compute_ytd_score` calls itself a "sync mirror" of `calculate_ytd_performance`.
It stopped being one: PR #110 gave the dashboard the intraday invalidation
credit and left the mirror behind. The screen showed 95.67 % while the podcast
said 93.17 % — a 2.51 point gap a listener could hear against the page in front
of them.

A full dual-session integration test would need the same rows visible to both a
sync and an async connection inside one transaction. These pin the behaviour
that actually drifted instead: the credit, its off-by-one, and the fact that
both sides read the same constant.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from app.services.dashboard_service import INVALIDATION_CREDIT_SCORE
from scripts._shared.brief_common import compute_ytd_score

# (date, close, decision) — the shape the query yields.
# Two rows and a J+1 horizon means exactly ONE scored day, so the average is
# that day's score and nothing else dilutes it.
_LOSS = [
    (date(2026, 1, 5), 100.0, "OPEN"),  # OPEN, then the price falls
    (date(2026, 1, 6), 90.0, "OPEN"),
]
# Five rows and a J+4 horizon: the session that SHOWS decision[0] is rows[1],
# while the horizon end is rows[4]. Only the former may credit.
_LOSS_J4 = [
    (date(2026, 1, 5), 100.0, "OPEN"),
    (date(2026, 1, 6), 99.0, "OPEN"),
    (date(2026, 1, 7), 98.0, "OPEN"),
    (date(2026, 1, 8), 97.0, "OPEN"),
    (date(2026, 1, 9), 90.0, "OPEN"),
]


def _session(rows, alerted):
    """A sync Session whose two queries return rows, then alerted sessions."""
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(all=lambda: rows),
        MagicMock(all=lambda: [(d,) for d in alerted]),
    ]
    return session


class TestTheCreditIsMirrored:
    def test_a_warned_loss_is_credited(self):
        scored = compute_ytd_score(
            _session(_LOSS, {date(2026, 1, 6)}),
            date(2026, 1, 6),
            "version-id",
            algorithm_name="regime",
        )
        assert scored == INVALIDATION_CREDIT_SCORE * 100

    def test_an_unwarned_loss_is_not_credited(self):
        scored = compute_ytd_score(
            _session(_LOSS, set()),
            date(2026, 1, 6),
            "version-id",
            algorithm_name="regime",
        )
        assert scored is not None
        assert scored < 0, "a loss nobody was warned about stays a loss"

    def test_the_credit_uses_the_session_that_shows_the_decision(self):
        """The alert fires on rows[i + 1], not on the horizon end.

        Crediting the horizon end would reward the wrong day — the same
        off-by-one the dashboard documents.
        """
        on_shown = compute_ytd_score(
            _session(_LOSS_J4, {date(2026, 1, 6)}), date(2026, 1, 9), "v"
        )
        on_horizon_end = compute_ytd_score(
            _session(_LOSS_J4, {date(2026, 1, 9)}), date(2026, 1, 9), "v"
        )
        assert on_shown == INVALIDATION_CREDIT_SCORE * 100
        assert on_horizon_end is not None and on_horizon_end < 0


class TestBothSidesShareTheDefinition:
    def test_the_mirror_reads_the_dashboard_constant(self):
        import inspect

        from scripts._shared import brief_common

        source = inspect.getsource(brief_common.compute_ytd_score)
        assert "INVALIDATION_CREDIT_SCORE" in source
        assert "delivery_status = 'sent'" in source, (
            "only a delivered alert credits a day — same rule as the dashboard"
        )
