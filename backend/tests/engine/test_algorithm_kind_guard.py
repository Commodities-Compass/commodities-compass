"""The indicator engine must only ever compute power-formula versions.

Before ``algorithm_kind`` existed, the only thing stopping an ML/LLM version
from being fed to the power-formula engine was a convention ("never set
compute_enabled on those"), and the nightly job runs ``--all-versions``. Break
the convention and you get one of two outcomes, both bad:

  * the version HAS config rows but not the power coefficients (regime carries
    16 router params) → ``KeyError: 'k'``, the job dies every night;
  * the version has NO config rows (judge) → the loader used to fall back to
    the hardcoded LEGACY_V1 and write power-formula decisions under that
    version's id — silent corruption of pl_indicator_daily.

These tests turn the convention into a structural guarantee.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.engine.runner import load_algorithm_config, load_compute_enabled_versions
from app.engine.types import (
    POWER_FORMULA_PARAMS,
    AlgorithmConfig,
    AlgorithmConfigIncompatibleError,
    AlgorithmConfigMissingError,
)
from app.models.pipeline import PlAlgorithmConfig, PlAlgorithmVersion


def _add_version(
    session: Session,
    name: str,
    *,
    kind: str,
    compute_enabled: bool,
    version: str = "1.0.0",
) -> PlAlgorithmVersion:
    row = PlAlgorithmVersion(
        name=name,
        version=version,
        horizon="short_term",
        is_active=False,
        compute_enabled=compute_enabled,
        algorithm_kind=kind,
    )
    session.add(row)
    session.flush()
    return row


@pytest.mark.integration
def test_ml_version_is_not_computed_even_when_compute_enabled(
    sync_db_session: Session,
) -> None:
    """The exact mis-configuration that would crash the nightly job."""
    _add_version(
        sync_db_session, "power_one", kind="power_formula", compute_enabled=True
    )
    _add_version(sync_db_session, "regime", kind="ml_regime", compute_enabled=True)
    _add_version(sync_db_session, "judge", kind="llm_overlay", compute_enabled=True)

    names = {name for _, name, _ in load_compute_enabled_versions(sync_db_session)}

    assert "power_one" in names
    assert "regime" not in names
    assert "judge" not in names


@pytest.mark.integration
def test_disabled_power_formula_version_is_not_computed(
    sync_db_session: Session,
) -> None:
    _add_version(sync_db_session, "paused", kind="power_formula", compute_enabled=False)

    names = {name for _, name, _ in load_compute_enabled_versions(sync_db_session)}

    assert "paused" not in names


@pytest.mark.integration
def test_missing_config_raises_instead_of_falling_back_to_legacy(
    sync_db_session: Session,
) -> None:
    """A version with no config rows must fail loudly, never inherit LEGACY_V1."""
    _add_version(
        sync_db_session, "no_config", kind="power_formula", compute_enabled=True
    )

    with pytest.raises(AlgorithmConfigMissingError) as exc:
        load_algorithm_config(sync_db_session, "no_config", "1.0.0")

    assert "no_config" in str(exc.value)


@pytest.mark.integration
def test_router_style_config_raises_and_names_the_missing_params(
    sync_db_session: Session,
) -> None:
    """Regime's real shape: config rows exist, power coefficients do not."""
    version = _add_version(
        sync_db_session, "regime", kind="ml_regime", compute_enabled=False
    )
    for param, value in (
        ("router_trend_band_k", "0.8"),
        ("router_rsi_oversold", "35"),
        ("decision_mode", "binary"),
    ):
        sync_db_session.add(
            PlAlgorithmConfig(
                algorithm_version_id=version.id, parameter_name=param, value=value
            )
        )
    sync_db_session.flush()

    with pytest.raises(AlgorithmConfigIncompatibleError) as exc:
        load_algorithm_config(sync_db_session, "regime", "1.0.0")

    message = str(exc.value)
    assert "regime" in message
    assert "algorithm_kind" in message
    # The missing coefficients are named — the old failure was a bare KeyError.
    assert "'k'" in message


def test_from_db_rows_rejects_a_partial_power_config() -> None:
    """One missing coefficient is enough — no silent default for those."""
    params = {p: "1.0" for p in POWER_FORMULA_PARAMS}
    del params["q"]

    with pytest.raises(AlgorithmConfigIncompatibleError) as exc:
        AlgorithmConfig.from_db_rows("half_configured", params)

    assert "'q'" in str(exc.value)


def test_from_db_rows_accepts_a_complete_power_config() -> None:
    """The optional params keep their defaults — they are not part of the guard."""
    params = {p: "1.0" for p in POWER_FORMULA_PARAMS}

    config = AlgorithmConfig.from_db_rows("complete", params)

    assert config.version_name == "complete"
    assert config.momentum_threshold == 0.2
    assert config.smoothing_window == 5
