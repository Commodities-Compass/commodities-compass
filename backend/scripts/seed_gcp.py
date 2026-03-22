"""Clean-data-only migration from legacy Docker DB to GCP Cloud SQL.

Reads from a source database (local Docker :5433) and writes to a target
database (GCP via Cloud SQL Auth Proxy :5434). Only raw market inputs,
GPT-generated outputs, formula-derived raw scores, and algorithm config
are migrated. Normalized z-scores, composites, and derived indicators are
excluded — they will be recomputed by the new pipeline.

Usage:
    poetry run seed-gcp                          # Full seed (local → GCP)
    poetry run seed-gcp --dry-run                # Preview without writing
    poetry run seed-gcp --validate-only          # Verify row counts
    poetry run seed-gcp --target-url "postgresql+psycopg2://..."
    poetry run seed-gcp --source-url "postgresql+psycopg2://..."
"""

import argparse
import logging
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.indicator import Indicator
from app.models.market_research import MarketResearch
from app.models.pipeline import (
    PlAlgorithmConfig,
    PlAlgorithmVersion,
    PlContractDataDaily,
    PlDerivedIndicators,
    PlFundamentalArticle,
    PlIndicatorDaily,
    PlWeatherObservation,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from app.models.technicals import Technicals
from app.models.test_range import TestRange
from app.models.weather_data import WeatherData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — ICE Futures Europe London Cocoa #7
# ---------------------------------------------------------------------------

EXCHANGE_CODE = "IFEU"
EXCHANGE_NAME = "ICE Futures Europe"
EXCHANGE_TZ = "Europe/London"

COMMODITY_CODE = "CC"
COMMODITY_NAME = "London Cocoa #7"

# Delivery months: H=Mar, K=May, N=Jul, U=Sep, Z=Dec
# (code, month_label, approximate_expiry, active_from, active_to)
CONTRACTS = [
    ("CAU24", "2024-09", date(2024, 9, 16), date(2024, 7, 16), date(2024, 9, 16)),
    ("CAZ24", "2024-12", date(2024, 12, 16), date(2024, 9, 17), date(2024, 12, 16)),
    ("CAH25", "2025-03", date(2025, 3, 17), date(2024, 12, 17), date(2025, 3, 17)),
    ("CAK25", "2025-05", date(2025, 5, 15), date(2025, 3, 18), date(2025, 5, 15)),
    ("CAN25", "2025-07", date(2025, 7, 15), date(2025, 5, 16), date(2025, 7, 15)),
    ("CAU25", "2025-09", date(2025, 9, 15), date(2025, 7, 16), date(2025, 9, 15)),
    ("CAZ25", "2025-12", date(2025, 12, 15), date(2025, 9, 16), date(2025, 12, 15)),
    ("CAH26", "2026-03", date(2026, 3, 16), date(2025, 12, 16), date(2026, 2, 27)),
    ("CAK26", "2026-05", date(2026, 5, 15), date(2026, 3, 2), date(2026, 5, 15)),
    ("CAN26", "2026-07", date(2026, 7, 15), date(2026, 5, 16), date(2026, 7, 15)),
]

DEFAULT_SOURCE_URL = (
    "postgresql+psycopg2://postgres:password@localhost:5433/commodities_compass"
)
DEFAULT_TARGET_URL = (
    "postgresql+psycopg2://postgres:password@localhost:5434/commodities_compass"
)

# NEW CHAMPION production power formula params from CONFIG col G (19 params)
NEW_CHAMPION_ALGO_NAME = "new_champion"
NEW_CHAMPION_ALGO_VERSION = "1.0.0"
NEW_CHAMPION_PARAMS = {
    "k": "-1.2",
    "a": "-1.3",
    "b": "1.8",
    "c": "0.5",
    "d": "0.7",
    "e": "-2.5",
    "f": "1.0",
    "g": "1.204",
    "h": "0.5",
    "i": "-0.4",
    "j": "1.751",
    "l": "4.98",
    "m": "1.2",
    "n": "-1.3",
    "o": "0.515",
    "p": "-0.5",
    "q": "1.98",
    "open_threshold": "1.5",
    "hedge_threshold": "-1.5",
}

# Normalized/composite fields explicitly set to None on GCP
NORM_FIELDS = (
    "rsi_norm",
    "macd_norm",
    "stoch_k_norm",
    "atr_norm",
    "close_pivot_norm",
    "vol_oi_norm",
)
COMPOSITE_FIELDS = ("indicator_value", "momentum", "final_indicator")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ts_to_date(ts: datetime | None) -> date | None:
    """Convert a legacy TIMESTAMP to DATE, stripping time component."""
    if ts is None:
        return None
    return ts.date()


def map_date_to_contract(
    d: date, contract_lookup: list[tuple[date, date, uuid.UUID]]
) -> uuid.UUID | None:
    """Return contract_id for a given date based on active_from/active_to ranges."""
    for active_from, active_to, contract_id in contract_lookup:
        if active_from <= d <= active_to:
            return contract_id
    return None


def decimal_or_none(val: Decimal | int | float | None) -> Decimal | None:
    """Coerce a value to Decimal or None."""
    if val is None:
        return None
    return Decimal(str(val))


def build_contract_lookup(
    contract_ids: dict[str, uuid.UUID],
) -> list[tuple[date, date, uuid.UUID]]:
    """Build a sorted list of (active_from, active_to, contract_id) for date mapping."""
    lookup = []
    for code, _, _, active_from, active_to in CONTRACTS:
        if code in contract_ids:
            lookup.append((active_from, active_to, contract_ids[code]))
    return sorted(lookup, key=lambda x: x[0])


def seed_reference_data(session: Session) -> dict:
    """Insert exchange, commodity, and contracts. Returns lookup IDs."""
    exchange = session.execute(
        select(RefExchange).where(RefExchange.code == EXCHANGE_CODE)
    ).scalar_one_or_none()
    if exchange is None:
        exchange = RefExchange(
            code=EXCHANGE_CODE, name=EXCHANGE_NAME, timezone=EXCHANGE_TZ
        )
        session.add(exchange)
        session.flush()
        log.info("Created exchange: %s", EXCHANGE_CODE)
    else:
        log.info("Exchange already exists: %s", EXCHANGE_CODE)

    commodity = session.execute(
        select(RefCommodity).where(RefCommodity.code == COMMODITY_CODE)
    ).scalar_one_or_none()
    if commodity is None:
        commodity = RefCommodity(
            code=COMMODITY_CODE, name=COMMODITY_NAME, exchange_id=exchange.id
        )
        session.add(commodity)
        session.flush()
        log.info("Created commodity: %s", COMMODITY_CODE)
    else:
        log.info("Commodity already exists: %s", COMMODITY_CODE)

    contract_ids: dict[str, uuid.UUID] = {}
    for code, month, expiry, _, _ in CONTRACTS:
        contract = session.execute(
            select(RefContract).where(RefContract.code == code)
        ).scalar_one_or_none()
        if contract is None:
            contract = RefContract(
                commodity_id=commodity.id,
                code=code,
                contract_month=month,
                expiry_date=expiry,
                is_active=(code == "CAK26"),
            )
            session.add(contract)
            session.flush()
            log.info("Created contract: %s", code)
        else:
            log.info("Contract already exists: %s", code)
        contract_ids[code] = contract.id

    return {
        "exchange_id": exchange.id,
        "commodity_id": commodity.id,
        "contract_ids": contract_ids,
    }


# ---------------------------------------------------------------------------
# Seed steps
# ---------------------------------------------------------------------------


def seed_algorithm_new_champion(session: Session) -> uuid.UUID:
    """Insert NEW CHAMPION algorithm version and 19 config params."""
    algo = session.execute(
        select(PlAlgorithmVersion).where(
            PlAlgorithmVersion.name == NEW_CHAMPION_ALGO_NAME,
            PlAlgorithmVersion.version == NEW_CHAMPION_ALGO_VERSION,
        )
    ).scalar_one_or_none()

    if algo is None:
        algo = PlAlgorithmVersion(
            name=NEW_CHAMPION_ALGO_NAME,
            version=NEW_CHAMPION_ALGO_VERSION,
            horizon="short_term",
            is_active=True,
            description="NEW CHAMPION power formula params from CONFIG col G",
        )
        session.add(algo)
        session.flush()
        log.info(
            "Created algorithm: %s v%s",
            NEW_CHAMPION_ALGO_NAME,
            NEW_CHAMPION_ALGO_VERSION,
        )

        for param_name, value in NEW_CHAMPION_PARAMS.items():
            session.add(
                PlAlgorithmConfig(
                    algorithm_version_id=algo.id,
                    parameter_name=param_name,
                    value=value,
                )
            )
        session.flush()
        log.info("Inserted %d algorithm config params", len(NEW_CHAMPION_PARAMS))
    else:
        log.info(
            "Algorithm already exists: %s v%s",
            NEW_CHAMPION_ALGO_NAME,
            NEW_CHAMPION_ALGO_VERSION,
        )

    return algo.id


def migrate_raw_market_data(
    src: Session,
    tgt: Session,
    contract_lookup: list[tuple[date, date, uuid.UUID]],
) -> int:
    """Migrate technicals → pl_contract_data_daily (raw OHLCV only, no derived)."""
    existing = tgt.execute(
        select(func.count()).select_from(PlContractDataDaily)
    ).scalar()
    if existing and existing > 0:
        log.info("pl_contract_data_daily already has %d rows — skipping", existing)
        return existing

    technicals = (
        src.execute(select(Technicals).order_by(Technicals.timestamp, Technicals.id))
        .scalars()
        .all()
    )
    log.info("Read %d rows from legacy technicals", len(technicals))

    by_date: dict[date, Technicals] = {}
    for t in technicals:
        row_date = ts_to_date(t.timestamp)
        if row_date is not None:
            by_date[row_date] = t
    log.info("Deduplicated to %d unique dates", len(by_date))

    count = 0
    skipped = 0
    for t in by_date.values():
        row_date = ts_to_date(t.timestamp)
        if row_date is None:
            skipped += 1
            continue

        contract_id = map_date_to_contract(row_date, contract_lookup)
        if contract_id is None:
            log.warning("No contract found for date %s — skipping", row_date)
            skipped += 1
            continue

        tgt.add(
            PlContractDataDaily(
                date=row_date,
                contract_id=contract_id,
                open=None,
                high=decimal_or_none(t.high),
                low=decimal_or_none(t.low),
                close=decimal_or_none(t.close),
                volume=t.volume,
                oi=t.open_interest,
                implied_volatility=decimal_or_none(t.implied_volatility),
                stock_us=decimal_or_none(t.stock_us),
                com_net_us=decimal_or_none(t.com_net_us),
            )
        )
        count += 1

    tgt.flush()
    log.info("Migrated raw market data: %d rows (%d skipped)", count, skipped)
    return count


def migrate_ai_outputs(
    src: Session,
    tgt: Session,
    contract_lookup: list[tuple[date, date, uuid.UUID]],
    algorithm_version_id: uuid.UUID,
) -> int:
    """Migrate indicator + technicals → pl_indicator_daily.

    Joins both legacy tables by date:
    - indicator: macroeco_bonus, eco, raw scores, macroeco_score
    - technicals: decision, confidence, direction, score (GPT Call #2)
    - Fallback: indicator.conclusion for decision when technicals.decision is NULL
    - Normalized/composite fields explicitly set to None.
    """
    existing = tgt.execute(select(func.count()).select_from(PlIndicatorDaily)).scalar()
    if existing and existing > 0:
        log.info("pl_indicator_daily already has %d rows — skipping", existing)
        return existing

    # Read and dedup indicators by date
    indicators = (
        src.execute(select(Indicator).order_by(Indicator.date, Indicator.id))
        .scalars()
        .all()
    )
    ind_by_date: dict[date, Indicator] = {}
    for ind in indicators:
        row_date = ts_to_date(ind.date)
        if row_date is not None:
            ind_by_date[row_date] = ind
    log.info(
        "Read %d indicator rows, deduplicated to %d",
        len(indicators),
        len(ind_by_date),
    )

    # Read and dedup technicals by date (for GPT Call #2 fields)
    technicals = (
        src.execute(select(Technicals).order_by(Technicals.timestamp, Technicals.id))
        .scalars()
        .all()
    )
    tech_by_date: dict[date, Technicals] = {}
    for t in technicals:
        row_date = ts_to_date(t.timestamp)
        if row_date is not None:
            tech_by_date[row_date] = t

    count = 0
    skipped = 0
    for row_date, ind in ind_by_date.items():
        contract_id = map_date_to_contract(row_date, contract_lookup)
        if contract_id is None:
            log.warning("No contract for indicator date %s — skipping", row_date)
            skipped += 1
            continue

        tech = tech_by_date.get(row_date)

        # Decision: prefer technicals.decision (GPT), fallback to indicator.conclusion
        decision = None
        if tech and tech.decision:
            decision = tech.decision
        elif ind.conclusion is not None:
            decision = str(ind.conclusion)

        # Confidence, direction, score from technicals (GPT Call #2)
        confidence = decimal_or_none(tech.confidence) if tech else None
        direction = tech.direction if tech else None
        composite_score = tech.score if tech else None

        tgt.add(
            PlIndicatorDaily(
                date=row_date,
                contract_id=contract_id,
                algorithm_version_id=algorithm_version_id,
                # Raw scores (preserved — lossy to drop)
                rsi_score=decimal_or_none(ind.rsi_score),
                macd_score=decimal_or_none(ind.macd_score),
                stochastic_score=decimal_or_none(ind.stochastic_score),
                atr_score=decimal_or_none(ind.atr_score),
                close_pivot=decimal_or_none(ind.close_pivot),
                volume_oi=decimal_or_none(ind.volume_oi),
                # Normalized z-scores → None (recomputed by new pipeline)
                rsi_norm=None,
                macd_norm=None,
                stoch_k_norm=None,
                atr_norm=None,
                close_pivot_norm=None,
                vol_oi_norm=None,
                # Composites → None (depend on norms)
                indicator_value=None,
                momentum=None,
                final_indicator=None,
                # GPT outputs (preserved — irreproducible)
                macroeco_bonus=decimal_or_none(ind.macroeco_bonus),
                macroeco_score=decimal_or_none(ind.macroeco_score),
                eco=ind.eco,
                # Decision fields (joined from technicals + indicator)
                decision=decision,
                confidence=confidence,
                direction=direction,
                composite_score=composite_score,
            )
        )
        count += 1

    tgt.flush()
    log.info("Migrated AI outputs: %d rows (%d skipped)", count, skipped)
    return count


def migrate_market_research(src: Session, tgt: Session) -> int:
    """Migrate market_research → pl_fundamental_article."""
    existing = tgt.execute(
        select(func.count()).select_from(PlFundamentalArticle)
    ).scalar()
    if existing and existing > 0:
        log.info("pl_fundamental_article already has %d rows — skipping", existing)
        return existing

    articles = (
        src.execute(select(MarketResearch).order_by(MarketResearch.date))
        .scalars()
        .all()
    )
    log.info("Read %d rows from legacy market_research", len(articles))

    count = 0
    for art in articles:
        row_date = ts_to_date(art.date)
        if row_date is None:
            continue

        tgt.add(
            PlFundamentalArticle(
                date=row_date,
                category="macro",
                source=art.author,
                title=None,
                summary=art.summary,
                keywords=art.keywords,
                sentiment=None,
                impact_synthesis=art.impact_synthesis,
                llm_provider="unknown",
            )
        )
        count += 1

    tgt.flush()
    log.info("Migrated market_research: %d rows", count)
    return count


def migrate_weather(src: Session, tgt: Session) -> int:
    """Migrate weather_data → pl_weather_observation."""
    existing = tgt.execute(
        select(func.count()).select_from(PlWeatherObservation)
    ).scalar()
    if existing and existing > 0:
        log.info("pl_weather_observation already has %d rows — skipping", existing)
        return existing

    weather_rows = (
        src.execute(select(WeatherData).order_by(WeatherData.date)).scalars().all()
    )
    log.info("Read %d rows from legacy weather_data", len(weather_rows))

    count = 0
    for w in weather_rows:
        row_date = ts_to_date(w.date)
        if row_date is None:
            continue

        tgt.add(
            PlWeatherObservation(
                date=row_date,
                region=None,
                observation=w.text,
                summary=w.summary,
                keywords=w.keywords,
                impact_assessment=w.impact_synthesis,
            )
        )
        count += 1

    tgt.flush()
    log.info("Migrated weather_data: %d rows", count)
    return count


def migrate_test_range(src: Session, tgt: Session) -> int:
    """Copy test_range rows verbatim (gauge color zones)."""
    existing = tgt.execute(select(func.count()).select_from(TestRange)).scalar()
    if existing and existing > 0:
        log.info("test_range already has %d rows — skipping", existing)
        return existing

    rows = src.execute(select(TestRange)).scalars().all()
    log.info("Read %d rows from legacy test_range", len(rows))

    count = 0
    for r in rows:
        tgt.add(
            TestRange(
                indicator=r.indicator,
                range_low=r.range_low,
                range_high=r.range_high,
                area=r.area,
            )
        )
        count += 1

    tgt.flush()
    log.info("Migrated test_range: %d rows", count)
    return count


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_clean(src: Session, tgt: Session) -> bool:
    """Validate the clean migration with dynamic row counts and leak checks."""
    passed = True

    # --- Row count checks (dynamic: source unique dates == target count) ---
    deduped_checks: list[tuple[str, type, str, type, str]] = [
        (
            "technicals→contract_data",
            Technicals,
            "timestamp",
            PlContractDataDaily,
            "date",
        ),
        ("indicator→indicator_daily", Indicator, "date", PlIndicatorDaily, "date"),
    ]
    for name, src_model, src_col, tgt_model, tgt_col in deduped_checks:
        src_attr = getattr(src_model, src_col)
        expected = (
            src.execute(select(func.count(func.distinct(src_attr)))).scalar() or 0
        )
        actual = tgt.execute(select(func.count()).select_from(tgt_model)).scalar() or 0

        src_min = src.execute(select(func.min(src_attr))).scalar()
        src_max = src.execute(select(func.max(src_attr))).scalar()
        tgt_attr = getattr(tgt_model, tgt_col)
        tgt_min = tgt.execute(select(func.min(tgt_attr))).scalar()
        tgt_max = tgt.execute(select(func.max(tgt_attr))).scalar()

        src_min_d = ts_to_date(src_min) if isinstance(src_min, datetime) else src_min
        src_max_d = ts_to_date(src_max) if isinstance(src_max, datetime) else src_max

        count_ok = actual == expected
        date_ok = src_min_d == tgt_min and src_max_d == tgt_max

        log.info(
            "%-35s expected=%d actual=%d [%s]  dates: %s→%s vs %s→%s [%s]",
            name,
            expected,
            actual,
            "OK" if count_ok else "MISMATCH",
            src_min_d,
            src_max_d,
            tgt_min,
            tgt_max,
            "OK" if date_ok else "MISMATCH",
        )
        if not count_ok or not date_ok:
            passed = False

    # --- Simple count checks (no dedup) ---
    simple_checks: list[tuple[str, type, type]] = [
        ("market_research→articles", MarketResearch, PlFundamentalArticle),
        ("weather→observations", WeatherData, PlWeatherObservation),
        ("test_range", TestRange, TestRange),
    ]
    for name, src_model, tgt_model in simple_checks:
        expected = (
            src.execute(select(func.count()).select_from(src_model)).scalar() or 0
        )
        actual = tgt.execute(select(func.count()).select_from(tgt_model)).scalar() or 0

        # For test_range src==tgt, so compare directly
        if src_model is tgt_model:
            log.info("%-35s count=%d [OK]", name, actual)
            continue

        ok = actual == expected
        log.info(
            "%-35s expected=%d actual=%d [%s]",
            name,
            expected,
            actual,
            "OK" if ok else "MISMATCH",
        )
        if not ok:
            passed = False

    # --- Emptiness check: pl_derived_indicators must have 0 rows ---
    di_count = (
        tgt.execute(select(func.count()).select_from(PlDerivedIndicators)).scalar() or 0
    )
    di_ok = di_count == 0
    log.info(
        "%-35s count=%d [%s]",
        "pl_derived_indicators (must be 0)",
        di_count,
        "OK" if di_ok else "CONTAMINATED",
    )
    if not di_ok:
        passed = False

    # --- Leak check: normalized fields must all be NULL ---
    indicator_count = (
        tgt.execute(select(func.count()).select_from(PlIndicatorDaily)).scalar() or 0
    )
    if indicator_count > 0:
        for field in NORM_FIELDS + COMPOSITE_FIELDS:
            col = getattr(PlIndicatorDaily, field)
            non_null = (
                tgt.execute(
                    select(func.count())
                    .select_from(PlIndicatorDaily)
                    .where(col.isnot(None))
                ).scalar()
                or 0
            )
            field_ok = non_null == 0
            log.info(
                "%-35s non_null=%d [%s]",
                f"leak_check: {field}",
                non_null,
                "OK" if field_ok else "LEAKED",
            )
            if not field_ok:
                passed = False

    # --- Raw scores must NOT all be NULL (sanity check) ---
    raw_score_fields = ("rsi_score", "macd_score", "close_pivot", "volume_oi")
    for field in raw_score_fields:
        col = getattr(PlIndicatorDaily, field)
        non_null = (
            tgt.execute(
                select(func.count())
                .select_from(PlIndicatorDaily)
                .where(col.isnot(None))
            ).scalar()
            or 0
        )
        field_ok = non_null > 0
        log.info(
            "%-35s non_null=%d [%s]",
            f"raw_check: {field}",
            non_null,
            "OK" if field_ok else "MISSING",
        )
        if not field_ok:
            passed = False

    # --- Algorithm config check ---
    config_count = (
        tgt.execute(select(func.count()).select_from(PlAlgorithmConfig)).scalar() or 0
    )
    config_ok = config_count == len(NEW_CHAMPION_PARAMS)
    log.info(
        "%-35s count=%d expected=%d [%s]",
        "algorithm_config",
        config_count,
        len(NEW_CHAMPION_PARAMS),
        "OK" if config_ok else "INCOMPLETE",
    )
    if not config_ok:
        passed = False

    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(
    source_url: str = DEFAULT_SOURCE_URL,
    target_url: str = DEFAULT_TARGET_URL,
    dry_run: bool = False,
    validate_only: bool = False,
) -> None:
    """Main entry point for the clean GCP seed."""
    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)

    with Session(source_engine) as src, Session(target_engine) as tgt:
        if validate_only:
            log.info("=== Validation only ===")
            ok = validate_clean(src, tgt)
            if ok:
                log.info("All validation checks passed")
            else:
                log.error("Validation checks failed")
                sys.exit(1)
            return

        log.info("=== Seeding reference data ===")
        refs = seed_reference_data(tgt)
        contract_lookup = build_contract_lookup(refs["contract_ids"])

        log.info("=== Seeding NEW CHAMPION algorithm config ===")
        algo_id = seed_algorithm_new_champion(tgt)

        log.info("=== Migrating raw market data ===")
        cd_count = migrate_raw_market_data(src, tgt, contract_lookup)

        log.info("=== Migrating AI outputs + raw scores ===")
        ind_count = migrate_ai_outputs(src, tgt, contract_lookup, algo_id)

        log.info("=== Migrating market research ===")
        mr_count = migrate_market_research(src, tgt)

        log.info("=== Migrating weather data ===")
        wx_count = migrate_weather(src, tgt)

        log.info("=== Migrating test_range ===")
        tr_count = migrate_test_range(src, tgt)

        log.info("=== Validating clean migration ===")
        ok = validate_clean(src, tgt)

        if dry_run:
            log.info("DRY RUN — rolling back all changes")
            tgt.rollback()
        else:
            if not ok:
                log.error("Validation failed — rolling back")
                tgt.rollback()
                sys.exit(1)
            tgt.commit()
            log.info("All data committed to GCP successfully")

        log.info(
            "Summary: contract_data=%d indicators=%d articles=%d weather=%d test_range=%d",
            cd_count,
            ind_count,
            mr_count,
            wx_count,
            tr_count,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean-data-only migration to GCP Cloud SQL"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without writing"
    )
    parser.add_argument(
        "--validate-only", action="store_true", help="Only run validation checks"
    )
    parser.add_argument(
        "--source-url",
        default=DEFAULT_SOURCE_URL,
        help="Source database URL (default: local Docker :5433)",
    )
    parser.add_argument(
        "--target-url",
        default=DEFAULT_TARGET_URL,
        help="Target database URL (default: GCP proxy :5434)",
    )
    args = parser.parse_args()
    run(
        source_url=args.source_url,
        target_url=args.target_url,
        dry_run=args.dry_run,
        validate_only=args.validate_only,
    )


if __name__ == "__main__":
    main()
