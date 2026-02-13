"""
Barchart Scraper for WATCH-AI-PRICING Desktop Application
Scrapes cocoa futures prices from Barchart.com using Playwright

NOTE: This file is currently unused in the main application.
Reserved for later implementation as part of the pricing pipeline.
"""

import os
import sys
import platform
from pathlib import Path


def get_playwright_browsers_path():
    """Get the path to Playwright browsers based on platform"""
    system = platform.system()
    if system == "Darwin":  # macOS
        user_cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    elif system == "Linux":  # Linux (Render, Docker)
        user_cache = Path("/root/.cache/ms-playwright")
        if not user_cache.exists():
            user_cache = Path.home() / ".cache" / "ms-playwright"
    else:  # Windows
        user_cache = Path.home() / "AppData" / "Local" / "ms-playwright"
    return str(user_cache)


def get_browser(playwright):
    """Get the appropriate browser based on platform (WebKit for macOS, Chromium for Linux)"""
    system = platform.system()
    if system == "Linux":
        return playwright.chromium
    else:
        return playwright.webkit


# Set Playwright browsers path BEFORE importing playwright
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = get_playwright_browsers_path()

from playwright.sync_api import sync_playwright  # noqa: E402
import time  # noqa: E402
import re  # noqa: E402
from datetime import datetime  # noqa: E402
from typing import Dict, Optional  # noqa: E402

from .db_manager import db  # noqa: E402
from .supabase_client import supabase_db  # noqa: E402

# Contracts to scrape (H26 -> Z26)
CONTRACTS = {
    "london": ["H26", "K26", "N26", "U26", "Z26"],  # CA prefix
    "new_york": ["H26", "K26", "N26", "U26", "Z26"],  # CC prefix
}

# Price validation ranges (widened for market volatility)
PRICE_RANGES = {
    "london": (1500, 20000),  # GBP/tonne
    "new_york": (2000, 25000),  # USD/tonne
}

# OHLC extraction patterns for Barchart JSON data
OHLC_PATTERNS = {
    "open": r'"openPrice":(\d+(?:\.\d+)?)',
    "high": r'"highPrice":(\d+(?:\.\d+)?)',
    "low": r'"lowPrice":(\d+(?:\.\d+)?)',
    "close": r'"lastPrice":(\d+(?:\.\d+)?)',
    "prev_close": r'"previousPrice":(\d+(?:\.\d+)?)',
    "change": r'"priceChange":(-?\d+(?:\.\d+)?)',
    "change_percent": r'"percentChange":(-?\d+(?:\.\d+)?)',
    "volume": r'"volume":(\d+(?:\.\d+)?)',
    "open_interest": r'"openInterest":(\d+(?:\.\d+)?)',
    "prev_volume": r'"previousVolume":(\d+(?:\.\d+)?)',
    "prev_open_interest": r'"previousOpenInterest":(\d+(?:\.\d+)?)',
}


