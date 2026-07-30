"""Bootstrap the regime frozen artifacts into ``pl_model_artifact`` (idempotent).

Reads the vendored ``frozen/manifest.json`` (key ``file`` — the regime pack's
manifest schema, distinct from the ensemble's ``filename``) and UPSERTs each of
the 14 artifacts as a BYTEA row under the ``regime`` version id. SHA-256 verified
on read AND after write (fail-loud, rule §0 #1). ``training_month`` is stamped
with the manifest ``data_cutoff`` so ``uq_pl_model_artifact`` (which includes
training_month) actually dedups — a NULL there would defeat ``ON CONFLICT``.

    poetry run regime-bootstrap-artifacts                 # live load
    poetry run regime-bootstrap-artifacts --dry-run       # SHA pre-flight only
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import uuid
from pathlib import Path

import sentry_sdk
from sentry_sdk.crons import monitor
from sqlalchemy import LargeBinary, bindparam, text

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper
from scripts.db import get_session

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("regime-bootstrap-artifacts", script_file=__file__)

_VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor" / "regime_v1.0.0"
_FROZEN_DIR = _VENDOR_DIR / "frozen"

ALGO_VERSION_NAME = "regime"
ALGO_VERSION = "1.0.0"

_UPSERT = """
INSERT INTO pl_model_artifact (
    id, algorithm_version_id, artifact_kind, artifact_name, training_month,
    payload, payload_encoding, sha256, n_bytes,
    fit_train_start, fit_train_end, n_train, class_balance,
    git_sha, python_version, lib_versions
) VALUES (
    gen_random_uuid(), :aid, :kind, :name, :tm,
    :payload, :encoding, :sha256, :n_bytes,
    :fit_start, :fit_end, :n_train, CAST(:class_balance AS jsonb),
    :git_sha, :py, CAST(:libs AS jsonb)
)
ON CONFLICT ON CONSTRAINT uq_pl_model_artifact DO UPDATE SET
    payload = EXCLUDED.payload,
    payload_encoding = EXCLUDED.payload_encoding,
    sha256 = EXCLUDED.sha256,
    n_bytes = EXCLUDED.n_bytes,
    fit_train_start = EXCLUDED.fit_train_start,
    fit_train_end = EXCLUDED.fit_train_end,
    n_train = EXCLUDED.n_train,
    class_balance = EXCLUDED.class_balance,
    git_sha = EXCLUDED.git_sha,
    python_version = EXCLUDED.python_version,
    lib_versions = EXCLUDED.lib_versions
"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_version_id(session) -> uuid.UUID:
    row = session.execute(
        text("SELECT id FROM pl_algorithm_version WHERE name = :n AND version = :v"),
        {"n": ALGO_VERSION_NAME, "v": ALGO_VERSION},
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"pl_algorithm_version {ALGO_VERSION_NAME}@{ALGO_VERSION} not found — "
            "apply sql/001_seed_regime_algorithm.sql (or its migration) first."
        )
    return row[0]


@monitor(monitor_slug="regime-bootstrap-artifacts")
def main() -> int:
    parser = build_base_argparser(
        "Load regime frozen artifacts into pl_model_artifact (idempotent UPSERT)",
        include_force=False,
    )
    args = parser.parse_args()
    configure_logging(verbose=args.verbose)

    manifest_path = _FROZEN_DIR / "manifest.json"
    if not manifest_path.exists():
        logger.error("manifest.json missing in %s", _FROZEN_DIR)
        return 1
    manifest = json.loads(manifest_path.read_text())

    git_sha = manifest["git_sha"]
    libs = manifest.get("lib_versions", {})
    py = libs.get("python", "")
    # training_month is VARCHAR(7) (YYYY-MM cohort). Regime has one freeze — stamp
    # it with the data_cutoff's month so uq_pl_model_artifact dedups on rerun.
    training_month = (manifest.get("data_cutoff") or "")[:7]  # e.g. "2026-07"

    # Pre-flight: every payload reachable + SHA matches the manifest.
    prepared: list[dict] = []
    for row in manifest["artifacts"]:
        rel = row["file"]  # regime manifest key (NOT "filename")
        path = _FROZEN_DIR / rel
        if not path.exists():
            logger.error("manifest references missing file: %s", path)
            return 1
        payload = path.read_bytes()
        observed = _sha256(payload)
        if observed != row["sha256"]:
            logger.error(
                "SHA-256 mismatch %s/%s: manifest=%s observed=%s",
                row["artifact_kind"],
                row["artifact_name"],
                row["sha256"],
                observed,
            )
            return 1
        prepared.append({"row": row, "payload": payload})

    logger.info(
        "Pre-flight OK — %d regime artifacts SHA-256 verified (cutoff %s)",
        len(prepared),
        training_month,
    )
    if args.dry_run:
        logger.info("[DRY RUN] skipping DB writes")
        return 0

    upsert = text(_UPSERT).bindparams(bindparam("payload", type_=LargeBinary))
    with get_session() as session:
        aid = _resolve_version_id(session)
        for prep in prepared:
            r = prep["row"]
            cb = r.get("class_balance")
            session.execute(
                upsert,
                {
                    "aid": str(aid),
                    "kind": r["artifact_kind"],
                    "name": r["artifact_name"],
                    "tm": training_month,
                    "payload": prep["payload"],
                    "encoding": r["payload_encoding"],
                    "sha256": r["sha256"],
                    "n_bytes": r["n_bytes"],
                    "fit_start": r.get("fit_train_start"),
                    "fit_end": r.get("fit_train_end"),
                    "n_train": r.get("n_train"),
                    "class_balance": json.dumps(cb) if cb is not None else None,
                    "git_sha": git_sha,
                    "py": py,
                    "libs": json.dumps(libs),
                },
            )

        # Post-load verification: re-read every regime row, recompute SHA.
        verified = 0
        for kind, name, payload, sha in session.execute(
            text(
                "SELECT artifact_kind, artifact_name, payload, sha256 "
                "FROM pl_model_artifact WHERE algorithm_version_id = :aid"
            ),
            {"aid": str(aid)},
        ).fetchall():
            observed = _sha256(bytes(payload))
            if observed != sha:
                raise RuntimeError(
                    f"post-load SHA mismatch {kind}/{name}: row={sha} obs={observed}"
                )
            verified += 1
        session.commit()

    sentry_sdk.set_context(
        "regime_bootstrap",
        {"n_artifacts": len(prepared), "verified": verified, "cutoff": training_month},
    )
    logger.info(
        "SUCCESS — %d regime artifacts loaded + %d verified via DB round-trip",
        len(prepared),
        verified,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
