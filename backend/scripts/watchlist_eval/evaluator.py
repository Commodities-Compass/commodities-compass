"""Evaluate watchlist items against actual market data."""

import logging
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from .types import DayData, EvalResult, WatchlistItem

_logger = logging.getLogger(__name__)


def load_market_data(session: Session) -> dict[tuple[date, UUID], DayData]:
    """Load all market data into memory for fast lookups.

    Returns dict keyed on (date, contract_id) → DayData.
    """
    rows = session.execute(
        text(
            "SELECT d.date, d.contract_id, d.close, d.volume, d.oi, "
            "d.implied_volatility, d.stock_us, d.com_net_us, "
            "di.rsi_14d, di.macd, di.r1, di.s1, di.pivot, "
            "di.stochastic_k_14, di.atr_14d, "
            "di.bollinger_upper, di.bollinger_lower "
            "FROM pl_contract_data_daily d "
            "JOIN ref_contract c ON d.contract_id = c.id "
            "LEFT JOIN pl_derived_indicators di "
            "  ON d.date = di.date AND d.contract_id = di.contract_id "
            "ORDER BY d.date"
        )
    ).fetchall()

    data: dict[tuple[date, UUID], DayData] = {}
    for r in rows:
        key = (r.date, r.contract_id)
        data[key] = DayData(
            date=r.date,
            contract_id=r.contract_id,
            close=float(r.close or 0),
            volume=int(r.volume or 0),
            oi=int(r.oi or 0),
            rsi_14d=float(r.rsi_14d) if r.rsi_14d is not None else None,
            macd=float(r.macd) if r.macd is not None else None,
            r1=float(r.r1) if r.r1 is not None else None,
            s1=float(r.s1) if r.s1 is not None else None,
            pivot=float(r.pivot) if r.pivot is not None else None,
            stochastic_k_14=float(r.stochastic_k_14)
            if r.stochastic_k_14 is not None
            else None,
            atr_14d=float(r.atr_14d) if r.atr_14d is not None else None,
            bollinger_upper=float(r.bollinger_upper)
            if r.bollinger_upper is not None
            else None,
            bollinger_lower=float(r.bollinger_lower)
            if r.bollinger_lower is not None
            else None,
            implied_volatility=float(r.implied_volatility)
            if r.implied_volatility is not None
            else None,
            stock_us=float(r.stock_us) if r.stock_us is not None else None,
            com_net_us=float(r.com_net_us) if r.com_net_us is not None else None,
        )

    _logger.info("Loaded %d market data rows", len(data))
    return data


def build_date_sequence(
    market_data: dict[tuple[date, UUID], DayData],
) -> dict[UUID, list[date]]:
    """Build sorted date sequences per contract for next-day lookups."""
    by_contract: dict[UUID, set[date]] = {}
    for d, cid in market_data:
        by_contract.setdefault(cid, set()).add(d)

    return {cid: sorted(dates) for cid, dates in by_contract.items()}


def _get_next_n_dates(
    date_seq: list[date],
    after: date,
    n: int,
) -> list[date]:
    """Get the next n trading dates strictly after `after`."""
    result: list[date] = []
    for d in date_seq:
        if d > after:
            result.append(d)
            if len(result) >= n:
                break
    return result


def _get_indicator_value(day: DayData, db_column: str) -> float | None:
    """Read the indicator value from a DayData by column name."""
    column_map: dict[str, str] = {
        "rsi_14d": "rsi_14d",
        "close": "close",
        "oi": "oi",
        "volume": "volume",
        "macd": "macd",
        "r1": "r1",
        "s1": "s1",
        "pivot": "pivot",
        "stochastic_k_14": "stochastic_k_14",
        "atr_14d": "atr_14d",
        "bollinger_upper": "bollinger_upper",
        "bollinger_lower": "bollinger_lower",
        "implied_volatility": "implied_volatility",
        "stock_us": "stock_us",
        "com_net_us": "com_net_us",
        "ema12": "close",  # fallback — EMA not in DayData
        "ema26": "close",  # fallback
        "macd_signal": "macd",  # fallback
    }
    attr = column_map.get(db_column)
    if attr is None:
        return None
    val = getattr(day, attr, None)
    if val is None:
        return None
    return float(val)


def _check_condition(comparator: str, actual: float, threshold: float) -> bool:
    """Check if the condition is met."""
    if comparator in ("BELOW", "CROSS_BELOW"):
        return actual < threshold
    if comparator in ("ABOVE", "CROSS_ABOVE"):
        return actual > threshold
    if comparator == "NEAR":
        if threshold == 0:
            return abs(actual) < 1.0
        return abs(actual - threshold) / abs(threshold) < 0.02
    return False


def _check_direction(
    implied: str, close_on_issue: float, close_at_hit: float
) -> bool | None:
    """Check if the implied direction was correct.

    Returns None for NEUTRE (not evaluable).
    """
    if implied == "NEUTRE":
        return None
    price_change = close_at_hit - close_on_issue
    if implied == "HAUSSIERE":
        return price_change > 0
    if implied == "BAISSIERE":
        return price_change < 0
    return None


def evaluate_item(
    item: WatchlistItem,
    market_data: dict[tuple[date, UUID], DayData],
    date_sequences: dict[UUID, list[date]],
) -> EvalResult | None:
    """Evaluate a single watchlist item against market data.

    Returns None if issue-day data is missing.
    """
    # Get issue-day data
    issue_key = (item.date, item.contract_id)
    issue_day = market_data.get(issue_key)
    if issue_day is None:
        return None

    # Get next 3 trading dates
    date_seq = date_sequences.get(item.contract_id, [])
    next_dates = _get_next_n_dates(date_seq, item.date, 3)

    # Evaluate for each future day
    j_hits: list[bool | None] = [None, None, None]
    j_closes: list[float | None] = [None, None, None]
    j_values: list[float | None] = [None, None, None]

    for i, future_date in enumerate(next_dates):
        future_key = (future_date, item.contract_id)
        future_day = market_data.get(future_key)
        if future_day is None:
            continue

        j_closes[i] = future_day.close
        actual_value = _get_indicator_value(future_day, item.db_column)
        j_values[i] = actual_value

        if actual_value is not None and item.threshold is not None:
            j_hits[i] = _check_condition(item.comparator, actual_value, item.threshold)
        else:
            j_hits[i] = None

    # Find first hit
    first_hit_day: int | None = None
    for i, hit in enumerate(j_hits):
        if hit is True:
            first_hit_day = i + 1
            break

    # Check direction at first hit
    direction_correct: bool | None = None
    if first_hit_day is not None:
        hit_close = j_closes[first_hit_day - 1]
        if hit_close is not None:
            direction_correct = _check_direction(
                item.implied_direction, issue_day.close, hit_close
            )

    return EvalResult(
        item=item,
        close_on_issue=issue_day.close,
        j1_condition_hit=j_hits[0],
        j1_close=j_closes[0],
        j1_actual_value=j_values[0],
        j2_condition_hit=j_hits[1],
        j2_close=j_closes[1],
        j2_actual_value=j_values[1],
        j3_condition_hit=j_hits[2],
        j3_close=j_closes[2],
        j3_actual_value=j_values[2],
        first_hit_day=first_hit_day,
        direction_correct=direction_correct,
    )
