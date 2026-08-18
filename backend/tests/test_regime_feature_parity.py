"""Train/serve feature parity against the R&D canonical snapshot.

The regime pack ships `frozen/canonical_snapshot/reference_tail_120.parquet` —
120 reference rows carrying the exact 12 router features the specialists were fit
on — precisely so an integrator can prove its feature chain matches the one the
models learned. Regime SELF-COMPUTES its features from raw prices
(`build_selfcomputed_features`), so this is the only thing standing between a
silent feature drift and a year of plausible-but-wrong decisions.

These tests do two things:

1. Pin our chain against the snapshot on every row that is arithmetically sound.
2. Document — and hold — the three rows where the SNAPSHOT is the one that is
   wrong, so nobody "fixes" our chain to match a corrupted reference.

### The three bad reference rows (2026-07-17, 07-20, 07-21)

Established 2026-08-18 by recomputing MACD from scratch (plain `ewm` on the raw
chained closes, no project code). That independent recompute matches the snapshot
on 117/120 rows and matches OUR chain on all 120. On the three exceptions:

* the snapshot's `daily_return` implies previous closes of 3924.3 / 4088.1 /
  4100.1, which exist on **no contract** in the database (CAU26 closed 3978 /
  4096 / 4097; CAZ26 4030 / 4152 / 4161);
* its `macd` runs +293.8 → **-40.9 → -34.3 → -22.4** → +193.5 and then rejoins
  the correct path *exactly*. A recursive EMA cannot swing 335 points and return
  in three sessions — the values were spliced in, not computed in sequence.

The window ends the day before 2026-07-22, the date `pl_derived_indicators` was
corrected for the macroeco fan-out — the likely provenance, though only R&D can
confirm it. Consequence: the pack's integration check
`decide(2026-07-27) → P(up)=0.533` is **not reproducible by a correct
implementation**; a correct chain yields 0.5172. Decision, regime and specialist
all still match.
"""

from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path

import pandas as pd
import pytest

_SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "vendor"
    / "regime_v1.0.0"
    / "frozen"
    / "canonical_snapshot"
    / "reference_tail_120.parquet"
)

# The 12 features the router and the specialists consume (manifest
# `router_features`). trend20 / trend60 / vol20 are derived inside the vendor
# from `daily_return`, so our chain does not carry them — they are excluded here
# and covered transitively by daily_return.
_SELF_COMPUTED = (
    "macd",
    "macd_signal",
    "rsi_14d",
    "atr_14d",
    "stochastic_d_14",
    "close_pivot_ratio",
    "volume_oi_ratio",
    "daily_return",
    "bollinger_width",
)

# Rows where the SNAPSHOT is wrong — see the module docstring. Held as data so a
# future re-freeze that fixes them makes this list shrink, loudly.
KNOWN_BAD_REFERENCE_ROWS = (
    date_cls(2026, 7, 17),
    date_cls(2026, 7, 20),
    date_cls(2026, 7, 21),
)


@pytest.fixture(scope="module")
def snapshot() -> pd.DataFrame:
    if not _SNAPSHOT.exists():
        pytest.skip("R&D canonical snapshot not vendored")
    df = pd.read_parquet(_SNAPSHOT)
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_snapshot_is_the_120_row_reference_tail(snapshot: pd.DataFrame) -> None:
    """Guard the artifact itself: a re-freeze that changes its shape must be seen."""
    assert len(snapshot) == 120
    for col in _SELF_COMPUTED:
        assert col in snapshot.columns, col


