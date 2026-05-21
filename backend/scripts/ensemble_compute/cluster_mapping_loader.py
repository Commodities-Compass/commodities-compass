"""Load runtime config rows from pl_algorithm_config.

Rule §0 #5 (config as data): the winter/spring duality and the Compass
wrapper threshold are externalized to ``pl_algorithm_config`` so future
C6 specialists / tuning rounds are DB-only changes — no redeploy.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


class ClusterMappingNotFoundError(RuntimeError):
    """Raised when fewer than the expected 14 cluster_* config rows are present."""


class CompassWrapperConfigNotFoundError(RuntimeError):
    """Raised when the Compass override threshold row is missing from the DB."""


# Expected number of specialists in v1.0.0 (matches seed migration row count).
_EXPECTED_CLUSTERS = 14

COMPASS_WRAPPER_THRESHOLD_KEY = "compass_wrapper_dispersion_with_acc_threshold"


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
