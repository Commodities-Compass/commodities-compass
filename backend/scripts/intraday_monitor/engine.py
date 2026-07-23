"""Alert engine — pure logic: edge-triggered cross detection + rendering.

No DB access here (see db_writer.py). The engine compares the previous and
current observed price to each rule's level; a rule fires only when the
price *crosses* the level between two ticks (edge-triggered), which also
catches gaps through the level at session open (prev = previous-session
daily close fallback).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping, Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuleSpec:
    """In-memory mirror of one enabled ref_alert_rule row."""

    id: uuid.UUID
    rule_key: str
    level_column: str
    level_label: str
    comparator: str  # 'below' | 'above'
    direction: str  # 'bearish' | 'bullish'
    severity: str
    message_template_key: str


@dataclass(frozen=True)
class Firing:
    """One rule whose level was crossed on this tick."""

    rule: RuleSpec
    level_value: Decimal
    prev_price: Decimal
    curr_price: Decimal


def detect_cross(prev: Decimal, curr: Decimal, level: Decimal, comparator: str) -> bool:
    """Edge-triggered crossing: prev on/inside the level, curr strictly beyond."""
    if comparator == "below":
        return prev >= level and curr < level
    if comparator == "above":
        return prev <= level and curr > level
    raise ValueError(f"Unknown comparator: {comparator!r}")


def evaluate_rules(
    rules: Sequence[RuleSpec],
    levels: Mapping[str, Decimal | None],
    prev_price: Decimal,
    curr_price: Decimal,
) -> list[Firing]:
    """Return the rules whose level was crossed between prev and curr."""
    firings: list[Firing] = []
    for rule in rules:
        level = levels.get(rule.level_column)
        if level is None:
            logger.warning(
                "Rule %s skipped: level column %s is NULL for the reference session",
                rule.rule_key,
                rule.level_column,
            )
            continue
        if detect_cross(prev_price, curr_price, level, rule.comparator):
            firings.append(
                Firing(
                    rule=rule,
                    level_value=level,
                    prev_price=prev_price,
                    curr_price=curr_price,
                )
            )
    return firings


def _fmt(value: Decimal) -> str:
    """Render a Decimal without trailing zeros (3755.670000 → 3755.67)."""
    normalized = value.normalize()
    return f"{normalized:f}"


def render_message(
    *,
    contract_code: str,
    price: Decimal,
    level_label: str,
    level_value: Decimal,
    observed_at: datetime,
    signal_decision: str | None,
) -> str:
    """Deterministic FR message (template key invalidation_v1, Telegram HTML)."""
    time_utc = observed_at.astimezone(timezone.utc).strftime("%H:%M")
    signal_line = (
        f"Signal <b>{signal_decision}</b> du jour remis en cause"
        if signal_decision
        else "Le signal du jour est remis en cause"
    )
    return (
        "⚠️ <b>Compass CC — Alerte intraday</b>\n"
        f"<b>{contract_code}</b> : le cours (<b>{_fmt(price)}</b>) a franchi "
        f"<b>{level_label} à {_fmt(level_value)}</b> à <b>{time_utc} UTC</b>.\n"
        f"{signal_line} (horizon 4-5 sessions).\n"
        "<i>Information de marché, pas un conseil en investissement.</i>"
    )
