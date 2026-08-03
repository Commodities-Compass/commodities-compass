"""Intraday alert engine tests — cross detection, dedup, rendering, loaders.

See docs/user-stories/P1-intraday-threshold-alerts-telegram.md §7.1.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models import AudAlertEvent, RefAlertRule
from scripts.intraday_monitor.db_writer import (
    LevelsMissingError,
    PrevPriceMissingError,
    append_observation,
    insert_alert_event,
    load_enabled_rules,
    load_levels,
    load_prev_price,
    update_delivery,
)
from scripts.intraday_monitor.engine import (
    Firing,
    RuleSpec,
    detect_cross,
    evaluate_rules,
    is_invalidation,
    render_message,
)
from tests.factories import (
    make_pl_contract_data_daily,
    make_pl_derived_indicators,
    make_ref_commodity,
    make_ref_contract,
    make_ref_exchange,
)

SESSION_DATE = date(2026, 7, 23)
LEVELS_DATE = date(2026, 7, 22)
OBSERVED_AT = datetime(2026, 7, 23, 10, 15, tzinfo=timezone.utc)


def _rule_spec(**overrides) -> RuleSpec:
    defaults = {
        "id": uuid.uuid4(),
        "rule_key": "close_below_s1",
        "level_column": "s1",
        "level_label": "SUPPORT 1",
        "comparator": "below",
        "direction": "bearish",
        "severity": "warning",
        "message_template_key": "invalidation_v1",
    }
    return RuleSpec(**(defaults | overrides))


# ---------------------------------------------------------------------------
# Pure logic: detect_cross
# ---------------------------------------------------------------------------


class TestDetectCross:
    def test_cross_below_fires(self):
        assert detect_cross(Decimal("3760"), Decimal("3750"), Decimal("3755"), "below")

    def test_cross_above_fires(self):
        assert detect_cross(Decimal("3920"), Decimal("3930"), Decimal("3928"), "above")

    def test_no_cross_no_fire(self):
        assert not detect_cross(
            Decimal("3800"), Decimal("3790"), Decimal("3755"), "below"
        )

    def test_already_below_no_fire(self):
        # Edge-triggered: prev must be on/above the level.
        assert not detect_cross(
            Decimal("3750"), Decimal("3740"), Decimal("3755"), "below"
        )

    def test_prev_exactly_on_level_then_break_fires(self):
        assert detect_cross(Decimal("3755"), Decimal("3750"), Decimal("3755"), "below")

    def test_curr_exactly_on_level_no_fire(self):
        # Strict inequality on curr: touching the level is not a break.
        assert not detect_cross(
            Decimal("3760"), Decimal("3755"), Decimal("3755"), "below"
        )

    def test_invalid_comparator_raises(self):
        with pytest.raises(ValueError):
            detect_cross(Decimal("1"), Decimal("2"), Decimal("3"), "sideways")


# ---------------------------------------------------------------------------
# Pure logic: evaluate_rules
# ---------------------------------------------------------------------------


def _both_rules() -> list[RuleSpec]:
    return [
        _rule_spec(),  # close_below_s1, bearish
        _rule_spec(
            rule_key="close_above_r1",
            level_column="r1",
            level_label="RESISTANCE 1",
            comparator="above",
            direction="bullish",
        ),
    ]


class TestEvaluateRules:
    def test_fires_invalidating_rule_only(self):
        # OPEN thesis (bullish) → only the S1 (bearish) break invalidates.
        levels = {"s1": Decimal("3755"), "r1": Decimal("3928")}
        firings = evaluate_rules(
            _both_rules(),
            levels,
            prev_price=Decimal("3760"),
            curr_price=Decimal("3750"),
            signal_decision="OPEN",
        )
        assert len(firings) == 1
        assert firings[0].rule.rule_key == "close_below_s1"
        assert firings[0].level_value == Decimal("3755")

    def test_gap_through_level_fires(self):
        # First tick of session: prev comes from previous-session daily close.
        rules = [_rule_spec()]
        levels = {"s1": Decimal("3755")}
        firings = evaluate_rules(
            rules,
            levels,
            prev_price=Decimal("3800"),
            curr_price=Decimal("3740"),
            signal_decision="OPEN",
        )
        assert len(firings) == 1

    def test_between_levels_no_fire(self):
        levels = {"s1": Decimal("3755"), "r1": Decimal("3928")}
        assert (
            evaluate_rules(
                _both_rules(),
                levels,
                prev_price=Decimal("3800"),
                curr_price=Decimal("3810"),
                signal_decision="OPEN",
            )
            == []
        )

    def test_missing_level_skips_rule(self):
        rules = [_rule_spec()]  # bearish, armed under OPEN
        assert (
            evaluate_rules(
                rules,
                {"s1": None},
                prev_price=Decimal("3800"),
                curr_price=Decimal("3700"),
                signal_decision="OPEN",
            )
            == []
        )


class TestInvalidationFilter:
    """The break must CONTRADICT the day's thesis to fire (backtest-validated)."""

    def test_open_s1_break_fires(self):
        firings = evaluate_rules(
            [_rule_spec()],
            {"s1": Decimal("3755")},
            prev_price=Decimal("3760"),
            curr_price=Decimal("3750"),
            signal_decision="OPEN",
        )
        assert len(firings) == 1

    def test_open_r1_break_suppressed_confirmation(self):
        # Price breaks R1 upward while OPEN (bullish) → confirms, not invalidates.
        r1_rule = _rule_spec(
            rule_key="close_above_r1",
            level_column="r1",
            comparator="above",
            direction="bullish",
        )
        assert (
            evaluate_rules(
                [r1_rule],
                {"r1": Decimal("3928")},
                prev_price=Decimal("3920"),
                curr_price=Decimal("3930"),
                signal_decision="OPEN",
            )
            == []
        )

    def test_hedge_r1_break_fires(self):
        r1_rule = _rule_spec(
            rule_key="close_above_r1",
            level_column="r1",
            comparator="above",
            direction="bullish",
        )
        firings = evaluate_rules(
            [r1_rule],
            {"r1": Decimal("3928")},
            prev_price=Decimal("3920"),
            curr_price=Decimal("3930"),
            signal_decision="HEDGE",
        )
        assert len(firings) == 1

    def test_hedge_s1_break_suppressed_confirmation(self):
        assert (
            evaluate_rules(
                [_rule_spec()],
                {"s1": Decimal("3755")},
                prev_price=Decimal("3760"),
                curr_price=Decimal("3750"),
                signal_decision="HEDGE",
            )
            == []
        )

    def test_monitor_suppresses_all(self):
        levels = {"s1": Decimal("3755"), "r1": Decimal("3928")}
        assert (
            evaluate_rules(
                _both_rules(),
                levels,
                prev_price=Decimal("3760"),
                curr_price=Decimal("3750"),
                signal_decision="MONITOR",
            )
            == []
        )

    def test_missing_decision_suppresses_all(self):
        # "pas de signal, pas d'alerte" — fail-safe.
        levels = {"s1": Decimal("3755"), "r1": Decimal("3928")}
        assert (
            evaluate_rules(
                _both_rules(),
                levels,
                prev_price=Decimal("3760"),
                curr_price=Decimal("3750"),
                signal_decision=None,
            )
            == []
        )

    def test_is_invalidation_matrix(self):
        assert is_invalidation("bearish", "OPEN") is True
        assert is_invalidation("bullish", "OPEN") is False
        assert is_invalidation("bullish", "HEDGE") is True
        assert is_invalidation("bearish", "HEDGE") is False
        assert is_invalidation("bearish", "MONITOR") is False
        assert is_invalidation("bullish", None) is False
        assert is_invalidation("bearish", "open") is True  # case-insensitive


