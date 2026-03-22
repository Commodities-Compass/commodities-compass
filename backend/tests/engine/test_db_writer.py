"""Tests for db_writer utility functions (no DB required)."""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from app.engine.db_writer import _to_decimal, _to_str


class TestToDecimal:
    def test_float(self) -> None:
        assert _to_decimal(3.14159) == Decimal("3.14159")

    def test_int(self) -> None:
        assert _to_decimal(42) == Decimal("42")

    def test_nan(self) -> None:
        assert _to_decimal(float("nan")) is None

    def test_none(self) -> None:
        assert _to_decimal(None) is None

    def test_numpy_nan(self) -> None:
        assert _to_decimal(np.nan) is None

    def test_numpy_float(self) -> None:
        result = _to_decimal(np.float64(2.5))
        assert result == Decimal("2.5")

    def test_precision_capped_at_6(self) -> None:
        result = _to_decimal(1.123456789)
        assert result == Decimal("1.123457")  # rounded to 6 decimals

    def test_large_value(self) -> None:
        result = _to_decimal(123456789.123456)
        assert result is not None


class TestToStr:
    def test_string(self) -> None:
        assert _to_str("OPEN") == "OPEN"

    def test_nan(self) -> None:
        assert _to_str(float("nan")) is None

    def test_none(self) -> None:
        assert _to_str(None) is None

    def test_number(self) -> None:
        assert _to_str(42) == "42"