def extract_ohlc_data(html_content: str, symbol: str) -> Optional[Dict]:
    """
    Extract OHLC data from Barchart HTML content.

    Args:
        html_content: HTML content from Barchart page
        symbol: Contract symbol for pattern matching

    Returns:
        Dict with OHLC data or None if extraction failed
    """
    import html

    # Decode HTML entities (Barchart uses &quot; instead of ")
    decoded_content = html.unescape(html_content)

    ohlc = {}

    # First, try to find the "raw" data block which contains OHLC data
    # The raw block with OHLC data contains fields like lowPrice, openPrice, highPrice, volume, openInterest
    raw_block_pattern = r'"raw"\s*:\s*\{([^}]*"lowPrice"\s*:\s*\d+[^}]*)\}'
    raw_match = re.search(raw_block_pattern, decoded_content)

    if raw_match:
        raw_block = raw_match.group(1)

        # Extract individual fields from the raw block
        field_patterns = {
            "open": r'"openPrice"\s*:\s*(\d+(?:\.\d+)?)',
            "high": r'"highPrice"\s*:\s*(\d+(?:\.\d+)?)',
            "low": r'"lowPrice"\s*:\s*(\d+(?:\.\d+)?)',
            "close": r'"lastPrice"\s*:\s*(\d+(?:\.\d+)?)',
            "prev_close": r'"previousPrice"\s*:\s*(\d+(?:\.\d+)?)',
            "volume": r'"volume"\s*:\s*(\d+(?:\.\d+)?)',
            "open_interest": r'"openInterest"\s*:\s*(\d+(?:\.\d+)?)',
            "prev_volume": r'"previousVolume"\s*:\s*(\d+(?:\.\d+)?)',
            "prev_open_interest": r'"previousOpenInterest"\s*:\s*(\d+(?:\.\d+)?)',
        }

        for field, pattern in field_patterns.items():
            match = re.search(pattern, raw_block)
            if match:
                try:
                    ohlc[field] = float(match.group(1))
                except (ValueError, IndexError):
                    ohlc[field] = None

        # Calculate change if we have close and prev_close
        if ohlc.get("close") and ohlc.get("prev_close") and ohlc["prev_close"] > 0:
            ohlc["change"] = ohlc["close"] - ohlc["prev_close"]
            ohlc["change_percent"] = (ohlc["change"] / ohlc["prev_close"]) * 100

        # If prev_volume or prev_open_interest not found in raw block, search in full content
        if ohlc.get("prev_volume") is None:
            prev_vol_match = re.search(
                r'"previousVolume"\s*:\s*(\d+(?:\.\d+)?)', decoded_content
            )
            if prev_vol_match:
                ohlc["prev_volume"] = float(prev_vol_match.group(1))

        if ohlc.get("prev_open_interest") is None:
            prev_oi_match = re.search(
                r'"previousOpenInterest"\s*:\s*(\d+(?:\.\d+)?)', decoded_content
            )
            if prev_oi_match:
                ohlc["prev_open_interest"] = float(prev_oi_match.group(1))

        if ohlc.get("close"):
            print(
                f"      [+] Extracted from raw block: O={ohlc.get('open')} H={ohlc.get('high')} L={ohlc.get('low')} C={ohlc.get('close')} V={ohlc.get('volume')} (prev={ohlc.get('prev_volume')}) OI={ohlc.get('open_interest')} (prev={ohlc.get('prev_open_interest')})"
            )
            return ohlc

    # Fallback: try to find OHLC patterns directly in the decoded content
    print("      [*] Raw block not found, trying direct patterns...")

    # Patterns for direct extraction (Barchart JSON format)
    direct_patterns = {
        "open": r'"openPrice"\s*:\s*(\d+(?:\.\d+)?)',
        "high": r'"highPrice"\s*:\s*(\d+(?:\.\d+)?)',
        "low": r'"lowPrice"\s*:\s*(\d+(?:\.\d+)?)',
        "close": r'"lastPrice"\s*:\s*(\d+(?:\.\d+)?)',
        "prev_close": r'"previousPrice"\s*:\s*(\d+(?:\.\d+)?)',
        "change": r'"priceChange"\s*:\s*(-?\d+(?:\.\d+)?)',
        "change_percent": r'"percentChange"\s*:\s*(-?\d+(?:\.\d+)?)',
        "volume": r'"volume"\s*:\s*(\d+(?:\.\d+)?)',
        "open_interest": r'"openInterest"\s*:\s*(\d+(?:\.\d+)?)',
        "prev_volume": r'"previousVolume"\s*:\s*(\d+(?:\.\d+)?)',
        "prev_open_interest": r'"previousOpenInterest"\s*:\s*(\d+(?:\.\d+)?)',
    }

    for field, pattern in direct_patterns.items():
        # Search in the whole content
        matches = re.findall(pattern, decoded_content)
        if matches:
            try:
                # Take the first numeric match (there might be multiple)
                ohlc[field] = float(matches[0])
            except (ValueError, IndexError):
                ohlc[field] = None

    # Check if we have at least the close price
    if ohlc.get("close") is None:
        return None

    print(
        f"      [+] Extracted via fallback: O={ohlc.get('open')} H={ohlc.get('high')} L={ohlc.get('low')} C={ohlc.get('close')} V={ohlc.get('volume')} (prev={ohlc.get('prev_volume')}) OI={ohlc.get('open_interest')} (prev={ohlc.get('prev_open_interest')})"
    )
    return ohlc