# ---------------------------------------------------------------------------
# Pure logic: render_message
# ---------------------------------------------------------------------------


class TestRenderMessage:
    def test_message_contains_contract_level_price_disclaimer(self):
        text = render_message(
            contract_code="CAU26",
            price=Decimal("3750.5"),
            level_label="SUPPORT 1",
            level_value=Decimal("3755.670000"),
            observed_at=OBSERVED_AT,
            signal_decision="OPEN",
        )
        assert "CAU26" in text
        assert "SUPPORT 1" in text
        assert "3755.67" in text
        assert "3750.5" in text
        assert "10:15" in text
        assert "OPEN" in text
        assert "pas un conseil" in text

    def test_message_rollsafe_contract_code(self):
        # The resolved contract code is used verbatim — never a hardcoded one.
        text = render_message(
            contract_code="CAZ26",
            price=Decimal("3750"),
            level_label="SUPPORT 1",
            level_value=Decimal("3755"),
            observed_at=OBSERVED_AT,
            signal_decision=None,
        )
        assert "CAZ26" in text

    def test_message_without_signal_decision_has_no_none(self):
        text = render_message(
            contract_code="CAU26",
            price=Decimal("3750"),
            level_label="SUPPORT 1",
            level_value=Decimal("3755"),
            observed_at=OBSERVED_AT,
            signal_decision=None,
        )
        assert "None" not in text


