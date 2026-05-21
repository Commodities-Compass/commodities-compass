"""Gate covering the Phase 2 wrapper refactor.

Asserts:
    1. ``DEFAULT_CLUSTER_MAPPING`` covers all 14 SPECIALISTS in the registry,
       and the cluster value matches each architecture's ``cluster`` attribute.
    2. Passing an explicit ``cluster_mapping`` to the wrapper produces the
       expected ``_winter_set`` / ``_spring_set``.
    3. The wrapper's cluster-dispersion detector reads from the constructor
       mapping, not from module-level constants — verified by passing a
       deliberately scrambled mapping and observing the cluster vote counts
       flip accordingly.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ensemble.optimizer.specialists import SPECIALISTS
from ensemble.orchestrator.transition_wrapper import (
    DEFAULT_CLUSTER_MAPPING,
    TransitionProtectionWrapper,
    WrapperConfig,
)


@pytest.mark.unit
def test_default_mapping_matches_registry() -> None:
    registry = {spec.name: spec.cluster for spec in SPECIALISTS}
    assert set(registry) == set(DEFAULT_CLUSTER_MAPPING), \
        "DEFAULT_CLUSTER_MAPPING misses specialists from SPECIALISTS registry " \
        f"(registry-only={set(registry) - set(DEFAULT_CLUSTER_MAPPING)}, " \
        f"mapping-only={set(DEFAULT_CLUSTER_MAPPING) - set(registry)})"
    for name, expected_cluster in registry.items():
        assert DEFAULT_CLUSTER_MAPPING[name] == expected_cluster, \
            f"cluster mismatch on {name}: registry={expected_cluster}, mapping={DEFAULT_CLUSTER_MAPPING[name]}"


@pytest.mark.unit
def test_constructor_builds_winter_and_spring_sets() -> None:
    mapping = {
        "alpha": "winter",
        "beta": "spring",
        "gamma": "winter",
    }
    wrap = TransitionProtectionWrapper(cluster_mapping=mapping)
    assert wrap._winter_set == frozenset({"alpha", "gamma"})
    assert wrap._spring_set == frozenset({"beta"})


@pytest.mark.unit
def test_cluster_votes_uses_constructor_mapping_not_constants() -> None:
    """Scramble the mapping (winter ↔ spring) and verify the detector follows."""
    swapped = {name: ("spring" if c == "winter" else "winter")
               for name, c in DEFAULT_CLUSTER_MAPPING.items()}
    wrap = TransitionProtectionWrapper(
        config=WrapperConfig(),
        cluster_mapping=swapped,
    )
    # 4 winter specialists vote OPEN, 4 spring specialists vote HEDGE on one day.
    today = pd.Timestamp("2026-04-15")
    winter_names = [n for n, c in DEFAULT_CLUSTER_MAPPING.items() if c == "winter"][:4]
    spring_names = [n for n, c in DEFAULT_CLUSTER_MAPPING.items() if c == "spring"][:4]
    votes = pd.DataFrame(
        [{"date": today, "specialist_name": n, "pred": "OPEN"} for n in winter_names]
        + [{"date": today, "specialist_name": n, "pred": "HEDGE"} for n in spring_names]
    )
    w_committed, w_signed, s_committed, s_signed = wrap._cluster_votes(votes, today)
    # After the swap, ``wrap._winter_set`` holds the names that were spring in
    # DEFAULT_CLUSTER_MAPPING — they voted HEDGE → winter_signed = -4.
    # ``wrap._spring_set`` holds the original-winter names — they voted OPEN
    # → spring_signed = +4. If the wrapper still read module-level constants
    # the signs would invert.
    assert (w_committed, w_signed) == (4, -4)
    assert (s_committed, s_signed) == (4, +4)
