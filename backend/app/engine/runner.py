"""CLI entry point for the indicator computation engine.

Usage:
    # Incremental (default) — compute full history, write only new rows
    poetry run compute-indicators --all-contracts
    poetry run compute-indicators --all-contracts --dry-run

    # All compute-enabled versions (nightly cron mode)
    poetry run compute-indicators --all-contracts --all-versions

    # Full rewrite — recompute and overwrite all rows (for version switches, backfills)
    poetry run compute-indicators --all-contracts --full

    # Specific version
    poetry run compute-indicators --all-contracts --algorithm legacy --algorithm-version 1.0.1

    # Single contract
    poetry run compute-indicators --contract CAK26 [--dry-run] [--window 252]

Reads from pl_contract_data_daily, computes all indicators, and writes to
pl_derived_indicators + pl_indicator_daily + pl_signal_component.

--all-versions: Queries pl_algorithm_version WHERE compute_enabled=True and
runs the pipeline once per version. Market data is loaded once and shared.
Adding a new algorithm version is a DB INSERT, not a code deploy.

Incremental mode (default): Computes on the full price series (required for
recursive indicators like EMA/RSI/ATR), but only writes rows with dates
after the last existing date in pl_derived_indicators. Safe for nightly crons.

Full mode (--full): Upserts all rows. Use for algorithm version switches,
historical backfills, or when you need to overwrite existing data.

--all-contracts mode: Loads the full price history across all contracts
as one continuous series (matching how the Sheets engine worked), computes
indicators on the full series, then writes results tagged to each row's
original contract_id.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.sentry import init_sentry
from app.engine.db_writer import write_pipeline_results
from app.engine.pipeline import IndicatorPipeline
from app.engine.types import AlgorithmConfig, AlgorithmConfigMissingError

logger = logging.getLogger(__name__)


def load_algorithm_config(
    session: Session, version_name: str, version: str | None = None
) -> AlgorithmConfig:
    """Load algorithm config from DB. Fail-loud when absent or incompatible."""
    if version:
        result = session.execute(
            text("""
                SELECT ac.parameter_name, ac.value
                FROM v_algorithm_config_current ac
                JOIN pl_algorithm_version av ON ac.algorithm_version_id = av.id
                WHERE av.name = :name AND av.version = :version
                ORDER BY ac.parameter_name
            """),
            {"name": version_name, "version": version},
        )
    else:
        result = session.execute(
            text("""
                SELECT ac.parameter_name, ac.value
                FROM v_algorithm_config_current ac
                JOIN pl_algorithm_version av ON ac.algorithm_version_id = av.id
                WHERE av.name = :name AND av.is_active = true
                ORDER BY ac.parameter_name
            """),
            {"name": version_name},
        )
    params = {row[0]: row[1] for row in result}
    if not params:
        # Fail loud. The old behaviour returned the hardcoded LEGACY_V1, which
        # meant an ML/LLM version reaching here silently produced power-formula
        # decisions written under ITS version id (pipeline-error-handling.md:
        # a producer never degrades). LEGACY_V1 remains available as a fixture
        # for tests, never as a production fallback.
        raise AlgorithmConfigMissingError(
            f"No active config rows in v_algorithm_config_current for "
            f"'{version_name}' version={version or 'active'}. Refusing to fall "
            f"back to LEGACY_V1 — that would store power-formula decisions "
            f"under this version id."
        )
    label = f"{version_name}_v{version}" if version else version_name
    return AlgorithmConfig.from_db_rows(label, params)


def load_algorithm_version_id(
    session: Session, version_name: str, version: str | None = None
) -> uuid.UUID | None:
    """Load the algorithm version UUID from DB."""
    if version:
        result = session.execute(
            text(
                "SELECT id FROM pl_algorithm_version WHERE name = :name AND version = :version"
            ),
            {"name": version_name, "version": version},
        )
    else:
        result = session.execute(
            text(
                "SELECT id FROM pl_algorithm_version WHERE name = :name AND is_active = true"
            ),
            {"name": version_name},
        )
    row = result.fetchone()
    return row[0] if row else None


def load_compute_enabled_versions(
    session: Session,
) -> list[tuple[uuid.UUID, str, str]]:
    """Power-formula versions this engine must compute.

    Filters on ``algorithm_kind`` as well as ``compute_enabled``. The kind is
    the structural guard: this engine only knows how to evaluate the power
    formula, so an ML or LLM version flagged ``compute_enabled`` is simply not
    returned instead of crashing the nightly job (missing coefficients) or —
    when it has no config rows at all — silently writing power-formula
    decisions under its version id.

    Returns list of (id, name, version) tuples.
    """
    result = session.execute(
        text(
            "SELECT id, name, version FROM pl_algorithm_version "
            "WHERE compute_enabled = true AND algorithm_kind = 'power_formula' "
            "ORDER BY name, version"
        )
    )
    return [(row[0], row[1], row[2]) for row in result]


def load_contract_id(session: Session, contract_code: str) -> uuid.UUID | None:
    """Load the contract UUID from ref_contract."""
    result = session.execute(
        text("SELECT id FROM ref_contract WHERE code = :code"),
        {"code": contract_code},
    )
    row = result.fetchone()
    return row[0] if row else None


def _convert_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert Decimal columns to float/int for computation."""
    result = df.copy()
    for col in [
        "close",
        "high",
        "low",
        "implied_volatility",
        "macroeco_bonus",
    ]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    for col in ["volume", "oi"]:
        if col in result.columns:
            result[col] = pd.Series(pd.to_numeric(result[col], errors="coerce")).astype(
                "Int64"
            )
    return result