# ---------------------------------------------------------------------------
# DB layer: fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def contract(sync_db_session):
    exchange = make_ref_exchange()
    sync_db_session.add(exchange)
    sync_db_session.flush()
    commodity = make_ref_commodity(exchange.id)
    sync_db_session.add(commodity)
    sync_db_session.flush()
    contract = make_ref_contract(commodity.id, code="CAU26")
    sync_db_session.add(contract)
    sync_db_session.flush()
    return contract


def _db_rule(session, **overrides) -> RefAlertRule:
    defaults = {
        "rule_key": "close_below_s1",
        "metric_column": "close",
        "level_column": "s1",
        "level_label": "SUPPORT 1",
        "comparator": "below",
        "direction": "bearish",
    }
    rule = RefAlertRule(**(defaults | overrides))
    session.add(rule)
    session.flush()
    return rule


def _firing_for(rule: RefAlertRule) -> Firing:
    spec = RuleSpec(
        id=rule.id,
        rule_key=rule.rule_key,
        level_column=rule.level_column,
        level_label=rule.level_label,
        comparator=rule.comparator,
        direction=rule.direction,
        severity=rule.severity,
        message_template_key=rule.message_template_key,
    )
    return Firing(
        rule=spec,
        level_value=Decimal("3755.670000"),
        prev_price=Decimal("3760"),
        curr_price=Decimal("3750"),
    )


# ---------------------------------------------------------------------------
# DB layer: dedup / idempotence
# ---------------------------------------------------------------------------


class TestDedup:
    def test_first_insert_returns_event_id(self, sync_db_session, contract):
        rule = _db_rule(sync_db_session)
        event_id = insert_alert_event(
            sync_db_session,
            firing=_firing_for(rule),
            contract_id=contract.id,
            session_date=SESSION_DATE,
            observed_at=OBSERVED_AT,
            signal_decision="OPEN",
            channel="console",
        )
        assert event_id is not None

    def test_second_insert_same_session_dedups(self, sync_db_session, contract):
        rule = _db_rule(sync_db_session)
        firing = _firing_for(rule)
        first = insert_alert_event(
            sync_db_session,
            firing=firing,
            contract_id=contract.id,
            session_date=SESSION_DATE,
            observed_at=OBSERVED_AT,
            signal_decision="OPEN",
            channel="console",
        )
        second = insert_alert_event(
            sync_db_session,
            firing=firing,
            contract_id=contract.id,
            session_date=SESSION_DATE,
            observed_at=datetime(2026, 7, 23, 11, 0, tzinfo=timezone.utc),
            signal_decision="OPEN",
            channel="console",
        )
        assert first is not None
        assert second is None
        count = (
            sync_db_session.query(AudAlertEvent)
            .filter_by(rule_id=rule.id, session_date=SESSION_DATE)
            .count()
        )
        assert count == 1

    def test_next_session_fires_again(self, sync_db_session, contract):
        rule = _db_rule(sync_db_session)
        firing = _firing_for(rule)
        first = insert_alert_event(
            sync_db_session,
            firing=firing,
            contract_id=contract.id,
            session_date=SESSION_DATE,
            observed_at=OBSERVED_AT,
            signal_decision="OPEN",
            channel="console",
        )
        second = insert_alert_event(
            sync_db_session,
            firing=firing,
            contract_id=contract.id,
            session_date=date(2026, 7, 24),
            observed_at=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
            signal_decision="OPEN",
            channel="console",
        )
        assert first is not None
        assert second is not None

    def test_update_delivery_marks_sent(self, sync_db_session, contract):
        rule = _db_rule(sync_db_session)
        event_id = insert_alert_event(
            sync_db_session,
            firing=_firing_for(rule),
            contract_id=contract.id,
            session_date=SESSION_DATE,
            observed_at=OBSERVED_AT,
            signal_decision=None,
            channel="telegram",
        )
        assert event_id is not None
        update_delivery(
            sync_db_session,
            event_id=event_id,
            status="sent",
            provider_message_id="12345",
        )
        event = sync_db_session.get(AudAlertEvent, event_id)
        assert event.delivery_status == "sent"
        assert event.provider_message_id == "12345"


