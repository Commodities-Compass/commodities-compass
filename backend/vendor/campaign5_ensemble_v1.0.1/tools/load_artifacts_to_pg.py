"""Prod-side loader: reads ``frozen/`` payload + manifest → UPSERTs into pl_model_artifact.

Run after the prod operator has:
    1. Applied ``sql/001_create_pl_model_artifact.sql`` + 002 + 003 + 004 on the
       target database.
    2. Extracted the tarball to a directory accessible from a host that can
       reach Cloud SQL via the bastion (or directly from a Cloud Run job
       container with the SA bound).

Env:
    DATABASE_URL — psycopg2-compatible connection string (e.g.
        postgres://user:pass@host:5432/dbname).
    FROZEN_DIR   — path to the extracted ``frozen/`` directory. Default
        cwd/frozen.
    ALGORITHM_VERSION_NAME (default 'ensemble_v1_softgate_wrapper').
    ALGORITHM_VERSION      (default '1.0.0').

Failure mode: any SHA-256 mismatch in/out aborts the run (rule §0 #1). Partial
loads are rolled back via the single transaction wrapping all UPSERTs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras


_UPSERT_SQL = """
INSERT INTO pl_model_artifact (
    id, algorithm_version_id, artifact_kind, artifact_name, training_month,
    payload, payload_encoding, sha256, n_bytes,
    fit_train_start, fit_train_end, n_train, class_balance,
    git_sha, python_version, lib_versions
)
VALUES (
    gen_random_uuid(), %(aid)s, %(kind)s, %(name)s, %(tm)s,
    %(payload)s, %(encoding)s, %(sha256)s, %(n_bytes)s,
    %(fit_train_start)s, %(fit_train_end)s, %(n_train)s, %(class_balance)s,
    %(git_sha)s, %(python_version)s, %(lib_versions)s
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

_RESOLVE_VERSION_SQL = """
SELECT id FROM pl_algorithm_version
WHERE name = %s AND version = %s
"""

_VERIFY_SHA_SQL = """
SELECT artifact_kind, artifact_name, training_month, payload, sha256
FROM pl_model_artifact
WHERE algorithm_version_id = %s
"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_algorithm_version_id(cur, name: str, version: str) -> str:
    cur.execute(_RESOLVE_VERSION_SQL, (name, version))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"pl_algorithm_version {name}@{version} not found — run "
            f"sql/004_seed_pl_algorithm_version.sql first."
        )
    return str(row[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "load frozen/ into pl_model_artifact")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse + SHA-check the payload but do not write to the DB")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url and not args.dry_run:
        print("DATABASE_URL is required (or pass --dry-run)", file=sys.stderr)
        return 2

    frozen_dir = Path(os.environ.get("FROZEN_DIR", str(Path.cwd() / "frozen"))).resolve()
    manifest_path = frozen_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"manifest.json missing in {frozen_dir}", file=sys.stderr)
        return 2

    manifest = json.loads(manifest_path.read_text())
    version_name = os.environ.get("ALGORITHM_VERSION_NAME", manifest.get("algorithm_version_name", "ensemble_v1_softgate_wrapper"))
    version = os.environ.get("ALGORITHM_VERSION", manifest.get("algorithm_version", "1.0.0"))
    git_sha = manifest["git_sha"]
    lib_versions_json = json.dumps(manifest.get("lib_versions", {}))
    python_version = manifest.get("lib_versions", {}).get("python", "")

    # Pre-flight: every payload reachable + SHA matches manifest --------------
    print(f"[loader] pre-flight check against {manifest_path} "
          f"({len(manifest['artifacts'])} artifacts) ...")
    prepared: list[dict] = []
    for row in manifest["artifacts"]:
        filename = row.get("filename")
        if not filename:
            raise RuntimeError(f"manifest row missing 'filename': {row}")
        path = frozen_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"manifest references missing file: {path}")
        payload = path.read_bytes()
        observed = _sha256(payload)
        if observed != row["sha256"]:
            raise RuntimeError(
                f"sha256 mismatch on {row['artifact_kind']}/{row['artifact_name']}: "
                f"manifest={row['sha256']} observed={observed}"
            )
        prepared.append({
            "row": row,
            "payload": payload,
        })

    print(f"[loader] all {len(prepared)} payloads pass SHA-256 pre-flight")
    if args.dry_run:
        print("[loader] --dry-run set; skipping DB writes")
        return 0

    # DB writes in a single transaction ----------------------------------------
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            aid = _resolve_algorithm_version_id(cur, version_name, version)
            print(f"[loader] target algorithm_version_id = {aid}")
            inserted_or_updated = 0
            for prep in prepared:
                r = prep["row"]
                payload = prep["payload"]
                class_balance = r.get("class_balance")
                cur.execute(_UPSERT_SQL, {
                    "aid": aid,
                    "kind": r["artifact_kind"],
                    "name": r["artifact_name"],
                    "tm": r.get("training_month"),
                    "payload": psycopg2.Binary(payload),
                    "encoding": r["payload_encoding"],
                    "sha256": r["sha256"],
                    "n_bytes": r["n_bytes"],
                    "fit_train_start": r.get("fit_train_start"),
                    "fit_train_end": r.get("fit_train_end"),
                    "n_train": r.get("n_train"),
                    "class_balance": json.dumps(class_balance) if class_balance is not None else None,
                    "git_sha": git_sha,
                    "python_version": python_version,
                    "lib_versions": lib_versions_json,
                })
                inserted_or_updated += 1

            # Post-load verification — re-fetch every row, recompute SHA. -----
            cur.execute(_VERIFY_SHA_SQL, (aid,))
            verified = 0
            for kind, name, tm, payload_bytes, sha in cur.fetchall():
                observed = _sha256(bytes(payload_bytes))
                if observed != sha:
                    raise RuntimeError(
                        f"post-load SHA mismatch on {kind}/{name}@{tm}: "
                        f"row.sha={sha} observed={observed}"
                    )
                verified += 1

    print(f"[loader] UPSERT done: {inserted_or_updated} rows, verified {verified} via DB round-trip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