def _assert_unique_dates(df: pd.DataFrame, source: str) -> None:
    """Fail loud if the market series has duplicate dates.

    Rolling/recursive indicators (EMA, RSI/ATR Wilder, 252d z-scores) are
    positional — a duplicated date silently corrupts every downstream value.
    A fan-out here (e.g. a LEFT JOIN over the pl_indicator_daily
    version/language dimensions) is exactly how pl_derived_indicators got
    corrupted historically; this turns any recurrence into an immediate crash
    instead of silent bad data. See .claude/rules/timeseries-uniqueness.md.
    """
    if df.empty:
        return
    if not df["date"].is_unique:
        dups = list(df.loc[df["date"].duplicated(keep=False), "date"].unique()[:5])
        raise RuntimeError(
            f"{source} returned duplicate dates ({dups}...) — the market series "
            "must have exactly one row per date. A fan-out has re-appeared; "
            "computing indicators over a duplicated series corrupts them."
        )


def mark_roll_boundaries(
    df: pd.DataFrame, code_col: str = "contract_code"
) -> pd.DataFrame:
    """Flag the first row of each new front-month contract in the chained series.

    A roll boundary is a row whose front-month contract differs from the previous
    row's. There the continuous series splices contract A's close (T-1) to contract
    B's (T) — a phantom price jump equal to the calendar spread, with no back-adjust.
    Return-based indicators (DailyReturn / WilderRSI / TrueRange) neutralize the
    cross-boundary change on these rows so the phantom jump never enters RSI/ATR/
    daily_return (nor, downstream, their 252d z-scores). The flag is also persisted
    so R&D can exclude roll rows from training and the ensemble wrapper can stay
    cautious near rolls. The first row is never a boundary (series start, no
    cross-contract predecessor). See .claude/rules/timeseries-uniqueness.md and the
    C5 retrain handoff runbook §3.7.
    """
    result = df.copy()
    if result.empty or code_col not in result.columns:
        result["is_roll_boundary"] = pd.Series(
            [False] * len(result), dtype=bool, index=result.index
        )
        return result
    changed = result[code_col].ne(result[code_col].shift())
    boundary = changed.to_numpy(dtype=bool)
    boundary[0] = False  # series start, not a roll
    result["is_roll_boundary"] = boundary
    return result


def _attach_version_macroeco(
    session: Session, df: pd.DataFrame, algo_version_id: uuid.UUID
) -> pd.DataFrame:
    """Merge THIS version's macroeco_bonus (fr) onto the market series.

    Kept OUT of the market loaders on purpose: the loaders must return a
    fan-out-proof one-row-per-date OHLCV series, but macroeco_bonus lives in
    pl_indicator_daily keyed on (date, contract_id, algo_version, language) —
    joining it in the loader fans the series out (the historical corruption).
    Here we join exactly one row per (date, contract) for the version being
    computed, so each version's composite uses its own macroeco and the series
    stays unique. macroeco only feeds the final composite, never the
    derived/z-score layers.
    """
    rows = session.execute(
        text(
            """
            SELECT date, contract_id, macroeco_bonus
            FROM pl_indicator_daily
            WHERE algorithm_version_id = :vid
              AND language = 'fr'
              AND macroeco_bonus IS NOT NULL
            """
        ),
        {"vid": algo_version_id},
    ).fetchall()
    if not rows:
        out = df.copy()
        out["macroeco_bonus"] = pd.NA
        return _convert_numeric_columns(out)
    macro = pd.DataFrame(
        rows, columns=pd.Index(["date", "contract_id", "macroeco_bonus"])
    )
    out = df.merge(macro, on=["date", "contract_id"], how="left")
    _assert_unique_dates(out, "_attach_version_macroeco")
    return _convert_numeric_columns(out)


