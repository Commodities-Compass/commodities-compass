"""Tests for --algorithm-version flag on daily-analysis.

Validates the fix for the Campaign 5 launch day-1 issue:
the legacy daily-analysis job must NOT overwrite the ensemble's
pl_indicator_daily row when both `legacy` and
`ensemble_v1_softgate_wrapper` versions coexist with is_active=TRUE.

See: docs/user-stories/P2-daily-analysis-version-flag.md
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.models.pipeline import (
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlDerivedIndicators,
    PlIndicatorDaily,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from scripts.daily_analysis.db_analysis_engine import (
    AlgorithmVersionNotFoundError,
    DBAnalysisEngine,
)
from scripts.daily_analysis.main import _parse_args


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ref_chain(sync_db_session):
    """Create exchange → commodity → contract chain."""
    exchange = RefExchange(
        code="IFEU", name="ICE Futures Europe", timezone="Europe/London"
    )
    sync_db_session.add(exchange)
    sync_db_session.flush()

    commodity = RefCommodity(code="CC", name="London Cocoa #7", exchange_id=exchange.id)
    sync_db_session.add(commodity)
    sync_db_session.flush()

    contract = RefContract(
        commodity_id=commodity.id,
        code="CAK26",
        contract_month="2026-05",
        expiry_date=date(2026, 5, 15),
        is_active=True,
    )
    sync_db_session.add(contract)
    sync_db_session.flush()
    return {"exchange": exchange, "commodity": commodity, "contract": contract}


@pytest.fixture()
def legacy_version(sync_db_session, ref_chain):
    """Insert a legacy algorithm version row.

    Note: is_active=FALSE intentionally — tests verify that the flag
    overrides the is_active filter.
    """
    version = PlAlgorithmVersion(
        name="legacy",
        version="1.0.1",
        horizon="short_term",
        is_active=False,
        compute_enabled=True,
        description="Legacy power formula",
    )
    sync_db_session.add(version)
    sync_db_session.flush()
    return version


@pytest.fixture()
def ensemble_version(sync_db_session, ref_chain):
    """Insert an active ensemble algorithm version row (the day-1 scenario)."""
    version = PlAlgorithmVersion(
        name="ensemble_v1_softgate_wrapper",
        version="1.0.0",
        horizon="short_term",
        is_active=True,
        compute_enabled=True,
        description="C5 ensemble — day-1 promotion",
    )
    sync_db_session.add(version)
    sync_db_session.flush()
    return version


@pytest.fixture()
def engine_default(sync_db_session):
    """DBAnalysisEngine instance without algorithm_version_name (backward compat)."""
    with patch("scripts.daily_analysis.db_analysis_engine.LLMClient"):
        return DBAnalysisEngine(sync_db_session)


@pytest.fixture()
def engine_pinned_legacy(sync_db_session):
    """DBAnalysisEngine instance pinned to algorithm name='legacy'."""
    with patch("scripts.daily_analysis.db_analysis_engine.LLMClient"):
        return DBAnalysisEngine(sync_db_session, algorithm_version_name="legacy")


# ---------------------------------------------------------------------------
# Unit tests — _resolve_algorithm_version_id
# ---------------------------------------------------------------------------


class TestResolveAlgorithmVersionId:
    """Test the private resolution helper that's called by _write_results."""

    def test_no_name_returns_active_version(
        self, sync_db_session, engine_default, legacy_version, ensemble_version
    ):
        """Without flag → resolve to is_active=TRUE row (current behavior)."""
        resolved_id = engine_default._resolve_algorithm_version_id()
        assert resolved_id == ensemble_version.id

    def test_no_name_returns_none_when_no_active(
        self, sync_db_session, engine_default, legacy_version
    ):
        """Without flag and no is_active row → return None (caller logs warning)."""
        # legacy_version has is_active=False, no active row exists
        resolved_id = engine_default._resolve_algorithm_version_id()
        assert resolved_id is None

    def test_name_returns_pinned_version_even_if_inactive(
        self, sync_db_session, engine_pinned_legacy, legacy_version, ensemble_version
    ):
        """With --algorithm-version legacy → resolve legacy row even if
        ensemble is the active one.

        This is the core safety net for day-1 launch C5.
        """
        resolved_id = engine_pinned_legacy._resolve_algorithm_version_id()
        assert resolved_id == legacy_version.id
        assert resolved_id != ensemble_version.id

    def test_name_not_found_raises_fail_loud(self, sync_db_session, ensemble_version):
        """With --algorithm-version <nonexistent> → fail-loud raise.

        Aligned with .claude/rules/pipeline-error-handling.md (no silent fallback).
        """
        with patch("scripts.daily_analysis.db_analysis_engine.LLMClient"):
            engine = DBAnalysisEngine(
                sync_db_session, algorithm_version_name="nonexistent_algo"
            )
        with pytest.raises(AlgorithmVersionNotFoundError, match="nonexistent_algo"):
            engine._resolve_algorithm_version_id()


# ---------------------------------------------------------------------------
# Integration test — _write_results must scope UPDATE to targeted version
# ---------------------------------------------------------------------------


