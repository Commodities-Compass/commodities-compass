"""Test Range model for defining indicator color thresholds."""

from decimal import Decimal

from sqlalchemy import DECIMAL, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, validates

from .base import Base


class TestRange(Base):
    """Test Range table for indicator color zone definitions.

    Each row defines a range (low to high) for a specific indicator
    and assigns it a color zone (RED, ORANGE, GREEN) used for
    trading signal interpretation.
    """

    __tablename__ = "test_range"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    indicator: Mapped[str] = mapped_column(
        String(50),
        comment="Name of the indicator (e.g., MACROECO, RSI, MACD)",
    )

    range_low: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        comment="Lower boundary of the range (inclusive)",
    )

    range_high: Mapped[Decimal] = mapped_column(
        DECIMAL(15, 6),
        comment="Upper boundary of the range (inclusive)",
    )

    area: Mapped[str] = mapped_column(
        String(10),
        comment="Color zone for this range (RED, ORANGE, GREEN)",
    )

    __table_args__ = (
        UniqueConstraint(
            "indicator", "range_low", "range_high", name="uq_indicator_range"
        ),
    )

    @validates("area")
    def validate_area(self, key, value):
        """Validate that area is one of the allowed values."""
        allowed_values = ["RED", "ORANGE", "GREEN"]
        if value and value.upper() not in allowed_values:
            raise ValueError(f"Area must be one of {allowed_values}")
        return value.upper() if value else value

    @validates("range_low", "range_high")
    def validate_range(self, key, value):
        """Ensure range values are valid."""
        if value is None:
            raise ValueError(f"{key} cannot be None")
        return value

    def __repr__(self):
        return (
            f"<TestRange(indicator='{self.indicator}', "
            f"range=[{self.range_low}, {self.range_high}], "
            f"area='{self.area}')>"
        )