def load_market_data(session: Session, contract_code: str) -> pd.DataFrame:
    """Load raw market data for a single contract."""
    result = session.execute(
        text("""
            SELECT
                d.date, d.close, d.high, d.low, d.volume, d.oi,
                d.implied_volatility,
                d.contract_id
            FROM pl_contract_data_daily d
            JOIN ref_contract c ON d.contract_id = c.id
            WHERE c.code = :code
            ORDER BY d.date ASC
        """),
        {"code": contract_code},
    )
    rows = result.fetchall()
    if not rows:
        logger.error("No market data found for contract %s", contract_code)
        return pd.DataFrame()

    columns = [
        "date",
        "close",
        "high",
        "low",
        "volume",
        "oi",
        "implied_volatility",
        "contract_id",
    ]
    df = _convert_numeric_columns(pd.DataFrame(rows, columns=pd.Index(columns)))
    _assert_unique_dates(df, "load_market_data")
    return df


def load_all_market_data(session: Session) -> pd.DataFrame:
    """Load full price history across all contracts as one continuous series.

    Reads the front-month per date from ``v_contract_data_chained``, the single
    canonical resolver — the front-month is the contract with the greatest
    ``ref_contract.active_from`` <= that date (the operator's roll calendar, seeded
    from the real decision history, maintained by ``roll-contract``). There is no
    oi/volume heuristic here anymore: the calendar is the only source of truth, so
    compute-indicators, the ensemble market_history loader, daily-analysis and the
    dashboard can never disagree on the front-month (that disagreement was the
    recurring split-brain — see docs/user-stories/P1-contract-roll-canonical-frontmonth.md).

    Each row retains its original contract_id for per-contract DB writes.
    """
    result = session.execute(
        text("""
            WITH market AS (
                -- front-month per date from the canonical roll calendar;
                -- v_contract_data_chained now resolves via ref_contract.active_from
                SELECT v.date, v.close, v.high, v.low, v.volume, v.oi,
                       v.implied_volatility,
                       v.contract_id,
                       c.code AS contract_code
                FROM v_contract_data_chained v
                JOIN ref_contract c ON c.id = v.contract_id
            )
            SELECT
                m.date, m.close, m.high, m.low, m.volume, m.oi,
                m.implied_volatility,
                m.contract_id, m.contract_code
            FROM market m
            ORDER BY m.date ASC
        """),
    )
    rows = result.fetchall()
    if not rows:
        logger.error("No market data found in pl_contract_data_daily")
        return pd.DataFrame()

    columns = [
        "date",
        "close",
        "high",
        "low",
        "volume",
        "oi",
        "implied_volatility",
        "contract_id",
        "contract_code",
    ]
    df = _convert_numeric_columns(pd.DataFrame(rows, columns=pd.Index(columns)))
    # NB: roll-boundary marking is intentionally NOT applied in the shared compute
    # path — cc-compute-indicators (and therefore the ensemble/legacy that read
    # pl_derived_indicators) stays byte-for-byte as prod. The regime shadow job does
    # its own marking in scripts/regime_shadow/feature_engine.py. Re-enabling it here
    # (with a prod recompute) is a deliberate step for the C5 retrain track.
    _assert_unique_dates(df, "load_all_market_data")
    return df


def _get_last_computed_date(
    session: Session, algo_version_id: uuid.UUID
) -> pd.Timestamp | None:
    """Get the last date with computed indicators for a given algorithm version."""
    result = session.execute(
        text("""
            SELECT MAX(date) FROM pl_indicator_daily
            WHERE algorithm_version_id = :vid
        """),
        {"vid": algo_version_id},
    )
    row = result.fetchone()
    if row and row[0]:
        return pd.Timestamp(row[0])  # type: ignore[return-value]
    return None


