"""Indicator protocol and base helpers.

Every indicator implements the Indicator protocol:
- name: unique identifier
- outputs: columns this indicator produces
- depends_on: columns it needs (from raw data or other indicators)
- warmup: minimum rows needed before producing valid output
- compute(df) -> df: pure function, returns new DataFrame with columns added
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class Indicator(Protocol):
    """Protocol for all technical indicators."""

    @property
    def name(self) -> str: ...

    @property
    def outputs(self) -> tuple[str, ...]: ...

    @property
    def depends_on(self) -> tuple[str, ...]: ...

    @property
    def warmup(self) -> int: ...

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute indicator values.

        Takes a DataFrame with all required columns (depends_on).
        Returns a NEW DataFrame with output columns added.
        Never mutates the input.
        """
        ...