def scrape_individual_contract(
    page, symbol: str, expected_range: tuple
) -> Optional[float]:
    """
    Scrape a single contract from Barchart

    Args:
        page: Playwright page object
        symbol: Contract symbol (e.g., 'CCH26' or 'CAH26')
        expected_range: Tuple (min, max) for price validation

    Returns:
        Price as float, or None if failed
    """
    url = f"https://www.barchart.com/futures/quotes/{symbol}/overview"

    try:
        page.goto(url, wait_until="load", timeout=60000)
        time.sleep(2)  # Wait for content to load

        # Get HTML content
        html_content = page.content()

        # Pattern to extract price from embedded JSON
        pattern = rf'"symbol":"{re.escape(symbol)}".*?"lastPrice":(\d+)'
        match = re.search(pattern, html_content)

        if match:
            price_str = match.group(1)
            price = float(price_str.replace(",", ""))

            # Validate price
            if expected_range[0] < price < expected_range[1]:
                return price
            else:
                print(
                    f"      [!] Price out of range: {price} (expected {expected_range[0]}-{expected_range[1]})"
                )
                return None
        else:
            print("      [!] Pattern not found in HTML")
            return None

    except Exception as e:
        print(f"      [!] Error: {e}")
        return None


def scrape_all_contracts(headless: bool = False, callback=None) -> Dict:
    """
    Scrape all cocoa futures contracts from Barchart

    Args:
        headless: Run browser in headless mode (invisible)
        callback: Optional callback function(message, progress) for UI updates

    Returns:
        Dict with structure: {
            'london': {'H26': 4500, 'K26': 4520, ...},
            'new_york': {'H26': 6200, 'K26': 6220, ...},
            'timestamp': '2025-01-15T10:30:00',
            'success': True/False,
            'error': 'Error message if failed'
        }
    """

    def log(message, progress=0):
        print(message)
        if callback:
            callback(message, progress)

    log("Starting Barchart scraper...", 0)

    prices = {"london": {}, "new_york": {}, "timestamp": None, "success": False}

    try:
        # Check browser path
        browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "not set")
        log(f"Browser path: {browsers_path}", 2)

        with sync_playwright() as p:
            log("Launching browser...", 5)

            # In packaged app, always use headless mode for reliability
            is_frozen = getattr(sys, "frozen", False)
            use_headless = True if is_frozen else headless

            log(f"Headless mode: {use_headless} (frozen: {is_frozen})", 6)

            browser = get_browser(p).launch(
                headless=use_headless, slow_mo=100 if use_headless else 300
            )
            page = browser.new_page()

            # Set a realistic user agent
            page.set_extra_http_headers(
                {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            )

            total_contracts = len(CONTRACTS["new_york"]) + len(CONTRACTS["london"])
            current = 0

            # Scrape New York contracts
            log("Scraping New York contracts...", 10)

            for contract in CONTRACTS["new_york"]:
                symbol = f"CC{contract}"
                log(
                    f"   Fetching {symbol}...", 10 + int(current / total_contracts * 80)
                )

                price = scrape_individual_contract(
                    page, symbol, PRICE_RANGES["new_york"]
                )

                if price:
                    prices["new_york"][contract] = price
                    log(
                        f"   {contract}: {price} USD",
                        10 + int(current / total_contracts * 80),
                    )

                current += 1

            # Scrape London contracts
            log("Scraping London contracts...", 50)

            for contract in CONTRACTS["london"]:
                symbol = f"CA{contract}"
                log(
                    f"   Fetching {symbol}...", 10 + int(current / total_contracts * 80)
                )

                price = scrape_individual_contract(page, symbol, PRICE_RANGES["london"])

                if price:
                    prices["london"][contract] = price
                    log(
                        f"   {contract}: {price} GBP",
                        10 + int(current / total_contracts * 80),
                    )

                current += 1

            browser.close()

        # Check if we got any data
        if prices["london"] or prices["new_york"]:
            prices["timestamp"] = datetime.now().isoformat()
            prices["success"] = True
            log(
                f"Scraping complete: {len(prices['london'])} London, {len(prices['new_york'])} NY",
                95,
            )
        else:
            prices["success"] = False
            prices["error"] = "No data extracted"
            log("Scraping failed: No data extracted", 100)

    except Exception as e:
        prices["success"] = False
        prices["error"] = str(e)
        log(f"Scraping error: {e}", 100)
        import traceback

        traceback.print_exc()

    return prices


def scrape_ohlc_contract(page, symbol: str, expected_range: tuple) -> Optional[Dict]:
    """
    Scrape full OHLC data for a single contract from Barchart.

    Args:
        page: Playwright page object
        symbol: Contract symbol (e.g., 'CCH26' or 'CAH26')
        expected_range: Tuple (min, max) for price validation

    Returns:
        Dict with OHLC data, or None if failed
    """
    url = f"https://www.barchart.com/futures/quotes/{symbol}/overview"

    try:
        page.goto(url, wait_until="load", timeout=60000)
        time.sleep(2)  # Wait for content to load

        # Get HTML content
        html_content = page.content()

        # Extract OHLC data
        ohlc = extract_ohlc_data(html_content, symbol)

        if ohlc and ohlc.get("close"):
            close_price = ohlc["close"]

            # Validate close price
            if expected_range[0] < close_price < expected_range[1]:
                return ohlc
            else:
                print(f"      [!] Close price out of range: {close_price}")
                return None
        else:
            print(f"      [!] OHLC data not found for {symbol}")
            return None

    except Exception as e:
        print(f"      [!] Error scraping OHLC for {symbol}: {e}")
        return None


def scrape_all_ohlc(headless: bool = True, callback=None) -> Dict:
    """
    Scrape OHLC data for all cocoa futures contracts.

    Args:
        headless: Run browser in headless mode
        callback: Optional callback function for UI updates

    Returns:
        Dict with structure: {
            'london': {'H26': {open, high, low, close, ...}, ...},
            'new_york': {'H26': {open, high, low, close, ...}, ...},
            'timestamp': '2025-01-15T10:30:00',
            'success': True/False
        }
    """

    def log(message, progress=0):
        print(message)
        if callback:
            callback(message, progress)

    log("Starting OHLC scraper...", 0)

    ohlc_data = {"london": {}, "new_york": {}, "timestamp": None, "success": False}

    try:
        with sync_playwright() as p:
            log("Launching browser...", 5)

            browser = get_browser(p).launch(headless=headless, slow_mo=100)
            page = browser.new_page()

            page.set_extra_http_headers(
                {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            )

            total_contracts = len(CONTRACTS["new_york"]) + len(CONTRACTS["london"])
            current = 0

            # Scrape New York contracts
            log("Scraping New York OHLC...", 10)
            for contract in CONTRACTS["new_york"]:
                symbol = f"CC{contract}"
                log(
                    f"   Fetching {symbol} OHLC...",
                    10 + int(current / total_contracts * 80),
                )

                ohlc = scrape_ohlc_contract(page, symbol, PRICE_RANGES["new_york"])

                if ohlc:
                    ohlc_data["new_york"][contract] = ohlc
                    log(
                        f"   {contract}: Close={ohlc.get('close')}",
                        10 + int(current / total_contracts * 80),
                    )

                current += 1

            # Scrape London contracts
            log("Scraping London OHLC...", 50)
            for contract in CONTRACTS["london"]:
                symbol = f"CA{contract}"
                log(
                    f"   Fetching {symbol} OHLC...",
                    10 + int(current / total_contracts * 80),
                )

                ohlc = scrape_ohlc_contract(page, symbol, PRICE_RANGES["london"])

                if ohlc:
                    ohlc_data["london"][contract] = ohlc
                    log(
                        f"   {contract}: Close={ohlc.get('close')}",
                        10 + int(current / total_contracts * 80),
                    )

                current += 1

            browser.close()

        # Check if we got any data
        if ohlc_data["london"] or ohlc_data["new_york"]:
            ohlc_data["timestamp"] = datetime.now().isoformat()
            ohlc_data["success"] = True
            log(
                f"OHLC scraping complete: {len(ohlc_data['london'])} London, {len(ohlc_data['new_york'])} NY",
                95,
            )
        else:
            ohlc_data["success"] = False
            ohlc_data["error"] = "No OHLC data extracted"
            log("OHLC scraping failed: No data extracted", 100)

    except Exception as e:
        ohlc_data["success"] = False
        ohlc_data["error"] = str(e)
        log(f"OHLC scraping error: {e}", 100)
        import traceback

        traceback.print_exc()

    return ohlc_data


def scrape_and_save(headless: bool = False, callback=None) -> Dict:
    """
    Scrape prices and save them to the database

    Args:
        headless: Run browser in headless mode
        callback: Optional callback function for UI updates

    Returns:
        Dict with scraping results
    """

    def log(message, progress=0):
        print(message)
        if callback:
            callback(message, progress)

    # Scrape prices
    prices = scrape_all_contracts(headless=headless, callback=callback)

    if not prices["success"]:
        return prices

    # Save to database
    log("Saving prices to database...", 96)

    saved_count = 0
    for market in ["london", "new_york"]:
        currency = "GBP" if market == "london" else "USD"
        for contract, price in prices[market].items():
            if db.save_manual_price(market, contract, price, currency):
                saved_count += 1

    # Save to history buffer (keeps last 4 snapshots for trends)
    from .history_buffer import history
    from .contract_ratios import ratios_manager

    # Include current H26 ratios in snapshot
    h26_ratios = ratios_manager.get_ratios("H26")
    prices["ratios"] = h26_ratios
    history.save_snapshot(prices)

    log(f"Saved {saved_count} prices to database", 100)

    prices["saved_count"] = saved_count
    return prices


async def scrape_individual_contract_async(
    page, symbol: str, expected_range: tuple
) -> Optional[float]:
    """
    Async version: Scrape a single contract from Barchart

    Args:
        page: Playwright async page object
        symbol: Contract symbol (e.g., 'CCH26' or 'CAH26')
        expected_range: Tuple (min, max) for price validation

    Returns:
        Price as float, or None if failed
    """
    url = f"https://www.barchart.com/futures/quotes/{symbol}/overview"

    try:
        await page.goto(url, wait_until="load", timeout=60000)
        await page.wait_for_timeout(2000)  # Wait for content to load

        # Get HTML content
        html_content = await page.content()

        # Pattern to extract price from embedded JSON
        pattern = rf'"symbol":"{re.escape(symbol)}".*?"lastPrice":(\d+)'
        match = re.search(pattern, html_content)

        if match:
            price_str = match.group(1)
            price = float(price_str.replace(",", ""))

            # Validate price
            if expected_range[0] < price < expected_range[1]:
                return price
            else:
                print(
                    f"      [!] Price out of range: {price} (expected {expected_range[0]}-{expected_range[1]})"
                )
                return None
        else:
            print(f"      [!] Pattern not found in HTML for {symbol}")
            return None

    except Exception as e:
        print(f"      [!] Error scraping {symbol}: {e}")
        return None


async def scrape_all_contracts_live():
    """
    Async generator that yields live events during scraping for SSE streaming.

    Yields events like:
        {"type": "init", "message": "Starting..."}
        {"type": "progress", "percent": 10, "message": "..."}
        {"type": "price", "market": "new_york", "contract": "H26", "price": 6200, "currency": "USD"}
        {"type": "complete", "success": True, "london": {...}, "new_york": {...}}
        {"type": "error", "message": "..."}
    """
    from playwright.async_api import async_playwright

    prices = {"london": {}, "new_york": {}, "timestamp": None, "success": False}

    yield {"type": "init", "message": "Initializing Barchart scraper..."}

    try:
        # Check browser path
        browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "not set")
        yield {
            "type": "progress",
            "percent": 2,
            "message": f"Browser path: {browsers_path}",
        }

        async with async_playwright() as p:
            yield {"type": "progress", "percent": 5, "message": "Launching browser..."}

            # Always use headless mode for streaming
            browser = await get_browser(p).launch(headless=True, slow_mo=100)
            page = await browser.new_page()

            # Set user agent
            await page.set_extra_http_headers(
                {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            )

            yield {
                "type": "progress",
                "percent": 10,
                "message": "Browser ready. Starting data extraction...",
            }

            total_contracts = len(CONTRACTS["new_york"]) + len(CONTRACTS["london"])
            current = 0

            # Scrape New York contracts
            yield {
                "type": "market_start",
                "market": "new_york",
                "message": "Fetching New York (ICE) contracts...",
            }

            for contract in CONTRACTS["new_york"]:
                symbol = f"CC{contract}"
                yield {
                    "type": "contract_start",
                    "market": "new_york",
                    "contract": contract,
                    "symbol": symbol,
                }

                price = await scrape_individual_contract_async(
                    page, symbol, PRICE_RANGES["new_york"]
                )

                current += 1
                progress = 10 + int(current / total_contracts * 80)

                if price:
                    prices["new_york"][contract] = price
                    # Save to database
                    db.save_manual_price("new_york", contract, price, "USD")
                    yield {
                        "type": "price",
                        "market": "new_york",
                        "contract": contract,
                        "symbol": symbol,
                        "price": price,
                        "currency": "USD",
                        "percent": progress,
                    }
                else:
                    yield {
                        "type": "contract_error",
                        "market": "new_york",
                        "contract": contract,
                        "symbol": symbol,
                        "message": "Failed to extract price",
                        "percent": progress,
                    }

            yield {
                "type": "market_complete",
                "market": "new_york",
                "count": len(prices["new_york"]),
            }

            # Scrape London contracts
            yield {
                "type": "market_start",
                "market": "london",
                "message": "Fetching London (ICE Liffe) contracts...",
            }

            for contract in CONTRACTS["london"]:
                symbol = f"CA{contract}"
                yield {
                    "type": "contract_start",
                    "market": "london",
                    "contract": contract,
                    "symbol": symbol,
                }

                price = await scrape_individual_contract_async(
                    page, symbol, PRICE_RANGES["london"]
                )

                current += 1
                progress = 10 + int(current / total_contracts * 80)

                if price:
                    prices["london"][contract] = price
                    # Save to database
                    db.save_manual_price("london", contract, price, "GBP")
                    yield {
                        "type": "price",
                        "market": "london",
                        "contract": contract,
                        "symbol": symbol,
                        "price": price,
                        "currency": "GBP",
                        "percent": progress,
                    }
                else:
                    yield {
                        "type": "contract_error",
                        "market": "london",
                        "contract": contract,
                        "symbol": symbol,
                        "message": "Failed to extract price",
                        "percent": progress,
                    }

            yield {
                "type": "market_complete",
                "market": "london",
                "count": len(prices["london"]),
            }

            await browser.close()

        # Final results
        if prices["london"] or prices["new_york"]:
            prices["timestamp"] = datetime.now().isoformat()
            prices["success"] = True
            saved_count = len(prices["london"]) + len(prices["new_york"])

            # Save to history buffer with ratios
            from .history_buffer import history
            from .contract_ratios import ratios_manager

            h26_ratios = ratios_manager.get_ratios("H26")
            prices["ratios"] = h26_ratios
            history.save_snapshot(prices)

            yield {
                "type": "complete",
                "success": True,
                "london": prices["london"],
                "new_york": prices["new_york"],
                "saved_count": saved_count,
                "timestamp": prices["timestamp"],
                "percent": 100,
            }
        else:
            yield {
                "type": "complete",
                "success": False,
                "error": "No data extracted",
                "percent": 100,
            }

    except Exception as e:
        import traceback

        traceback.print_exc()
        yield {"type": "error", "message": str(e), "percent": 100}


async def scrape_ohlc_contract_async(
    page, symbol: str, expected_range: tuple, max_retries: int = 2
) -> Optional[Dict]:
    """
    Async version: Scrape full OHLC data for a single contract from Barchart.

    Args:
        page: Playwright async page object
        symbol: Contract symbol (e.g., 'CCH26' or 'CAH26')
        expected_range: Tuple (min, max) for price validation
        max_retries: Number of retry attempts on failure

    Returns:
        Dict with OHLC data, or None if failed
    """
    url = f"https://www.barchart.com/futures/quotes/{symbol}/overview"

    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                print(f"      [*] Retry {attempt}/{max_retries} for {symbol}...")
                await page.wait_for_timeout(5000)  # Wait 5s before retry

            await page.goto(url, wait_until="load", timeout=90000)  # 90s timeout
            await page.wait_for_timeout(3000)  # Wait 3s for content to load

            # Get HTML content
            html_content = await page.content()

            # Extract OHLC data using patterns
            ohlc = extract_ohlc_data(html_content, symbol)

            if ohlc and ohlc.get("close"):
                close_price = ohlc["close"]

                # Validate close price
                if expected_range[0] < close_price < expected_range[1]:
                    return ohlc
                else:
                    print(f"      [!] Close price out of range: {close_price}")
                    return None
            else:
                print(f"      [!] OHLC data not found for {symbol}")
                if attempt < max_retries:
                    continue
                return None

        except Exception as e:
            print(f"      [!] Error scraping OHLC for {symbol}: {e}")
            if attempt < max_retries:
                continue
            return None

    return None


async def scrape_all_ohlc_live():
    """
    Async generator that yields live events during OHLC scraping for SSE streaming.

    Yields events like:
        {"type": "init", "message": "Starting OHLC scraper..."}
        {"type": "progress", "percent": 10, "message": "..."}
        {"type": "ohlc", "market": "new_york", "contract": "H26", "data": {...}, "currency": "USD"}
        {"type": "complete", "success": True, "london": {...}, "new_york": {...}}
        {"type": "error", "message": "..."}
    """
    from playwright.async_api import async_playwright
    from datetime import date

    ohlc_data = {"london": {}, "new_york": {}, "timestamp": None, "success": False}

    yield {"type": "init", "message": "Initializing OHLC scraper..."}

    try:
        # Check browser path
        browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "not set")
        yield {
            "type": "progress",
            "percent": 2,
            "message": f"Browser path: {browsers_path}",
        }

        async with async_playwright() as p:
            yield {"type": "progress", "percent": 5, "message": "Launching browser..."}

            browser = await get_browser(p).launch(headless=True, slow_mo=100)
            page = await browser.new_page()

            await page.set_extra_http_headers(
                {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            )

            yield {
                "type": "progress",
                "percent": 10,
                "message": "Browser ready. Extracting OHLC data...",
            }

            total_contracts = len(CONTRACTS["new_york"]) + len(CONTRACTS["london"])
            current = 0
            today = date.today()

            # Scrape New York contracts
            yield {
                "type": "market_start",
                "market": "new_york",
                "message": "Fetching New York (ICE) OHLC...",
            }

            for contract in CONTRACTS["new_york"]:
                symbol = f"CC{contract}"
                yield {
                    "type": "contract_start",
                    "market": "new_york",
                    "contract": contract,
                    "symbol": symbol,
                }

                ohlc = await scrape_ohlc_contract_async(
                    page, symbol, PRICE_RANGES["new_york"]
                )

                current += 1
                progress = 10 + int(current / total_contracts * 80)

                if ohlc:
                    # Calculate volume/OI change percentages using previous day's Supabase data
                    volume_change_percent = None
                    oi_change_percent = None

                    # Get previous day's data from Supabase (exclude today)
                    prev_record = supabase_db.get_previous_ohlc(
                        "new_york", contract, exclude_date=today.isoformat()
                    )

                    new_vol = ohlc.get("volume")
                    new_oi = ohlc.get("open_interest")

                    if prev_record:
                        prev_vol = prev_record.get("volume")
                        prev_oi = prev_record.get("open_interest")

                        if prev_vol and prev_vol > 0 and new_vol is not None:
                            volume_change_percent = round(
                                ((new_vol - prev_vol) / prev_vol) * 100, 2
                            )
                        if prev_oi and prev_oi > 0 and new_oi is not None:
                            oi_change_percent = round(
                                ((new_oi - prev_oi) / prev_oi) * 100, 2
                            )

                    # Add change percentages to ohlc data for display
                    ohlc["volume_change_percent"] = volume_change_percent
                    ohlc["oi_change_percent"] = oi_change_percent
                    ohlc_data["new_york"][contract] = ohlc

                    # Save to Supabase (cloud)
                    supabase_db.save_ohlc_price(
                        {
                            "market": "new_york",
                            "contract": contract,
                            "date": today.isoformat(),
                            "close_price": ohlc.get("close", 0),
                            "currency": "USD",
                            "open_price": ohlc.get("open"),
                            "high_price": ohlc.get("high"),
                            "low_price": ohlc.get("low"),
                            "prev_close": ohlc.get("prev_close"),
                            "volume": ohlc.get("volume"),
                            "open_interest": ohlc.get("open_interest"),
                            "change": ohlc.get("change"),
                            "change_percent": ohlc.get("change_percent"),
                            "volume_change_percent": volume_change_percent,
                            "oi_change_percent": oi_change_percent,
                        }
                    )

                    yield {
                        "type": "ohlc",
                        "market": "new_york",
                        "contract": contract,
                        "symbol": symbol,
                        "data": ohlc,
                        "currency": "USD",
                        "percent": progress,
                    }
                else:
                    yield {
                        "type": "contract_error",
                        "market": "new_york",
                        "contract": contract,
                        "symbol": symbol,
                        "message": "Failed to extract OHLC",
                        "percent": progress,
                    }

                # Delay between contracts to avoid rate limiting (5 seconds)
                await page.wait_for_timeout(5000)

            yield {
                "type": "market_complete",
                "market": "new_york",
                "count": len(ohlc_data["new_york"]),
            }

            # Scrape London contracts
            yield {
                "type": "market_start",
                "market": "london",
                "message": "Fetching London (ICE Liffe) OHLC...",
            }

            for contract in CONTRACTS["london"]:
                symbol = f"CA{contract}"
                yield {
                    "type": "contract_start",
                    "market": "london",
                    "contract": contract,
                    "symbol": symbol,
                }

                ohlc = await scrape_ohlc_contract_async(
                    page, symbol, PRICE_RANGES["london"]
                )

                current += 1
                progress = 10 + int(current / total_contracts * 80)

                if ohlc:
                    # Calculate volume/OI change percentages using previous day's Supabase data
                    volume_change_percent = None
                    oi_change_percent = None

                    # Get previous day's data from Supabase (exclude today)
                    prev_record = supabase_db.get_previous_ohlc(
                        "london", contract, exclude_date=today.isoformat()
                    )

                    new_vol = ohlc.get("volume")
                    new_oi = ohlc.get("open_interest")

                    if prev_record:
                        prev_vol = prev_record.get("volume")
                        prev_oi = prev_record.get("open_interest")

                        if prev_vol and prev_vol > 0 and new_vol is not None:
                            volume_change_percent = round(
                                ((new_vol - prev_vol) / prev_vol) * 100, 2
                            )
                        if prev_oi and prev_oi > 0 and new_oi is not None:
                            oi_change_percent = round(
                                ((new_oi - prev_oi) / prev_oi) * 100, 2
                            )

                    # Add change percentages to ohlc data for display
                    ohlc["volume_change_percent"] = volume_change_percent
                    ohlc["oi_change_percent"] = oi_change_percent
                    ohlc_data["london"][contract] = ohlc

                    # Save to Supabase (cloud)
                    supabase_db.save_ohlc_price(
                        {
                            "market": "london",
                            "contract": contract,
                            "date": today.isoformat(),
                            "close_price": ohlc.get("close", 0),
                            "currency": "GBP",
                            "open_price": ohlc.get("open"),
                            "high_price": ohlc.get("high"),
                            "low_price": ohlc.get("low"),
                            "prev_close": ohlc.get("prev_close"),
                            "volume": ohlc.get("volume"),
                            "open_interest": ohlc.get("open_interest"),
                            "change": ohlc.get("change"),
                            "change_percent": ohlc.get("change_percent"),
                            "volume_change_percent": volume_change_percent,
                            "oi_change_percent": oi_change_percent,
                        }
                    )

                    yield {
                        "type": "ohlc",
                        "market": "london",
                        "contract": contract,
                        "symbol": symbol,
                        "data": ohlc,
                        "currency": "GBP",
                        "percent": progress,
                    }
                else:
                    yield {
                        "type": "contract_error",
                        "market": "london",
                        "contract": contract,
                        "symbol": symbol,
                        "message": "Failed to extract OHLC",
                        "percent": progress,
                    }

                # Delay between contracts to avoid rate limiting (5 seconds)
                await page.wait_for_timeout(5000)

            yield {
                "type": "market_complete",
                "market": "london",
                "count": len(ohlc_data["london"]),
            }

            await browser.close()

        # Final results
        if ohlc_data["london"] or ohlc_data["new_york"]:
            ohlc_data["timestamp"] = datetime.now().isoformat()
            ohlc_data["success"] = True
            saved_count = len(ohlc_data["london"]) + len(ohlc_data["new_york"])

            yield {
                "type": "complete",
                "success": True,
                "london": ohlc_data["london"],
                "new_york": ohlc_data["new_york"],
                "saved_count": saved_count,
                "timestamp": ohlc_data["timestamp"],
                "percent": 100,
            }
        else:
            yield {
                "type": "complete",
                "success": False,
                "error": "No OHLC data extracted",
                "percent": 100,
            }

    except Exception as e:
        import traceback

        traceback.print_exc()
        yield {"type": "error", "message": str(e), "percent": 100}


# For direct execution (testing)
if __name__ == "__main__":
    print("=" * 60)
    print("WATCH-AI-PRICING - Barchart Scraper Test")
    print("=" * 60)

    result = scrape_and_save(headless=False)

    print("\n" + "=" * 60)
    print("RESULTS:")
    print("=" * 60)
    print(f"Success: {result.get('success')}")
    print(f"London: {result.get('london')}")
    print(f"New York: {result.get('new_york')}")
    if result.get("error"):
        print(f"Error: {result.get('error')}")
