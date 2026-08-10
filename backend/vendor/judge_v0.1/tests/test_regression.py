"""Regression fixture grounded in the real 07-31/08-03 failure.

Pass condition: on the session where both regime and the ensemble committed a
bearish HEDGE right before a +9.75% move, the judge overlay must NOT keep the
HEDGE — it must resolve to MONITOR or FLIP. And the production score must
improve versus the un-overlaid base.
"""

from __future__ import annotations

from judge.brief_parser import parse_brief_file
from judge.llm import GoldenJudgeLLM
from judge.runner import decide
from judge.schema import Decision
from judge.scoring import score_decision

# Realized J+1 move used to score each decision (signed fractional return).
# 07-31 decision -> 07-31 closed 4011 vs 3810  = +5.28%
# 08-03 decision -> 08-03 closed 4402 vs 4011  = +9.75%  (the miss)
REALIZED = {
    "2026-07-31": (3810.0, 4011.0),
    "2026-08-03": (4011.0, 4402.0),
}


def _move(session: str) -> float:
    t, t1 = REALIZED[session]
    return (t1 - t) / t


def _briefs(briefs_dir):
    return {
        "0730": parse_brief_file(str(briefs_dir / "20260730-CompassBrief-Ensemble-EN.txt")),
        "0731": parse_brief_file(str(briefs_dir / "20260731-CompassBrief-Ensemble-EN.txt")),
        "0803": parse_brief_file(str(briefs_dir / "20260803-CompassBrief-Ensemble-EN.txt")),
    }


def test_0803_hedge_is_not_kept(briefs_dir, golden_path):
    """THE proof case: the bearish HEDGE into +9.75% must not survive."""
    b = _briefs(briefs_dir)
    llm = GoldenJudgeLLM.from_file(str(golden_path))
    out = decide([b["0730"], b["0731"]], llm)  # decides session 2026-08-03

    assert out.base_decision is Decision.HEDGE
    assert out.final_decision is not Decision.HEDGE, out.rationale
    assert out.final_decision in (Decision.MONITOR, Decision.OPEN)
    assert out.changed


def test_0803_overlay_improves_score(briefs_dir, golden_path):
    b = _briefs(briefs_dir)
    llm = GoldenJudgeLLM.from_file(str(golden_path))
    out = decide([b["0730"], b["0731"]], llm)

    move = _move("2026-08-03")
    base_score = score_decision(out.base_decision, move)   # HEDGE -> -0.195
    overlay_score = score_decision(out.final_decision, move)

    assert base_score < 0
    assert overlay_score > base_score
    assert overlay_score - base_score > 1.0  # material improvement


def test_0804_strong_bull_drift_flips_to_open(briefs_dir, golden_path):
    """Escalated bullish drift (Ghana -16%, +6.8% NY) clears the flip bar."""
    b = _briefs(briefs_dir)
    llm = GoldenJudgeLLM.from_file(str(golden_path))
    out = decide([b["0731"], b["0803"]], llm)  # decides session 2026-08-04

    assert out.base_decision is Decision.HEDGE
    assert out.final_decision is Decision.OPEN
    assert out.verdict.confidence >= 4


def test_0731_weak_signal_keeps_monitor(briefs_dir, golden_path):
    """Quiet/mildly-supportive day: overlay must not manufacture a commit."""
    b = _briefs(briefs_dir)
    llm = GoldenJudgeLLM.from_file(str(golden_path))
    out = decide([b["0730"]], llm)  # decides session 2026-07-31

    assert out.base_decision is Decision.MONITOR
    assert out.final_decision is Decision.MONITOR
    assert not out.changed


def test_log_fields_present(briefs_dir, golden_path):
    b = _briefs(briefs_dir)
    llm = GoldenJudgeLLM.from_file(str(golden_path))
    out = decide([b["0730"], b["0731"]], llm)
    for key in ("session_date", "base_decision", "final_decision", "changed",
                "judge_confidence", "rationale", "weather_series"):
        assert key in out.log_fields
