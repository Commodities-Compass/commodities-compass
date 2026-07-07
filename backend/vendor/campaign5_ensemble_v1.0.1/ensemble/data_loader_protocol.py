"""Protocol the production data layer implements to feed ``EnsemblePipeline``.

The R&D-side data loader (``methodology.data_loader``) reads from local Parquet
files and is **not** shipped to prod. The pipeline therefore depends only on
this Protocol — prod backs it with whatever it wants (SQLAlchemy session, raw
psycopg2, an in-process cache during job execution).

Five access methods, all returning plain DataFrames or simple dataclasses. The
column shapes match the canonical Parquet snapshot the freezer pinned in
``pl_model_artifact`` (artifact_kind='canonical_snapshot') — the ground truth.

CONTRACT (v1.0.1 §9.3/§9.4 — read before implementing prod's loader):

  FRONT-MONTH CHAINING (§9.4). ``market_history`` MUST be the front-month-by-OI
  *chained* series, NOT a single contract:
    - selection: per date, the contract with the highest open_interest (tiebreak:
      highest volume, then nearest expiry). This is prod's ``v_contract_data_chained``.
    - ``contract_id`` identifies the CHAIN, not one contract — lookback must span
      rolls without truncation (GARCH specialists need 500+ continuous rows; a
      single contract truncates to ~15 at a roll).
    - ``forward_return`` / the specialist target are defined on this chained
      ``close``. R&D trains on the same chained series; do not re-derive a
      different roll rule prod-side or train/score labels diverge on roll days.

  DTYPES (§9.3). Postgres NUMERIC / ``Decimal`` columns (OHLCV, IV, COT) MUST be
  coerced to float64 before the frame reaches the pipeline — specialists never
  see ``Decimal``. ``date`` is tz-naive ``datetime64[ns]``; vote/decision strings
  are exactly ``{"OPEN","HEDGE","MONITOR"}``.

  The required columns per method are enumerated in each method's docstring below;
  treat those lists as the binding contract (not advisory).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class MacroSignal:
    """Today's aggregated macro state. Output of ``MacroEventLayer.predict``."""

    direction: int          # {-1, 0, +1}; per MAC-002 only bear (-1) and neutral are amplified
    surprise: float         # [0, 1] — magnitude of surprise relative to baseline
    confidence: float       # [0, 1] — aggregator confidence
    half_life_days: int = 0  # v1.0.1 §9.9 — macro decay half-life {1,3,7}; 0 = no event (prod stops re-deriving the piecewise breaks)


@dataclass(frozen=True)
class DecideRequest:
    """Bundle of inputs ``EnsemblePipeline.decide`` consumes for one day.

    Why a single request object instead of N positional args:
        - keeps the public signature stable as new signals are added later
          (e.g., when C6 lights up COT EU);
        - makes it trivial to log a structured "what did the model see" record
          to ``pl_orchestrator_decision`` for audit.

    All fields are MANDATORY at call time. Day-1 callers pre-seed
    ``recent_decisions`` + ``recent_votes`` with R&D's historical
    ``wrapped_decisions.csv`` rows so the wrapper's running_acc detector has a
    valid trailing window (see deployment plan §6.2 bootstrap procedure).
    """

    today: pd.Timestamp
    contract_id: str
    # market_history rows must include `today`. Minimum length depends on the
    # specialist pool — at least ``trend_window`` (default 7) for the wrapper's
    # trend detector, and 500+ rows when GARCH-using specialists are active so
    # the GARCH residual feature can be computed without refitting on a stub.
    market_history: pd.DataFrame
    recent_decisions: pd.DataFrame    # prior wrapped decisions (see EnsembleDataLoader)
    recent_votes: pd.DataFrame        # prior per-specialist votes
    macro: MacroSignal


class EnsembleDataLoader(Protocol):
    """Methods prod implements to assemble a ``DecideRequest``.

    The pipeline does not call this Protocol directly — prod calls these
    helpers and packs the result into a ``DecideRequest``. The Protocol is
    documented here as the canonical interface; tests can ship a fake
    implementation backed by Parquet to exercise the pipeline end-to-end.
    """

    def load_market_history(
        self,
        end_date: pd.Timestamp,
        contract_id: str,
        lookback_days: int,
    ) -> pd.DataFrame:
        """Return rows of the canonical market panel for ``contract_id`` from
        ``end_date - lookback_days`` to ``end_date`` inclusive.

        Required columns: those produced by the canonical R&D snapshot's join
        of ``pl_contract_data_daily`` × ``pl_derived_indicators`` — at minimum
        ``date``, ``close``, ``open``, ``high``, ``low``, ``daily_return``,
        ``atr_14d``, ``ema_*``, ``rsi_14d``, ``macd*``, ``bollinger_*``,
        ``stochastic_*``, ``volume_oi_ratio``, ``close_pivot_ratio``.
        """
        ...

    def load_recent_orchestrator_decisions(
        self,
        end_date: pd.Timestamp,
        contract_id: str,
        lookback_days: int,
    ) -> pd.DataFrame:
        """Return up to ``lookback_days`` of prior rows from
        ``pl_orchestrator_decision`` for the active contract. Joins
        ``pl_indicator_daily`` (or equivalent forward-return source) to
        compute ``correct`` once the horizon has expired; for days where the
        horizon is still pending, ``correct`` may be NULL — the wrapper's
        running-acc detector treats NULL as a non-committed day and skips it.

        Required columns: ``date``, ``decision`` (original soft-gate decision),
        ``decision_wrapped`` (the wrapper output that was actually used),
        ``net_score``, ``macro_direction``, ``prior_open``, ``prior_hedge``,
        ``prior_monitor``, ``committed``, ``correct``.

        Day-1 bootstrap: on the first scheduled run, this returns 0 rows from
        prod. The caller MUST then pre-populate the table with 5 trailing rows
        from R&D's ``wrapped_decisions.csv`` before invoking the pipeline,
        otherwise the wrapper's running_acc detector cannot fire.
        """
        ...

    def load_recent_specialist_votes(
        self,
        end_date: pd.Timestamp,
        contract_id: str,
        lookback_days: int,
    ) -> pd.DataFrame:
        """Return per-specialist predictions from ``pl_specialist_prediction``
        for the trailing ``lookback_days`` (exclusive of ``end_date``).

        Required columns: ``date``, ``specialist_name``, ``pred``
        (one of "OPEN", "HEDGE", "MONITOR").
        """
        ...

    def load_macro_signal(self, today: pd.Timestamp) -> MacroSignal:
        """Aggregate today's ``pl_article_segment`` rows into a ``MacroSignal``.

        Implementations should call ``ensemble.macro_events.pipeline.MacroEventLayer``
        with the frozen weights loaded from ``pl_model_artifact``.
        """
        ...