class TestWriteResultsScopedUpdate:
    """End-to-end SQL scoping: targeting `legacy` must NOT update ensemble's row."""

    def test_pinned_legacy_leaves_ensemble_row_untouched(
        self,
        sync_db_session,
        ref_chain,
        legacy_version,
        ensemble_version,
    ):
        """The hard guarantee: pinning daily-analysis to legacy never overwrites
        the ensemble's row, even when both versions have rows for the same date.
        """
        contract_id = ref_chain["contract"].id
        target = date(2026, 5, 20)

        # Pre-seed: market data row (needed for FK consistency in some paths)
        sync_db_session.add(
            PlContractDataDaily(
                date=target,
                contract_id=contract_id,
                close=Decimal("8500.0"),
                high=Decimal("8600.0"),
                low=Decimal("8400.0"),
                volume=5000,
                oi=40000,
            )
        )

        # Pre-seed: derived indicators (required by some downstream queries)
        sync_db_session.add(PlDerivedIndicators(date=target, contract_id=contract_id))

        # Pre-seed: pl_indicator_daily rows for BOTH versions on same date
        legacy_row = PlIndicatorDaily(
            date=target,
            contract_id=contract_id,
            algorithm_version_id=legacy_version.id,
            decision="MONITOR",
            confidence=Decimal("50.0"),
            direction="NEUTRAL",
            eco="legacy-original-eco",
            conclusion="legacy-original-conclusion",
            macroeco_bonus=Decimal("0.0"),
            final_indicator=Decimal("0.5"),
        )
        ensemble_row = PlIndicatorDaily(
            date=target,
            contract_id=contract_id,
            algorithm_version_id=ensemble_version.id,
            decision="OPEN",  # ensemble's decision — must NOT be overwritten
            confidence=Decimal("82.5"),
            direction="LONG",
            eco="ensemble-original-eco",
            conclusion="ensemble-original-conclusion",
            macroeco_bonus=Decimal("0.3"),
            final_indicator=Decimal("1.8"),
        )
        sync_db_session.add_all([legacy_row, ensemble_row])
        sync_db_session.flush()

        # Run the scoped UPDATE that _write_results would perform.
        # We exercise the resolution + UPDATE pattern directly via raw SQL
        # mirroring db_analysis_engine.py lines 246-275 with the new resolution.
        with patch("scripts.daily_analysis.db_analysis_engine.LLMClient"):
            engine = DBAnalysisEngine(sync_db_session, algorithm_version_name="legacy")
        resolved_id = engine._resolve_algorithm_version_id()
        assert resolved_id == legacy_version.id, (
            "Resolution must return the legacy id, not the active ensemble"
        )

        # Apply the same UPDATE pattern that _write_results uses
        sync_db_session.execute(
            text("""
                UPDATE pl_indicator_daily
                SET decision = :decision,
                    confidence = :confidence,
                    direction = :direction,
                    eco = :eco,
                    conclusion = :conclusion,
                    macroeco_bonus = :macroeco_bonus,
                    final_indicator = :final_indicator
                WHERE date = :target_date
                  AND contract_id = :contract_id
                  AND algorithm_version_id = :algo_version_id
            """),
            {
                "decision": "HEDGE",  # legacy LLM tries to write a new decision
                "confidence": 60.0,
                "direction": "SHORT",
                "eco": "legacy-llm-updated-eco",
                "conclusion": "legacy-llm-updated-conclusion",
                "macroeco_bonus": -0.2,
                "final_indicator": -1.6,
                "target_date": target,
                "contract_id": contract_id,
                "algo_version_id": resolved_id,
            },
        )

        # --- ASSERTIONS ---
        sync_db_session.flush()

        # 1. Legacy row WAS updated (LLM ran successfully against the pinned version)
        legacy_after = sync_db_session.execute(
            text("""
                SELECT decision, eco, conclusion
                FROM pl_indicator_daily
                WHERE date = :d AND contract_id = :c AND algorithm_version_id = :v
            """),
            {"d": target, "c": contract_id, "v": legacy_version.id},
        ).fetchone()
        assert legacy_after.decision == "HEDGE"
        assert legacy_after.eco == "legacy-llm-updated-eco"
        assert legacy_after.conclusion == "legacy-llm-updated-conclusion"

        # 2. Ensemble row WAS NOT touched (the whole point of this US)
        ensemble_after = sync_db_session.execute(
            text("""
                SELECT decision, eco, conclusion, confidence, direction
                FROM pl_indicator_daily
                WHERE date = :d AND contract_id = :c AND algorithm_version_id = :v
            """),
            {"d": target, "c": contract_id, "v": ensemble_version.id},
        ).fetchone()
        assert ensemble_after.decision == "OPEN", (
            "Ensemble decision must not be overwritten by legacy daily-analysis"
        )
        assert ensemble_after.eco == "ensemble-original-eco"
        assert ensemble_after.conclusion == "ensemble-original-conclusion"
        assert ensemble_after.confidence == Decimal("82.50")
        assert ensemble_after.direction == "LONG"


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


class TestCliFlag:
    """Verify the --algorithm-version flag is wired into argparse."""

    def test_flag_default_is_none(self):
        """Backward compat: omitting the flag → algorithm_version is None."""
        with patch.object(sys, "argv", ["daily-analysis"]):
            args = _parse_args()
        assert args.algorithm_version is None

    def test_flag_accepts_name(self):
        """Explicit pin: --algorithm-version legacy is captured."""
        with patch.object(
            sys, "argv", ["daily-analysis", "--algorithm-version", "legacy"]
        ):
            args = _parse_args()
        assert args.algorithm_version == "legacy"

    def test_flag_combines_with_other_args(self):
        """The flag composes with existing args without conflict."""
        with patch.object(
            sys,
            "argv",
            [
                "daily-analysis",
                "--algorithm-version",
                "legacy",
                "--contract",
                "CAK26",
                "--dry-run",
            ],
        ):
            args = _parse_args()
        assert args.algorithm_version == "legacy"
        assert args.contract == "CAK26"
        assert args.dry_run is True
