"""Multi-source news fetcher for cocoa market data."""

import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from scripts.press_review_agent.config import (
    HTTP_TIMEOUT,
    MAX_CHARS_PER_SOURCE,
    MIN_SOURCES_REQUIRED,
    NEWS_SOURCES,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


@dataclass
class NewsResult:
    name: str
    text: str
    success: bool
    error: str | None = None


class NewsFetcherError(Exception):
    pass


def _extract_text(html: str, selectors: list[str]) -> str:
    """Extract readable text from HTML using BeautifulSoup.

    Tries selectors in order, falls back to all <p> tags.
    Strips nav/script/style, truncates to MAX_CHARS_PER_SOURCE.
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    for selector in selectors:
        elements = soup.select(selector)
        if elements:
            text = " ".join(el.get_text(separator=" ", strip=True) for el in elements)
            if len(text) > 100:
                return text[:MAX_CHARS_PER_SOURCE]

    paragraphs = soup.find_all("p")
    text = " ".join(p.get_text(strip=True) for p in paragraphs)
    return text[:MAX_CHARS_PER_SOURCE]


def fetch_all_sources() -> list[NewsResult]:
    """Fetch news from all configured sources with graceful degradation.

    Returns list of NewsResult (both successes and failures for logging).
    """
    results: list[NewsResult] = []
    headers = {"User-Agent": USER_AGENT}

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        for source in NEWS_SOURCES:
            name = source["name"]
            url = source["url"]
            try:
                logger.info(f"Fetching {name}...")
                response = client.get(url, headers=headers)
                response.raise_for_status()

                text = _extract_text(response.text, source["selectors"])
                if len(text) < 50:
                    logger.warning(f"{name}: content too short ({len(text)} chars)")
                    results.append(
                        NewsResult(
                            name=name,
                            text="",
                            success=False,
                            error="Content too short",
                        )
                    )
                    continue

                logger.info(f"{name}: extracted {len(text)} chars")
                results.append(NewsResult(name=name, text=text, success=True))

            except httpx.TimeoutException:
                logger.warning(f"{name}: timeout after {HTTP_TIMEOUT}s")
                results.append(
                    NewsResult(name=name, text="", success=False, error="Timeout")
                )
            except httpx.HTTPStatusError as e:
                logger.warning(f"{name}: HTTP {e.response.status_code}")
                results.append(
                    NewsResult(
                        name=name,
                        text="",
                        success=False,
                        error=f"HTTP {e.response.status_code}",
                    )
                )
            except Exception as e:
                logger.warning(f"{name}: {e}")
                results.append(
                    NewsResult(name=name, text="", success=False, error=str(e))
                )

    successful = [r for r in results if r.success]
    logger.info(f"Fetched {len(successful)}/{len(NEWS_SOURCES)} sources successfully")

    if len(successful) < MIN_SOURCES_REQUIRED:
        logger.warning(
            f"Only {len(successful)} sources available "
            f"(minimum: {MIN_SOURCES_REQUIRED}). "
            "Agent will run in price-only mode."
        )

    return results


def format_sources_for_prompt(results: list[NewsResult]) -> str:
    """Format successful news results into the user prompt sources section."""
    sections: list[str] = []
    for r in results:
        if r.success and r.text:
            sections.append(f"### {r.name}\n{r.text}")
    if sections:
        return "\n\n".join(sections)
    return "(No external sources available today — generate analysis from close price and general market knowledge only)"