def _filter_new_rows(
    signals: pd.DataFrame, last_date: pd.Timestamp | None
) -> pd.DataFrame:
    """Filter signals to only rows after last_date."""
    if last_date is None:
        return signals
    cutoff = last_date.date() if hasattr(last_date, "date") else last_date
    result: pd.DataFrame = signals.loc[signals["date"] > cutoff].copy()  # type: ignore[assignment]
    return result


def _print_summary(signals: pd.DataFrame) -> None:
    """Log decision distribution and score stats."""
    valid_decisions = signals["decision"].value_counts()
    logger.info("Decisions: %s", dict(valid_decisions))

    final = signals["final_indicator"].dropna()
    if len(final) > 0:
        logger.info(
            "Score stats: min=%.3f, max=%.3f, mean=%.3f, median=%.3f",
            final.min(),
            final.max(),
            final.mean(),
            final.median(),
        )


def _print_tail(signals: pd.DataFrame, n: int = 5) -> None:
    """Log the last N rows."""
    cols = ["date", "final_indicator", "decision"]
    if "contract_code" in signals.columns:
        cols = ["date", "contract_code", "final_indicator", "decision"]
    tail = signals[cols].tail(n)
    for _, row in tail.iterrows():
        score = (
            f"{row['final_indicator']:.3f}"
            if bool(pd.notna(row["final_indicator"]))
            else "N/A"
        )
        contract = f"  [{row['contract_code']}]" if "contract_code" in row.index else ""
        logger.info(
            "  %s%s  score=%s  decision=%s",
            row["date"],
            contract,
            score,
            row["decision"],
        )


def _write_results_per_contract(
    session: Session,
    signals: pd.DataFrame,
    algo_version_id: uuid.UUID,
    config: AlgorithmConfig,
    *,
    derived_only: bool = False,
) -> dict[str, int]:
    """Write results grouped by contract_id, using savepoints.

    Each contract's writes are wrapped in a SAVEPOINT so that a failure
    in contract N+1 doesn't leave contract N permanently committed while
    contract N+1 has partial deletes. All contracts commit atomically.

    ``derived_only`` writes only pl_derived_indicators (leaves decisions/scores frozen).
    """
    totals: dict[str, int] = {
        "pl_derived_indicators": 0,
        "pl_indicator_daily": 0,
        "pl_signal_component": 0,
    }

    grouped = signals.groupby("contract_id")
    for contract_id, group_df in grouped:
        contract_code = (
            group_df["contract_code"].iloc[0]
            if "contract_code" in group_df.columns
            else str(contract_id)
        )
        logger.info("Writing %d rows for %s", len(group_df), contract_code)

        with session.begin_nested():  # SAVEPOINT per contract
            counts = write_pipeline_results(
                session=session,
                signals_df=group_df,
                contract_id=uuid.UUID(str(contract_id)),
                algorithm_version_id=algo_version_id,
                config=config,
                commit=False,
                derived_only=derived_only,
            )
        for key in totals:
            totals[key] += counts[key]

    session.commit()
    logger.info("Committed all contract writes atomically")
    return totals


def _run_for_version(
    session: Session,
    df: pd.DataFrame,
    algo_version_id: uuid.UUID,
    algo_name: str,
    algo_version: str,
    args: argparse.Namespace,
) -> None:
    """Compute and write indicators for a single algorithm version."""
    logger.info("=== Processing algorithm: %s v%s ===", algo_name, algo_version)
    config = load_algorithm_config(session, algo_name, algo_version)

    pipeline = IndicatorPipeline(config=config, normalization_window=args.window)
    # Attach THIS version's macroeco_bonus here (not in the loader) so the market
    # series stays fan-out-proof — one row per date. macroeco only feeds the final
    # composite, never the derived/z-score layers.
    df_v = _attach_version_macroeco(session, df, algo_version_id)
    result = pipeline.run(df_v)
    signals = result.signals

    _print_summary(signals)

    # Incremental mode: filter to only new rows
    write_signals = signals
    if not args.full:
        last_date = _get_last_computed_date(session, algo_version_id)
        if last_date is not None:
            write_signals = _filter_new_rows(signals, last_date)
            logger.info(
                "Incremental mode: last computed date=%s, %d new rows to write",
                last_date.date(),
                len(write_signals),
            )
            if write_signals.empty:
                logger.info(
                    "%s v%s — already up to date, skipping",
                    algo_name,
                    algo_version,
                )
                return
        else:
            logger.info(
                "Incremental mode: no existing data, writing full history (%d rows)",
                len(write_signals),
            )
    else:
        logger.info("Full mode: writing all %d rows (upsert)", len(write_signals))

    if args.dry_run:
        logger.info("Dry run — skipping DB write")
        _print_tail(write_signals, n=10)
        return

    derived_only = getattr(args, "derived_only", False)
    if args.all_contracts:
        logger.info("Writing results to database (per contract)...")
        totals = _write_results_per_contract(
            session, write_signals, algo_version_id, config, derived_only=derived_only
        )
    else:
        contract_id = load_contract_id(session, args.contract)
        if contract_id is None:
            logger.error("Contract %s not found in ref_contract", args.contract)
            return

        logger.info("Writing results to database...")
        totals = write_pipeline_results(
            session=session,
            signals_df=write_signals,
            contract_id=contract_id,
            algorithm_version_id=algo_version_id,
            config=config,
            derived_only=derived_only,
        )

    logger.info(
        "Done (%s v%s): %d derived, %d indicator_daily, %d signal_components",
        algo_name,
        algo_version,
        totals["pl_derived_indicators"],
        totals["pl_indicator_daily"],
        totals["pl_signal_component"],
    )


