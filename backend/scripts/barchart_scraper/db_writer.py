"""Database writer for Barchart OHLCV + IV data → pl_contract_data_daily."""

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pipeline import PlContractDataDaily
from scripts.contract_resolver import resolve_by_code

log = logging.getLogger(__name__)


class DbWriterError(Exception):
    pass


def write_ohlcv(
    session: Session,
    data: dict[str, Any],
    contract_code: str,
    dry_run: bool = False,
) -> None:
    """Insert or update a row in pl_contract_data_daily.

    Portable upsert: query by (date, contract_id), update if exists, insert if not.

    Args:
        session: SQLAlchemy sync session (caller manages commit).
        data: Scraper output dict with keys: timestamp, close, high, low,
              volume, open_interest, implied_volatility.
        contract_code: Contract code from ACTIVE_CONTRACT env var (e.g., "CAK26").
        dry_run: Log only, don't write.
    """
    contract_id = resolve_by_code(session, contract_code)
    ts = data["timestamp"]
    row_date: date = ts.date() if hasattr(ts, "date") and callable(ts.date) else ts

    iv_raw = data.get("implied_volatility")
    iv_decimal = Decimal(str(iv_raw)) / 100 if iv_raw is not None else None

    if dry_run:
        log.info(
            "[DRY RUN] Would write to pl_contract_data_daily: "
            "date=%s, contract=%s, close=%s, volume=%s, oi=%s, iv=%s",
            row_date,
            contract_code,
            data.get("close"),
            data.get("volume"),
            data.get("open_interest"),
            iv_decimal,
        )
        return

    existing = session.execute(
        select(PlContractDataDaily).where(
            PlContractDataDaily.date == row_date,
            PlContractDataDaily.contract_id == contract_id,
        )
    ).scalar_one_or_none()

    if existing:
        existing.close = _to_decimal(data.get("close"))
        existing.high = _to_decimal(data.get("high"))
        existing.low = _to_decimal(data.get("low"))
        existing.volume = _to_int(data.get("volume"))
        existing.oi = _to_int(data.get("open_interest"))
        existing.implied_volatility = iv_decimal
        log.info("Updated existing row: date=%s, contract=%s", row_date, contract_code)
    else:
        row = PlContractDataDaily(
            date=row_date,
            contract_id=contract_id,
            close=_to_decimal(data.get("close")),
            high=_to_decimal(data.get("high")),
            low=_to_decimal(data.get("low")),
            volume=_to_int(data.get("volume")),
            oi=_to_int(data.get("open_interest")),
            implied_volatility=iv_decimal,
        )
        session.add(row)
        log.info("Inserted new row: date=%s, contract=%s", row_date, contract_code)

    session.flush()


def _to_decimal(val: Any) -> Decimal | None:
    if val is None:
        return None
    return Decimal(str(val))


def _to_int(val: Any) -> int | None:
    if val is None:
        return None
    return int(val)
