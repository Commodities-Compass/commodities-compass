"""Fail-loud HTTP helper shared by all httpx-based scrapers.

Per ``.claude/rules/pipeline-error-handling.md``: no auto-retry, no silent
fallback. A scraper either succeeds fully or fails loudly with the
caller-chosen exception type.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

import httpx

DEFAULT_TIMEOUT_SECONDS = 60

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=Exception)


def fail_loud_get(
    url: str,
    *,
    error_factory: Callable[[str], E],
    user_agent: str,
    accept: str = "text/html,application/xhtml+xml,application/xml",
    extra_headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    follow_redirects: bool = True,
) -> str:
    """HTTP GET with single attempt; raise ``error_factory(msg)`` on failure.

    ``error_factory`` is a callable that takes a message and returns the
    scraper-specific exception to raise (e.g. ``IceCotEuScraperError``).
    This lets every scraper preserve its own exception type while sharing
    the fetch logic.

    Raises:
        Whatever ``error_factory`` returns, on any of:
          * httpx network error
          * non-200 HTTP status
          * empty body
    """
    logger.info("Fetching %s", url)
    headers = {"User-Agent": user_agent, "Accept": accept}
    if extra_headers:
        headers.update(extra_headers)

    try:
        response = httpx.get(
            url,
            headers=headers,
            timeout=timeout,
            follow_redirects=follow_redirects,
        )
    except httpx.HTTPError as exc:
        raise error_factory(f"Network error fetching {url}: {exc}") from exc

    if response.status_code != 200:
        raise error_factory(
            f"HTTP {response.status_code} fetching {url}: {response.text[:200]!r}"
        )

    body = response.text
    if not body.strip():
        raise error_factory(f"Empty body from {url}")

    return body
