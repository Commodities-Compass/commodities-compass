"""Typed domain model for the `judge` macro-overlay layer.

`judge` sits above a base algorithm (regime / ensemble). It reads the last N
Compass daily briefs, detects macro/press/weather drift versus the technical
call, and — via a deterministic policy — may confirm, abstain (MONITOR) or flip
the base decision. This module holds only the immutable data shapes; behaviour
lives in the sibling modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Decision(str, Enum):
    """A trading stance for the horizon."""

    OPEN = "OPEN"      # commit long (bet up)
    HEDGE = "HEDGE"    # commit short (bet down)
    MONITOR = "MONITOR"  # abstain / stand aside


class Direction(str, Enum):
    """A directional view, decoupled from the commit/abstain decision."""

    UP = "UP"
    DOWN = "DOWN"
    NONE = "NONE"


class Stance(str, Enum):
    """The judge's read of macro context relative to the base call."""

    CONFIRM = "CONFIRM"
    CONTRADICT = "CONTRADICT"
    NEUTRAL = "NEUTRAL"


# Decision -> the directional view it embodies.
DECISION_DIRECTION: dict[Decision, Direction] = {
    Decision.OPEN: Direction.UP,
    Decision.HEDGE: Direction.DOWN,
    Decision.MONITOR: Direction.NONE,
}


@dataclass(frozen=True)
class WeatherRead:
    """The weather-watch slice of a brief."""

    impact_10: float | None       # X/10 market-impact score
    summary: str


@dataclass(frozen=True)
class PressRead:
    """The eco & press-review slice of a brief."""

    supply: str = ""
    fundamentals: str = ""
    market: str = ""
    sentiment: str = ""
    impact_summary: str = ""

    def full_text(self) -> str:
        parts = [
            ("SUPPLY", self.supply),
            ("FUNDAMENTALS", self.fundamentals),
            ("MARKET", self.market),
            ("MARKET SENTIMENT", self.sentiment),
            ("IMPACT SUMMARY", self.impact_summary),
        ]
        return "\n\n".join(f"{label}\n{body.strip()}" for label, body in parts if body.strip())


@dataclass(frozen=True)
class Brief:
    """One parsed Compass daily brief, keyed to the session it decides for."""

    session_date: str            # the trading session this brief decides for (YYYY-MM-DD)
    last_close_date: str         # last completed session used as input
    base_decision: Decision      # the base algorithm's call
    base_confidence: float       # the base algorithm's own 0-5 conviction
    base_direction_label: str    # raw direction string from the brief (NEUTRE/BAISSIERE/...)
    ytd: float | None
    press: PressRead
    weather: WeatherRead
    close: float | None = None
    volume: float | None = None
    rsi: float | None = None
    raw_text: str = ""


@dataclass(frozen=True)
class BaseCall:
    """A base-algorithm decision injected into the overlay.

    In the full system this comes from `regime` (running in shadow), NOT from
    the brief's own SIGNAL block. The press/weather content of the brief is
    algorithm-agnostic and is reused as-is; only the decision + conviction are
    swapped for the base algo's live call.
    """

    decision: Decision
    confidence: float          # 0-5 conviction (mapped from regime prob_up)
    direction_label: str = ""  # human label (UP/DOWN/NEUTRE/BAISSIERE/...)
    source: str = ""           # e.g. "regime/1.0.0"


@dataclass(frozen=True)
class Drift:
    """Cross-day movement in the macro picture, computed deterministically."""

    n_days: int
    weather_impact_series: tuple[float, ...] = ()
    weather_delta: float | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class JudgeVerdict:
    """The LLM judgment. Non-reproducible by design — logged for calibration."""

    suggested_direction: Direction
    confidence: int              # 1..5, rubric-anchored
    stance: Stance
    is_anomaly: bool
    evidence: tuple[str, ...]    # >=2 quoted brief items or forced NEUTRAL
    drift_summary: str
    disconfirming_case: str
    key_risk: str
    prompt_version: str = ""
    model_id: str = ""


@dataclass(frozen=True)
class JudgeOutcome:
    """The final fused decision plus the reasoning trail, for the shadow log."""

    session_date: str
    base_decision: Decision
    final_decision: Decision
    changed: bool
    verdict: JudgeVerdict
    drift: Drift
    rationale: str
    log_fields: dict[str, object] = field(default_factory=dict)
