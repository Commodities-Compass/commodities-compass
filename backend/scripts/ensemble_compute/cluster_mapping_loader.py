"""Load runtime config rows from pl_algorithm_config.

Rule §0 #5 (config as data): the winter/spring duality and the Compass
wrapper threshold are externalized to ``pl_algorithm_config`` so future
C6 specialists / tuning rounds are DB-only changes — no redeploy.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

from ensemble.orchestrator.transition_wrapper import WrapperConfig
from sqlalchemy import text
from sqlalchemy.orm import Session


class ClusterMappingNotFoundError(RuntimeError):
    """Raised when fewer than the expected 14 cluster_* config rows are present."""


class CompassWrapperConfigNotFoundError(RuntimeError):
    """Raised when the Compass override threshold row is missing from the DB."""


class WrapperConfigDriftError(RuntimeError):
    """Raised when a ``wrapper_*`` config key does not map to a WrapperConfig field."""


# Expected number of specialists in v1.0.0 (matches seed migration row count).
_EXPECTED_CLUSTERS = 14

COMPASS_WRAPPER_THRESHOLD_KEY = "compass_wrapper_dispersion_with_acc_threshold"

# Prefix for the wrapper-detector config rows. The ``WrapperConfig`` lives in the
# frozen R&D artifact (``tpw_v1``); these rows OVERRIDE it so detector switches /
# thresholds are tunable without re-freezing the artifact or redeploying.
_WRAPPER_PREFIX = "wrapper_"

# Optional Compass-side levers (config-as-data; absent row → lever OFF, no behavior change).
REGIME_MONITOR_ATR_PCTL_KEY = "compass_regime_monitor_atr_pctl"
SOFTGATE_ALPHA_MACRO_CAP_KEY = "compass_softgate_alpha_macro_cap"


def load_optional_config_float(
    session: Session, algorithm_version_id: uuid.UUID, key: str
) -> float | None:
    """Read an optional float config row. Returns None when the row is absent.

    Used by Compass-side levers (regime-MONITOR threshold, alpha_macro cap) that are
    OFF when unconfigured — absence means "lever disabled", a legitimate state (NOT a
    fail-loud case, unlike the required threshold/cluster rows).
    """
    row = session.execute(
        text(
            "SELECT value FROM pl_algorithm_config "
            "WHERE algorithm_version_id = :aid AND parameter_name = :key"
        ),
        {"aid": algorithm_version_id, "key": key},
    ).fetchone()
    return float(row.value) if row is not None else None


def load_cluster_mapping(
    session: Session, algorithm_version_id: uuid.UUID
) -> dict[str, str]:
    """Read ``cluster_<specialist_name>`` rows from pl_algorithm_config.

    Returns ``{specialist_name: 'winter' | 'spring'}``. Fails-loud when the
    count diverges from the expected 14 — guards against partial seeds or
    drift from the R&D pool definition.
    """
    rows = session.execute(
        text(
            "SELECT parameter_name, value FROM pl_algorithm_config "
            "WHERE algorithm_version_id = :aid "
            "AND parameter_name LIKE 'cluster\\_%' ESCAPE '\\'"
        ),
        {"aid": algorithm_version_id},
    ).fetchall()

    mapping: dict[str, str] = {}
    for row in rows:
        # parameter_name is e.g. 'cluster_exp_optim_002' → strip the 'cluster_' prefix.
        name = row.parameter_name[len("cluster_") :]
        mapping[name] = row.value

    if len(mapping) != _EXPECTED_CLUSTERS:
        raise ClusterMappingNotFoundError(
            f"expected {_EXPECTED_CLUSTERS} cluster_* rows in pl_algorithm_config, "
            f"found {len(mapping)} for algorithm_version_id={algorithm_version_id}"
        )

    return mapping


def load_compass_wrapper_threshold(
    session: Session, algorithm_version_id: uuid.UUID
) -> float:
    """Read the Compass-wrapper dispersion-release threshold from pl_algorithm_config.

    Fails-loud if the row is missing — no silent fallback to a hardcoded
    default. The migration ``o9j0k1l2m3n4`` is responsible for seeding it.
    """
    row = session.execute(
        text(
            "SELECT value FROM pl_algorithm_config "
            "WHERE algorithm_version_id = :aid AND parameter_name = :key"
        ),
        {"aid": algorithm_version_id, "key": COMPASS_WRAPPER_THRESHOLD_KEY},
    ).fetchone()

    if row is None:
        raise CompassWrapperConfigNotFoundError(
            f"missing '{COMPASS_WRAPPER_THRESHOLD_KEY}' row in pl_algorithm_config "
            f"for algorithm_version_id={algorithm_version_id}. "
            "Run Alembic migration o9j0k1l2m3n4 to seed it."
        )

    return float(row.value)


def _cast_to_field(field: dataclasses.Field, raw: str) -> Any:
    """Cast a stored string ``value`` to the WrapperConfig field's type.

    bool: '1'/'true'/'yes' → True, '0'/'false'/'no' → False (also tolerates '1.0').
    int / float: parsed directly. Fails-loud on an unparseable value.
    """
    t = field.type
    try:
        if t is bool or t == "bool":
            return str(raw).strip().lower() in {"1", "1.0", "true", "yes", "on"}
        if t is int or t == "int":
            return int(float(raw))  # tolerate '3.0' → 3
        if t is float or t == "float":
            return float(raw)
        return raw
    except (TypeError, ValueError) as exc:
        raise WrapperConfigDriftError(
            f"cannot cast wrapper config '{field.name}'={raw!r} to {t}"
        ) from exc


def load_wrapper_config(
    session: Session, algorithm_version_id: uuid.UUID
) -> WrapperConfig:
    """Build the WrapperConfig from ``wrapper_*`` rows in pl_algorithm_config.

    Config-as-data (north-star rule #4): the frozen ``tpw_v1`` artifact supplies the
    R&D-tuned defaults, but these DB rows are authoritative — they let us flip detector
    switches (e.g. ``use_trend_conflict``) and thresholds without re-freezing the artifact.

    Starts from ``WrapperConfig()`` defaults and overrides every field present as a
    ``wrapper_<field>`` row. Fails-loud (``WrapperConfigDriftError``) on a ``wrapper_*``
    key that doesn't map to a known field — guards against silent config drift.

    Returns the assembled ``WrapperConfig``. Callers pass it to ``CompassTransitionWrapper``.
    """
    rows = session.execute(
        text(
            "SELECT parameter_name, value FROM pl_algorithm_config "
            "WHERE algorithm_version_id = :aid "
            "AND parameter_name LIKE 'wrapper\\_%' ESCAPE '\\'"
        ),
        {"aid": algorithm_version_id},
    ).fetchall()

    fields_by_name = {f.name: f for f in dataclasses.fields(WrapperConfig)}
    overrides: dict[str, Any] = {}
    for row in rows:
        field_name = row.parameter_name[len(_WRAPPER_PREFIX) :]
        field = fields_by_name.get(field_name)
        if field is None:
            raise WrapperConfigDriftError(
                f"config key {row.parameter_name!r} has no matching WrapperConfig "
                f"field (known: {sorted(fields_by_name)}). Fix the seed migration."
            )
        overrides[field_name] = _cast_to_field(field, row.value)

    return dataclasses.replace(WrapperConfig(), **overrides)
