"""CLI entry point for the indicator computation engine.

Usage:
    poetry run compute-indicators --all-contracts [--dry-run]
    poetry run compute-indicators --all-contracts --algorithm legacy --algorithm-version 1.1.0
    poetry run compute-indicators --contract CAK26 [--dry-run] [--window 252]

Reads from pl_contract_data_daily, computes all indicators, and writes to
pl_derived_indicators + pl_indicator_daily + pl_signal_component.

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
from app.engine.db_writer import write_pipeline_results
from app.engine.pipeline import IndicatorPipeline
from app.engine.types import AlgorithmConfig, LEGACY_V1

logger = logging.getLogger(__name__)


def load_algorithm_config(
    session: Session, version_name: str, version: str | None = None
) -> AlgorithmConfig:
    """Load algorithm config from DB. Falls back to hardcoded LEGACY_V1."""
    if version:
        result = session.execute(
            text("""
                SELECT ac.parameter_name, ac.value
                FROM pl_algorithm_config ac
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
                FROM pl_algorithm_config ac
                JOIN pl_algorithm_version av ON ac.algorithm_version_id = av.id
                WHERE av.name = :name AND av.is_active = true
                ORDER BY ac.parameter_name
            """),
            {"name": version_name},
        )
    params = {row[0]: row[1] for row in result}
    if not params:
        logger.warning(
            "No active algorithm config found for '%s' version=%s, using hardcoded LEGACY_V1",
            version_name,
            version,
        )
        return LEGACY_V1
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
        "stock_us",
        "com_net_us",
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


def load_market_data(session: Session, contract_code: str) -> pd.DataFrame:
    """Load raw market data for a single contract."""
    result = session.execute(
        text("""
            SELECT
                d.date, d.close, d.high, d.low, d.volume, d.oi,
                d.implied_volatility, d.stock_us, d.com_net_us,
                d.contract_id,
                i.macroeco_bonus
            FROM pl_contract_data_daily d
            JOIN ref_contract c ON d.contract_id = c.id
            LEFT JOIN pl_indicator_daily i
                ON d.date = i.date AND d.contract_id = i.contract_id
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
        "stock_us",
        "com_net_us",
        "contract_id",
        "macroeco_bonus",
    ]
    return _convert_numeric_columns(pd.DataFrame(rows, columns=pd.Index(columns)))


def load_all_market_data(session: Session) -> pd.DataFrame:
    """Load full price history across all contracts as one continuous series.

    Sorted by date — the pipeline sees it as one price stream,
    but each row retains its original contract_id for DB writes.
    """
    result = session.execute(
        text("""
            SELECT
                d.date, d.close, d.high, d.low, d.volume, d.oi,
                d.implied_volatility, d.stock_us, d.com_net_us,
                d.contract_id,
                c.code as contract_code,
                i.macroeco_bonus
            FROM pl_contract_data_daily d
            JOIN ref_contract c ON d.contract_id = c.id
            LEFT JOIN pl_indicator_daily i
                ON d.date = i.date AND d.contract_id = i.contract_id
            ORDER BY d.date ASC
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
        "stock_us",
        "com_net_us",
        "contract_id",
        "contract_code",
        "macroeco_bonus",
    ]
    return _convert_numeric_columns(pd.DataFrame(rows, columns=pd.Index(columns)))


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
) -> dict[str, int]:
    """Write results grouped by contract_id. Returns total counts."""
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

        counts = write_pipeline_results(
            session=session,
            signals_df=group_df,
            contract_id=uuid.UUID(str(contract_id)),
            algorithm_version_id=algo_version_id,
            config=config,
        )
        for key in totals:
            totals[key] += counts[key]

    return totals


def main() -> None:
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
    parser.add_argument("--algorithm", default="legacy", help="Algorithm name")
    parser.add_argument(
        "--algorithm-version",
        default=None,
        help="Algorithm version (e.g., 1.0.0, 1.1.0)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    db_url = str(settings.DATABASE_SYNC_URL)
    engine = create_engine(db_url)

    with Session(engine) as session:
        logger.info(
            "Loading algorithm config: %s version=%s",
            args.algorithm,
            args.algorithm_version or "active",
        )
        config = load_algorithm_config(session, args.algorithm, args.algorithm_version)

        # Load data
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

        # Run pipeline on the full series
        pipeline = IndicatorPipeline(config=config, normalization_window=args.window)
        result = pipeline.run(df)
        signals = result.signals

        _print_summary(signals)

        if args.dry_run:
            logger.info("Dry run — skipping DB write")
            _print_tail(signals, n=10)
            return

        # Resolve algorithm version ID
        algo_version_id = load_algorithm_version_id(
            session, args.algorithm, args.algorithm_version
        )
        if algo_version_id is None:
            logger.error(
                "Algorithm version '%s' not found or not active", args.algorithm
            )
            sys.exit(1)

        if args.all_contracts:
            # Write results per contract (each row tagged with its contract_id)
            logger.info("Writing results to database (per contract)...")
            totals = _write_results_per_contract(
                session, signals, algo_version_id, config
            )
        else:
            # Single contract
            contract_id = load_contract_id(session, args.contract)
            if contract_id is None:
                logger.error("Contract %s not found in ref_contract", args.contract)
                sys.exit(1)

            logger.info("Writing results to database...")
            totals = write_pipeline_results(
                session=session,
                signals_df=signals,
                contract_id=contract_id,
                algorithm_version_id=algo_version_id,
                config=config,
            )

        logger.info(
            "Done: %d derived, %d indicator_daily, %d signal_components",
            totals["pl_derived_indicators"],
            totals["pl_indicator_daily"],
            totals["pl_signal_component"],
        )


if __name__ == "__main__":
    main()
