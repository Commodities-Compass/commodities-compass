"""Standard logging setup for scrapers (single format, stdout handler)."""

from __future__ import annotations

import logging
import sys

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def configure_logging(*, verbose: bool = False) -> None:
    """Configure the root logger for a scraper CLI.

    Safe to call multiple times — basicConfig is a no-op after the root
    logger has handlers, but we still bump the level on ``verbose`` so the
    second call still has an effect.
    """
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
