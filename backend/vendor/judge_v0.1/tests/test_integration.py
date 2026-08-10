"""Full-system path: regime shadow call -> judge overlay -> shadow sink."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from judge.brief_parser import parse_brief_file
from judge.integration import prob_up_to_confidence, regime_base_call, run_shadow
from judge.llm import GoldenJudgeLLM
from judge.schema import Brief, Decision


@dataclass
class FakeRegimeDecision:
    decision: str
    prob_up: float
    regime: str
    specialist: str


class InMemoryStore:
    def __init__(self, briefs: dict[str, list[Brief]]):
        self._briefs = briefs

    def load_recent(self, session_date: str, n: int) -> list[Brief]:
        return self._briefs[session_date][-n:]


class ListSink:
    def __init__(self):
        self.rows: list[dict] = []

    def write(self, log_fields: dict) -> None:
        self.rows.append(log_fields)


def test_prob_up_to_confidence_monotonic():
    assert prob_up_to_confidence(0.5) == 0.0
    assert prob_up_to_confidence(0.21) == pytest.approx(2.9)
    assert prob_up_to_confidence(0.0) == 5.0
    assert prob_up_to_confidence(1.0) == 5.0


def test_regime_base_call_maps_direction():
    bc = regime_base_call(FakeRegimeDecision("HEDGE", 0.21, "highvol", "highvol"))
    assert bc.decision is Decision.HEDGE
    assert bc.direction_label == "DOWN"
    assert bc.source == "regime/1.0.0"


def test_full_system_rescues_the_0803_hedge(briefs_dir, golden_path):
    """regime's real 07-31 call (HEDGE, P=0.21) overlaid -> must not stay HEDGE."""
    b0730 = parse_brief_file(str(briefs_dir / "20260730-CompassBrief-Ensemble-EN.txt"))
    b0731 = parse_brief_file(str(briefs_dir / "20260731-CompassBrief-Ensemble-EN.txt"))
    store = InMemoryStore({"2026-08-03": [b0730, b0731]})
    sink = ListSink()
    rd = FakeRegimeDecision(decision="HEDGE", prob_up=0.2133, regime="highvol", specialist="highvol")

    out = run_shadow(
        session_date="2026-08-03",
        regime_decision=rd,
        store=store,
        llm=GoldenJudgeLLM.from_file(str(golden_path)),
        sink=sink,
    )

    assert out.base_decision is Decision.HEDGE
    assert out.final_decision is not Decision.HEDGE
    assert out.final_decision is Decision.MONITOR
    # provenance logged for the pipeline analysis
    row = sink.rows[0]
    assert row["base_source"] == "regime/1.0.0"
    assert row["specialist"] == "highvol"
    assert row["prob_up"] == 0.2133
    assert row["final_decision"] == "MONITOR"
