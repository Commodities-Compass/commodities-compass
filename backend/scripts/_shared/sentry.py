"""Bootstrap a scraper's runtime environment (dotenv + Sentry).

Every CLI scraper calls ``bootstrap_scraper("<slug>")`` at module import
time, before ``@monitor``-decorated functions are defined. The slug is
the Sentry cron monitor slug (e.g. ``"fx-scraper"``).
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from app.core.sentry import init_sentry


def bootstrap_scraper(slug: str, *, script_file: str | Path) -> None:
    """Load .env then init Sentry. Idempotent — safe to call multiple times.

    ``script_file`` is typically ``__file__`` from the calling main module;
    the .env is expected at ``backend/.env`` (two parents up from
    ``backend/scripts/<scraper>/main.py``).
    """
    backend_root = Path(script_file).resolve().parent.parent.parent
    load_dotenv(backend_root / ".env")
    init_sentry(slug)
