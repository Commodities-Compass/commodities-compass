"""Reconstruct a ``RegimePipeline`` from ``pl_model_artifact`` BYTEA rows.

Prod-shaped mirror of the vendored ``FrozenDirLoader`` (which reads a disk
``frozen/`` dir): identical contract — return the 6 deserialized specialists +
the router config, having SHA-256-verified every payload against the stored
digest — but the bytes come from the DB, not disk. ``feature_order`` is the
canonical ``regime.config.FEATURES`` (== the manifest's ``router_features``).

Fail-loud on any SHA mismatch or a missing model/router (rule §0 #1).
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import uuid

from regime.config import FEATURES
from regime.pipeline import RegimePipeline
from regime.router import RegimeRouter
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class RegimeArtifactError(RuntimeError):
    """Raised on missing artifacts or a SHA-256 mismatch in the DB read path."""


_SELECT = """
SELECT artifact_kind, artifact_name, payload, sha256
FROM pl_model_artifact
WHERE algorithm_version_id = :aid
"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_regime_pipeline_from_db(
    session: Session, *, algorithm_version_id: uuid.UUID
) -> RegimePipeline:
    """Load + SHA-verify the regime specialists + router from pl_model_artifact."""
    rows = session.execute(text(_SELECT), {"aid": str(algorithm_version_id)}).fetchall()
    if not rows:
        raise RegimeArtifactError(
            f"no pl_model_artifact rows for regime version {algorithm_version_id} "
            "— run `poetry run regime-bootstrap-artifacts` first"
        )

    specialists: dict[str, object] = {}
    router_cfg: dict | None = None
    for kind, name, payload, sha in rows:
        blob = bytes(payload)
        observed = _sha256(blob)
        if observed != sha:
            raise RegimeArtifactError(
                f"SHA-256 mismatch on {kind}/{name}: row={sha} observed={observed}"
            )
        if kind == "regime_specialist_model":
            specialists[name] = pickle.loads(blob)
        elif kind == "regime_router":
            router_cfg = json.loads(blob.decode())

    if not specialists:
        raise RegimeArtifactError("no regime_specialist_model artifacts in the DB")
    if router_cfg is None:
        raise RegimeArtifactError("no regime_router artifact in the DB")

    logger.info(
        "Loaded regime pipeline from DB: %d specialists (%s) + router",
        len(specialists),
        ",".join(sorted(specialists)),
    )
    return RegimePipeline(specialists, RegimeRouter(router_cfg), list(FEATURES))
