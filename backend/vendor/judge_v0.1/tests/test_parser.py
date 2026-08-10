"""Brief parser — label-driven extraction from real fixtures."""

from __future__ import annotations

from judge.brief_parser import parse_brief_file
from judge.schema import Decision


def test_parse_monitor_brief(briefs_dir):
    b = parse_brief_file(str(briefs_dir / "20260730-CompassBrief-Ensemble-EN.txt"))
    assert b.session_date == "2026-07-31"
    assert b.last_close_date == "2026-07-30"
    assert b.base_decision is Decision.MONITOR
    assert b.base_confidence == 2.0
    assert b.base_direction_label == "NEUTRE"
    assert b.ytd == 89.27
    assert b.close == 3810.0
    assert b.weather.impact_10 == 3.0
    assert "slightly supportive" in b.press.impact_summary


def test_parse_hedge_brief_0803(briefs_dir):
    b = parse_brief_file(str(briefs_dir / "20260731-CompassBrief-Ensemble-EN.txt"))
    assert b.session_date == "2026-08-03"
    assert b.last_close_date == "2026-07-31"
    assert b.base_decision is Decision.HEDGE
    assert b.base_confidence == 2.0
    assert b.close == 4011.0
    assert b.weather.impact_10 == 2.0
    # the smoking-gun contradiction must survive parsing
    assert "favor modest long" in b.press.impact_summary.lower()
    assert "prices soaring" in b.press.supply.lower()


def test_parse_hedge_brief_0804(briefs_dir):
    b = parse_brief_file(str(briefs_dir / "20260803-CompassBrief-Ensemble-EN.txt"))
    assert b.session_date == "2026-08-04"
    assert b.base_decision is Decision.HEDGE
    assert b.base_confidence == 3.0
    assert b.close == 4402.0
    assert "decidedly bullish" in b.press.sentiment.lower()