def test_the_reference_macd_is_discontinuous_only_at_the_known_bad_window(
    snapshot: pd.DataFrame,
) -> None:
    """MACD is a difference of EMAs — it cannot teleport.

    Arbitrates the reference against itself, no price series and no project code
    needed. Across the 119 day-to-day steps the reference's own |Δ macd| has a
    median of 10 and a largest legitimate move of 43. Exactly two steps break
    that scale by an order of magnitude: **into** 2026-07-17 (335) and **out of**
    2026-07-21 into 07-22 (216) — the value leaves the smooth path and returns to
    it three sessions later, at precisely the value a continuous EMA would have
    reached. Values were spliced in; they were not computed in sequence.
    """
    df = snapshot.sort_values("date").reset_index(drop=True)
    jump = df["macd"].astype(float).diff().abs()

    # 100 sits far above every legitimate move (max 43) and far below the two
    # anomalies (216, 335) — the gap is 5x wide, so the bound is not tuned.
    teleports = {d.date() for d in df.loc[jump > 100.0, "date"]}
    expected = {KNOWN_BAD_REFERENCE_ROWS[0], date_cls(2026, 7, 22)}
    assert teleports == expected, (
        f"MACD discontinuities at {sorted(teleports)}, expected {sorted(expected)} "
        "— if this set shrank, the snapshot was re-frozen and "
        "KNOWN_BAD_REFERENCE_ROWS should shrink with it."
    )

    # And the rest of the series is smooth, which is what makes the two above
    # anomalies rather than a volatile market.
    clean = jump.dropna()
    clean = clean[clean <= 100.0]
    assert float(clean.max()) < 50.0, f"unexpected MACD volatility: {clean.max():.1f}"


def test_the_three_bad_rows_carry_a_return_no_contract_produced(
    snapshot: pd.DataFrame,
) -> None:
    """Pin the evidence, so the finding survives without re-deriving it.

    The snapshot's return on those dates implies a previous close that does not
    exist in the market data. Hardcoded from the audited values rather than
    recomputed from the DB: this is a statement about the artifact, and it must
    stay true whatever the database later holds.
    """
    implied = {
        date_cls(2026, 7, 17): (4096.0, 3978.0),  # (close, our chain's previous)
        date_cls(2026, 7, 20): (4097.0, 4096.0),
        date_cls(2026, 7, 21): (4173.0, 4097.0),
    }
    df = snapshot.set_index(snapshot["date"].dt.date)
    for day, (close, real_prev) in implied.items():
        ref_ret = float(df.loc[day, "daily_return"])
        ref_prev = close / (1.0 + ref_ret)
        assert abs(ref_prev - real_prev) > 1.0, (
            f"{day}: the snapshot's implied previous close {ref_prev:.1f} now "
            f"agrees with the market ({real_prev}) — the snapshot may have been "
            "re-frozen; drop this date from KNOWN_BAD_REFERENCE_ROWS."
        )


@pytest.mark.integration
def test_our_self_computed_chain_matches_the_reference(snapshot: pd.DataFrame) -> None:
    """The real parity gate: our features vs the ones the models were fit on.

    Opt-in, because it needs 120 real sessions of price history that no fixture
    is going to seed and that the isolated test DB does not hold. Point it at the
    synced dev database to run it:

        REGIME_PARITY_DB_URL=postgresql+psycopg2://postgres:password@localhost:5433/commodities_compass \
            poetry run pytest tests/test_regime_feature_parity.py

    Skips otherwise, which is the CI path.

    Tolerance is 1e-6: this must be an exact match, not a close one. The
    specialists are gradient-boosted trees whose splits sit on precise
    thresholds, so a 0.01 drift can flip a leaf and therefore a decision.
    """
    import os

    import numpy as np
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SyncSession

    from scripts.regime_shadow.feature_engine import build_selfcomputed_features

    url = os.environ.get("REGIME_PARITY_DB_URL")
    if not url:
        pytest.skip("set REGIME_PARITY_DB_URL to run the parity gate (see docstring)")

    engine = create_engine(url)
    with SyncSession(engine) as session:
        ours = build_selfcomputed_features(session)

    ours["date"] = pd.to_datetime(ours["date"])
    merged = snapshot.merge(ours, on="date", how="inner", suffixes=("_ref", "_our"))
    if len(merged) < 100:
        pytest.skip(
            f"only {len(merged)}/120 snapshot dates present locally — needs a synced DB"
        )

    good = merged[~merged["date"].dt.date.isin(KNOWN_BAD_REFERENCE_ROWS)]
    for col in _SELF_COMPUTED:
        a = np.asarray(good[f"{col}_ref"], dtype=float)
        b = np.asarray(good[f"{col}_our"], dtype=float)
        worst = float(np.abs(a - b).max())
        assert worst < 1e-6, (
            f"{col}: our self-computed chain drifted from the frozen reference "
            f"by up to {worst:.6f} over {len(good)} rows. The specialists were "
            f"fit on the reference — a drift here silently changes decisions."
        )