def main() -> None:
    init_sentry("compute-indicators")
    parser = argparse.ArgumentParser(description="Compute indicators for a contract")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--contract", help="Contract code (e.g., CAK26)")
    group.add_argument(
        "--all-contracts",
        action="store_true",
        help="Run on full history across all contracts",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute but don't write to DB"
    )
    parser.add_argument(
        "--window",
        type=int,
        default=252,
        help="Normalization rolling window (default: 252)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full rewrite: upsert all rows (default: incremental, only new rows)",
    )
    parser.add_argument("--algorithm", default="legacy", help="Algorithm name")
    parser.add_argument(
        "--algorithm-version",
        default=None,
        help="Algorithm version (e.g., 1.0.0, 1.0.1)",
    )
    parser.add_argument(
        "--all-versions",
        action="store_true",
        help="Run on all algorithm versions with compute_enabled=True",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even on non-trading days (for backfills/debugging)",
    )
    parser.add_argument(
        "--derived-only",
        action="store_true",
        help=(
            "Write ONLY pl_derived_indicators (correct the raw technical indicators the "
            "dashboard never reads), leaving pl_indicator_daily + pl_signal_component "
            "frozen. Use to fix corrupted lookback inputs without restating historical "
            "decisions/scores/gauges. Pair with --full."
        ),
    )
    args = parser.parse_args()

    if args.all_versions and args.algorithm_version:
        logger.error("--all-versions and --algorithm-version are mutually exclusive")
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    # Skip on non-trading days unless --force
    from scripts.db import should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return

    db_url = str(settings.DATABASE_SYNC_URL)
    engine = create_engine(db_url)

    with Session(engine) as session:
        # Load market data once (shared across all versions — derived indicators
        # are version-agnostic, only the power formula differs)
        if args.all_contracts:
            logger.info("Loading full market data across all contracts")
            df = load_all_market_data(session)
        else:
            logger.info("Loading market data for %s", args.contract)
            df = load_market_data(session, args.contract)

        if df.empty:
            sys.exit(1)

        logger.info(
            "Loaded %d rows (%s to %s)", len(df), df["date"].min(), df["date"].max()
        )

        if args.all_contracts:
            contracts = df.groupby("contract_code").size()
            for code, count in contracts.items():
                logger.info("  %s: %d rows", code, count)

        # Resolve which versions to run
        if args.all_versions:
            versions = load_compute_enabled_versions(session)
            if not versions:
                logger.error("No algorithm versions with compute_enabled=True found")
                sys.exit(1)
            logger.info(
                "Running %d compute-enabled versions: %s",
                len(versions),
                ", ".join(f"{n} v{v}" for _, n, v in versions),
            )
        else:
            algo_version_id = load_algorithm_version_id(
                session, args.algorithm, args.algorithm_version
            )
            if algo_version_id is None:
                logger.error(
                    "Algorithm version '%s' version=%s not found or not active",
                    args.algorithm,
                    args.algorithm_version or "active",
                )
                sys.exit(1)
            versions = [
                (algo_version_id, args.algorithm, args.algorithm_version or "active")
            ]

        for vid, name, ver in versions:
            _run_for_version(session, df, vid, name, ver, args)


if __name__ == "__main__":
    main()
