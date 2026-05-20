"""Common CLI flags for scrapers.

Each scraper builds its argparser on top of ``build_base_argparser`` and
adds its scraper-specific flags (e.g. ``--year``, ``--date``) directly.

The shared flags are:
  * ``--dry-run`` — fetch + parse + log only, no DB write.
  * ``--verbose`` — DEBUG logging.
  * ``--force`` — bypass non-trading-day skip (only for daily scrapers).
"""

from __future__ import annotations

import argparse


def build_base_argparser(
    description: str,
    *,
    include_force: bool = True,
) -> argparse.ArgumentParser:
    """Return an ArgumentParser with --dry-run, --verbose, and optional --force.

    Set ``include_force=False`` for scrapers that aren't daily (e.g. ENSO is
    monthly — no trading-day skip applies, no --force flag).
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape + parse + log, but do not write to DB",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    if include_force:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even on non-trading days (manual backfills/debugging)",
        )
    return parser
