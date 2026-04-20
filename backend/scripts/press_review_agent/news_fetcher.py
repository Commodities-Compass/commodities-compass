"""Multi-source news fetcher for cocoa market data.

Supports two fetch methods:
- httpx (default): fast, lightweight HTTP client for SSR sites
- playwright: headless browser for JS-rendered / Cloudflare-protected sites

Also fetches Google News RSS headlines as a coverage layer (titles only,
no link following). Inspired by TogetherCocoa Monitor pattern.
"""

import hashlib
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from scripts.press_review_agent.config import (
    GOOGLE_NEWS_MAX_ITEMS_PER_QUERY,
    GOOGLE_NEWS_QUERIES,
    HTTP_TIMEOUT,
    MAX_CHARS_PER_SOURCE,
    MIN_SOURCES_REQUIRED,
    NEWS_SOURCES,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

PLAYWRIGHT_TIMEOUT_MS = 15_000
PLAYWRIGHT_WAIT_MS = 3_000


@dataclass
class NewsResult:
    name: str
    text: str
    success: bool
    error: str | None = None


@dataclass(frozen=True)
class NewsHeadline:
    title: str
    source: str
    theme: str
    pub_date: str = ""


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


def _fetch_playwright_sources(
    sources: list[dict[str, object]],
) -> list[NewsResult]:
    """Fetch sources that require a headless browser (JS-rendered / Cloudflare).

    Launches a single browser instance, visits each source sequentially,
    then closes the browser.
    """
    if not sources:
        return []

    results: list[NewsResult] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed — skipping browser sources")
        return [
            NewsResult(
                name=str(s["name"]),
                text="",
                success=False,
                error="Playwright not installed",
            )
            for s in sources
        ]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)

        for source in sources:
            name = str(source["name"])
            url = str(source["url"])
            selectors: list[str] = source.get("selectors", [])  # type: ignore[assignment]
            try:
                logger.info(f"Fetching {name} (playwright)...")
                page.goto(
                    url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT_MS
                )
                page.wait_for_timeout(PLAYWRIGHT_WAIT_MS)

                html = page.content()
                text = _extract_text(html, selectors)

                if len(text) < 50:
                    logger.warning(f"{name}: content too short ({len(text)} chars)")
                    results.append(
                        NewsResult(
                            name=name, text="", success=False, error="Content too short"
                        )
                    )
                    continue

                logger.info(f"{name}: extracted {len(text)} chars")
                results.append(NewsResult(name=name, text=text, success=True))

            except Exception as e:
                logger.warning(f"{name}: {e}")
                results.append(
                    NewsResult(name=name, text="", success=False, error=str(e))
                )

        browser.close()

    return results


def fetch_all_sources() -> list[NewsResult]:
    """Fetch news from all configured sources with graceful degradation.

    httpx sources are fetched first, then Playwright sources (if any)
    are fetched in a single browser session.
    """
    results: list[NewsResult] = []
    headers = {"User-Agent": USER_AGENT}

    httpx_sources = [s for s in NEWS_SOURCES if s.get("method", "httpx") == "httpx"]
    pw_sources = [s for s in NEWS_SOURCES if s.get("method") == "playwright"]

    # --- httpx sources ---
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        for source in httpx_sources:
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

    # --- Playwright sources (lazy — only if configured) ---
    results.extend(_fetch_playwright_sources(pw_sources))

    successful = [r for r in results if r.success]
    logger.info(f"Fetched {len(successful)}/{len(NEWS_SOURCES)} sources successfully")

    if len(successful) < MIN_SOURCES_REQUIRED:
        logger.warning(
            f"Only {len(successful)} sources available "
            f"(minimum: {MIN_SOURCES_REQUIRED}). "
            "Agent will run in price-only mode."
        )

    return results


def fetch_google_news_headlines() -> list[NewsHeadline]:
    """Fetch headlines from Google News RSS thematic queries.

    Returns deduplicated headlines (title + source + theme).
    No link following — titles only. ~2s total network time.
    """
    headlines: list[NewsHeadline] = []
    seen_hashes: set[str] = set()
    headers = {"User-Agent": USER_AGENT}

    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for query in GOOGLE_NEWS_QUERIES:
            theme = query["theme"]
            url = query["url"]
            try:
                response = client.get(url, headers=headers)
                root = ET.fromstring(response.text)
                items = root.findall(".//item")

                for item in items[:GOOGLE_NEWS_MAX_ITEMS_PER_QUERY]:
                    title_el = item.find("title")
                    source_el = item.find("source")
                    pub_el = item.find("pubDate")

                    if title_el is None or not title_el.text:
                        continue

                    title = title_el.text.strip()
                    source_name = (
                        source_el.text.strip()
                        if source_el is not None and source_el.text
                        else "Unknown"
                    )
                    pub_date = (
                        pub_el.text.strip()
                        if pub_el is not None and pub_el.text
                        else ""
                    )

                    # Strip " - SourceName" suffix that Google News appends to titles
                    if title.endswith(f" - {source_name}"):
                        title = title[: -len(f" - {source_name}")].strip()

                    # Dedup by MD5 hash of normalized title
                    title_hash = hashlib.md5(title.lower().encode()).hexdigest()
                    if title_hash in seen_hashes:
                        continue
                    seen_hashes.add(title_hash)

                    headlines.append(
                        NewsHeadline(
                            title=title,
                            source=source_name,
                            theme=theme,
                            pub_date=pub_date,
                        )
                    )

            except Exception as e:
                logger.warning(f"Google News RSS ({theme}): {e}")

    # Log per-theme breakdown
    theme_counts: dict[str, int] = {}
    for h in headlines:
        theme_counts[h.theme] = theme_counts.get(h.theme, 0) + 1
    breakdown = ", ".join(f"{t}={n}" for t, n in sorted(theme_counts.items()))
    logger.info(
        f"Google News: {len(headlines)} unique headlines "
        f"from {len(GOOGLE_NEWS_QUERIES)} queries ({breakdown})"
    )
    return headlines


def format_sources_for_prompt(
    results: list[NewsResult],
    headlines: list[NewsHeadline] | None = None,
) -> str:
    """Format successful news results + Google News headlines for prompt."""
    sections: list[str] = []

    # Full-content sources
    for r in results:
        if r.success and r.text:
            sections.append(f"### {r.name}\n{r.text}")

    # Google News headlines (titles only — separate section for grounding)
    if headlines:
        headline_lines: list[str] = []
        for h in headlines:
            headline_lines.append(f"- [{h.source}] {h.title}")
        if headline_lines:
            sections.append(
                "### Headlines du jour (titres uniquement — contexte additionnel, "
                "pas de contenu détaillé)\n" + "\n".join(headline_lines)
            )

    if sections:
        return "\n\n".join(sections)
    return (
        "(No external sources available today — generate analysis "
        "from close price and general market knowledge only)"
    )
