"""Shared error type for the NCA grindings scraper.

Extracted to its own module so both ``scraper.py`` and ``browser.py`` can raise
it without a circular import. Re-exported by ``scraper.py`` for backward-compat
imports (``from scripts.nca_grindings_scraper.scraper import NcaScraperError``).
"""

from __future__ import annotations


class NcaScraperError(RuntimeError):
    """Fail-loud error for the NCA scraper (per pipeline-error-handling rule)."""
