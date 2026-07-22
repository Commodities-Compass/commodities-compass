"""Guards the pl_derived_indicators fan-out corruption.

The macroeco_bonus LEFT JOIN in the market loaders used to fan the OHLCV series
out over the pl_indicator_daily (algorithm_version, language) dimensions →
duplicate dates → every rolling/recursive indicator (EMA, RSI/ATR Wilder, 252d
z-score) computed over a doubled series → CORRUPTED pl_derived_indicators (which
the ensemble/dashboard then consume). It went unnoticed for months because the
writer upserts one row/date (stored table looks clean) and no test reproduced
the multi-version/multi-language fan-out.

This locks the "never again" guards:
  1. the loader returns exactly one row per date even with several versions AND
     languages present (the regression that would have caught it);
  2. the fail-loud uniqueness assert fires if a fan-out ever re-appears;
  3. macroeco is attached per-version without re-introducing the fan-out.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from app.engine.runner import (
    _assert_unique_dates,
    _attach_version_macroeco,
    load_market_data,
)
from app.models.pipeline import (
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlIndicatorDaily,
)
from app.models.reference import RefCommodity, RefContract, RefExchange


def _setup(
    session: Session, *, versions: list[str], languages: list[str]
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    ex = RefExchange(code="ICE-FO", name="ICE", timezone="UTC")
    session.add(ex)
    session.flush()
    com = RefCommodity(code="CC-FO", name="Cocoa", exchange_id=ex.id)
    session.add(com)
    session.flush()
    c = RefContract(
        commodity_id=com.id, code="CAFO26", contract_month="U26", is_active=True
    )
    session.add(c)
    session.flush()
    vids: list[uuid.UUID] = []
    for i, vname in enumerate(versions):
        v = PlAlgorithmVersion(
            name=vname, version=f"1.0.{i}", horizon="short_term", is_active=(i == 0)
        )
        session.add(v)
        session.flush()
        vids.append(v.id)
    days = [date(2026, 1, 5) + timedelta(days=i) for i in range(10)]
    for d in days:
        session.add(
            PlContractDataDaily(
                date=d,
                contract_id=c.id,
                close=Decimal("4000"),
                high=Decimal("4010"),
                low=Decimal("3990"),
                volume=100,
                oi=1000,
            )
        )
        # Fan-out source: one pl_indicator_daily row per (version, language).
        for vid in vids:
            for lang in languages:
                session.add(
                    PlIndicatorDaily(
                        date=d,
                        contract_id=c.id,
                        algorithm_version_id=vid,
                        language=lang,
                        decision="OPEN",
                        conclusion="x",
                        macroeco_bonus=Decimal("0.05")
                        if (vid == vids[0] and lang == "fr")
                        else Decimal("0.03"),
                    )
                )
    session.flush()
    return c.id, vids


@pytest.mark.integration
def test_loader_unique_despite_multiple_versions_and_languages(
    sync_db_session: Session,
) -> None:
    """10 sessions × (2 versions × 2 languages) = 40 pl_indicator_daily rows, but
    the loader must return exactly 10 rows (one per date). Pre-fix: 40."""
    _setup(sync_db_session, versions=["legacy", "power10years"], languages=["fr", "en"])
    df = load_market_data(sync_db_session, "CAFO26")
    assert len(df) == 10
    assert df["date"].is_unique
    # macroeco is no longer joined in the loader (attached per-version later).
    assert "macroeco_bonus" not in df.columns


def test_assert_unique_dates_fires_on_duplicates() -> None:
    dup = pd.DataFrame(
        {
            "date": [date(2026, 1, 5), date(2026, 1, 5), date(2026, 1, 6)],
            "close": [1, 1, 2],
        }
    )
    with pytest.raises(RuntimeError, match="duplicate dates"):
        _assert_unique_dates(dup, "test-source")
    # A unique series passes silently.
    _assert_unique_dates(dup.drop_duplicates("date"), "test-source")


@pytest.mark.integration
def test_attach_version_macroeco_per_version_no_fanout(
    sync_db_session: Session,
) -> None:
    _, vids = _setup(
        sync_db_session, versions=["legacy", "power10years"], languages=["fr", "en"]
    )
    df = load_market_data(sync_db_session, "CAFO26")
    out = _attach_version_macroeco(sync_db_session, df, vids[0])
    assert len(out) == len(df)  # no fan-out
    assert out["date"].is_unique
    # This version's fr macroeco (0.05), not the other version's (0.03).
    assert float(out["macroeco_bonus"].iloc[0]) == pytest.approx(0.05)
