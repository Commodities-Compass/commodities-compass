"""Indicator registry with automatic dependency-based computation order.

Registers indicators and resolves computation order via topological sort
on the depends_on → outputs dependency graph.
"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from app.engine.indicators.base import Indicator


class IndicatorRegistry:
    """Registry of indicators with dependency resolution."""

    def __init__(self) -> None:
        self._indicators: list[Indicator] = []
        self._sorted: list[Indicator] | None = None

    def register(self, indicator: Indicator) -> None:
        self._indicators.append(indicator)
        self._sorted = None  # invalidate cache

    def register_all(self, indicators: list[Indicator]) -> None:
        for ind in indicators:
            self.register(ind)

    def compute_order(self) -> list[Indicator]:
        """Topological sort of indicators by dependency."""
        if self._sorted is not None:
            return self._sorted

        # Build mapping: column_name → indicator that produces it
        producer: dict[str, Indicator] = {}
        for ind in self._indicators:
            for col in ind.outputs:
                producer[col] = ind

        # Build adjacency: indicator → set of indicators it depends on
        deps: dict[str, set[str]] = {}
        for ind in self._indicators:
            deps[ind.name] = set()
            for col in ind.depends_on:
                if col in producer:
                    dep_ind = producer[col]
                    if dep_ind.name != ind.name:
                        deps[ind.name].add(dep_ind.name)

        # Kahn's algorithm
        in_degree: dict[str, int] = defaultdict(int)
        for ind in self._indicators:
            if ind.name not in in_degree:
                in_degree[ind.name] = 0
            for dep_name in deps[ind.name]:
                in_degree[ind.name] += 1

        by_name = {ind.name: ind for ind in self._indicators}
        queue = [name for name, deg in in_degree.items() if deg == 0]
        result: list[Indicator] = []

        # Reverse adjacency for degree updates
        dependents: dict[str, list[str]] = defaultdict(list)
        for ind_name, dep_names in deps.items():
            for dep_name in dep_names:
                dependents[dep_name].append(ind_name)

        while queue:
            name = queue.pop(0)
            result.append(by_name[name])
            for dependent in dependents[name]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(self._indicators):
            sorted_names = {ind.name for ind in result}
            missing = {ind.name for ind in self._indicators} - sorted_names
            msg = f"Circular dependency detected among: {missing}"
            raise ValueError(msg)

        self._sorted = result
        return result

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Run all indicators in dependency order. Returns enriched DataFrame."""
        result = df.copy()
        for indicator in self.compute_order():
            result = indicator.compute(result)
        return result
