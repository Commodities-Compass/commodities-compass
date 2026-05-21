"""Bootstrap C5 ensemble artefacts into pl_model_artifact (one-shot).

Wraps ``vendor/campaign5_ensemble_v1.0.0/tools/load_artifacts_to_pg.py``
with our Sentry monitor + env var resolution conventions.

Usage:
    poetry run ensemble-bootstrap-artifacts                # live load
    poetry run ensemble-bootstrap-artifacts --dry-run      # parse + log, no DB write
    poetry run ensemble-bootstrap-artifacts --verbose

The R&D tool reads ``DATABASE_URL``, ``FROZEN_DIR``,
``ALGORITHM_VERSION_NAME``, ``ALGORITHM_VERSION`` from env. We translate
backend's ``DATABASE_SYNC_URL`` (SQLAlchemy URL) into the plain
``postgres://`` string psycopg2 expects, and pin the frozen dir to the
vendored path so the operator never has to remember it.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

import sentry_sdk
from sentry_sdk.crons import monitor

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("ensemble-bootstrap-artifacts", script_file=__file__)


# Vendor path is fixed by the repo layout. Re-bump when R&D ships v1.x.
_VENDOR_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "vendor"
    / "campaign5_ensemble_v1.0.0"
)
_FROZEN_DIR = _VENDOR_DIR / "frozen"
_LOAD_SCRIPT = _VENDOR_DIR / "tools" / "load_artifacts_to_pg.py"


# Default algorithm version names that the seed migration created.
DEFAULT_ALGO_VERSION_NAME = "ensemble_v1_softgate_wrapper"
DEFAULT_ALGO_VERSION = "1.0.0"


def _sqlalchemy_url_to_psycopg2(url: str) -> str:
    """Strip the SQLAlchemy dialect prefix so psycopg2.connect accepts the URL.

    ``postgresql+psycopg2://user:pass@host/db`` -> ``postgres://user:pass@host/db``.
    Any other prefix or scheme is returned unchanged (allows the operator to
    pass a raw psycopg2 URL if they prefer).
    """
    return re.sub(r"^postgresql\+\w+://", "postgres://", url)


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser(
        "Load Campaign 5 ensemble frozen artefacts into pl_model_artifact "
        "(idempotent UPSERT)",
        include_force=False,
    )
    parser.add_argument(
        "--algorithm-version-name",
        default=DEFAULT_ALGO_VERSION_NAME,
        help=f"Default {DEFAULT_ALGO_VERSION_NAME!r} (matches seed migration)",
    )
    parser.add_argument(
        "--algorithm-version",
        default=DEFAULT_ALGO_VERSION,
        help=f"Default {DEFAULT_ALGO_VERSION!r}",
    )
    return parser.parse_args()


@monitor(monitor_slug="ensemble-bootstrap-artifacts")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    if not _FROZEN_DIR.exists():
        logger.error("Frozen dir missing: %s", _FROZEN_DIR)
        return 1
    if not _LOAD_SCRIPT.exists():
        logger.error("R&D loader missing: %s", _LOAD_SCRIPT)
        return 1

    sync_url = os.environ.get("DATABASE_SYNC_URL")
    if not sync_url:
        logger.error("DATABASE_SYNC_URL is required (set via env or .env)")
        return 1
    pg_url = _sqlalchemy_url_to_psycopg2(sync_url)

    logger.info("=" * 60)
    logger.info("Ensemble artefact bootstrap")
    logger.info("Vendor:  %s", _VENDOR_DIR)
    logger.info("Frozen:  %s", _FROZEN_DIR)
    logger.info(
        "Target:  algorithm_version=%s v%s",
        args.algorithm_version_name,
        args.algorithm_version,
    )
    logger.info("Mode:    %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    # Hand off to the R&D tool. We import its `main()` rather than shelling
    # out so Sentry exceptions surface in our monitor cleanly. The env vars
    # below are scoped to this process and removed in the `finally` block —
    # the DATABASE_URL contains plaintext credentials and must never leak
    # into the broader environment (Sentry breadcrumbs, child processes,
    # debug dumps).
    sys.path.insert(0, str(_VENDOR_DIR / "tools"))
    _env_vars_set = {
        "DATABASE_URL": pg_url,
        "FROZEN_DIR": str(_FROZEN_DIR),
        "ALGORITHM_VERSION_NAME": args.algorithm_version_name,
        "ALGORITHM_VERSION": args.algorithm_version,
    }
    for k, v in _env_vars_set.items():
        os.environ[k] = v

    # R&D tool's argparse is its own; pass --dry-run iff we got it.
    rd_argv = ["load_artifacts_to_pg.py"]
    if args.dry_run:
        rd_argv.append("--dry-run")
    if args.verbose:
        rd_argv.append("--verbose")

    saved_argv = sys.argv
    try:
        sys.argv = rd_argv
        import load_artifacts_to_pg

        rc = int(load_artifacts_to_pg.main() or 0)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 — fail-loud top-level
        logger.exception("R&D loader failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1
    finally:
        sys.argv = saved_argv
        # Wipe the env vars we set so credentials don't linger in the process.
        for k in _env_vars_set:
            os.environ.pop(k, None)

    sentry_sdk.set_context(
        "bootstrap",
        {
            "algorithm_version_name": args.algorithm_version_name,
            "algorithm_version": args.algorithm_version,
            "dry_run": args.dry_run,
            "exit_code": rc,
        },
    )

    if rc != 0:
        logger.error("R&D loader returned non-zero exit code: %d", rc)
        return rc

    logger.info("SUCCESS — ensemble artefacts loaded into pl_model_artifact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
