"""Signal decomposition table for the MVP schema.

Per-indicator contribution to composite trading signal.
Enables explainability: "why did you say HEDGE on Feb 10?"
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DATE, DECIMAL, TIMESTAMP, VARCHAR, ForeignKey, Index, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PlSignalComponent(Base):
    """Per-indicator contribution to a composite trading signal."""

    __tablename__ = "pl_signal_component"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    date: Mapped[date] = mapped_column(DATE, nullable=False)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_contract.id"), nullable=False
    )
    indicator_name: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    raw_value: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    normalized_value: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    weighted_contribution: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(15, 6))
    algorithm_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("pl_algorithm_version.id")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        Index("ix_signal_component_date_contract", "date", "contract_id"),
    )