# ---------------------------------------------------------------------------
# DB layer: loaders
# ---------------------------------------------------------------------------


class TestLoaders:
    def test_load_enabled_rules_filters_disabled(self, sync_db_session):
        _db_rule(sync_db_session)
        _db_rule(
            sync_db_session,
            rule_key="close_above_r1",
            level_column="r1",
            level_label="RESISTANCE 1",
            comparator="above",
            direction="bullish",
            enabled=False,
        )
        rules = load_enabled_rules(sync_db_session)
        keys = [r.rule_key for r in rules]
        assert "close_below_s1" in keys
        assert "close_above_r1" not in keys

    def test_load_levels_returns_pivot_columns(self, sync_db_session, contract):
        sync_db_session.add(
            make_pl_derived_indicators(
                contract.id,
                date=LEVELS_DATE,
                s1=Decimal("3755.670000"),
                r1=Decimal("3928.670000"),
                s2=Decimal("3600.000000"),
            )
        )
        sync_db_session.flush()
        levels = load_levels(sync_db_session, contract.id, LEVELS_DATE)
        assert levels["s1"] == Decimal("3755.670000")
        assert levels["r1"] == Decimal("3928.670000")
        assert levels["s2"] == Decimal("3600.000000")

    def test_load_levels_missing_row_raises(self, sync_db_session, contract):
        with pytest.raises(LevelsMissingError):
            load_levels(sync_db_session, contract.id, LEVELS_DATE)

    def test_load_prev_price_prefers_last_intraday_obs(self, sync_db_session, contract):
        sync_db_session.add(
            make_pl_contract_data_daily(
                contract.id, date=LEVELS_DATE, close=Decimal("3800")
            )
        )
        append_observation(
            sync_db_session,
            contract_id=contract.id,
            session_date=SESSION_DATE,
            observed_at=datetime(2026, 7, 23, 9, 45, tzinfo=timezone.utc),
            last_price=Decimal("3770"),
            trade_time=None,
        )
        append_observation(
            sync_db_session,
            contract_id=contract.id,
            session_date=SESSION_DATE,
            observed_at=datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc),
            last_price=Decimal("3760"),
            trade_time=None,
        )
        prev = load_prev_price(
            sync_db_session,
            contract_id=contract.id,
            session_date=SESSION_DATE,
            fallback_date=LEVELS_DATE,
        )
        assert prev == Decimal("3760")

    def test_load_prev_price_falls_back_to_daily_close(self, sync_db_session, contract):
        sync_db_session.add(
            make_pl_contract_data_daily(
                contract.id, date=LEVELS_DATE, close=Decimal("3800")
            )
        )
        sync_db_session.flush()
        prev = load_prev_price(
            sync_db_session,
            contract_id=contract.id,
            session_date=SESSION_DATE,
            fallback_date=LEVELS_DATE,
        )
        assert prev == Decimal("3800")

    def test_load_prev_price_missing_everything_raises(self, sync_db_session, contract):
        with pytest.raises(PrevPriceMissingError):
            load_prev_price(
                sync_db_session,
                contract_id=contract.id,
                session_date=SESSION_DATE,
                fallback_date=LEVELS_DATE,
            )
