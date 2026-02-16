"""Quick IV reconnaissance script to inspect volatility-greeks page structure."""

import re
from playwright.sync_api import sync_playwright
from config import get_volatility_url, get_current_contract_code, USER_AGENT


def main():
    print("=" * 60)
    print("IV Reconnaissance - Barchart volatility-greeks page")
    print("=" * 60)

    # Get current contract
    contract = get_current_contract_code()
    url = get_volatility_url()

    print(f"\nCurrent contract: {contract}")
    print(f"URL: {url}\n")

    # Fetch page with Playwright
    with sync_playwright() as p:
        print("Launching browser...")
        browser = p.webkit.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({"User-Agent": USER_AGENT})

        print(f"Fetching {url}...")
        page.goto(url, wait_until="load", timeout=60000)
        page.wait_for_timeout(2000)

        html = page.content()
        print(f"Fetched {len(html)} bytes\n")

        # Search for IV-related patterns
        print("Searching for Implied Volatility patterns...\n")

        # Pattern 1: JSON field
        pattern1 = r'"impliedVolatility"\s*:\s*(\d+(?:\.\d+)?)'
        match1 = re.search(pattern1, html, re.IGNORECASE)
        if match1:
            print(f"✓ Pattern 1 (JSON 'impliedVolatility'): {match1.group(1)}")
        else:
            print("✗ Pattern 1 not found")

        # Pattern 2: JSON short form
        pattern2 = r'"iv"\s*:\s*(\d+(?:\.\d+)?)'
        match2 = re.search(pattern2, html, re.IGNORECASE)
        if match2:
            print(f"✓ Pattern 2 (JSON 'iv'): {match2.group(1)}")
        else:
            print("✗ Pattern 2 not found")

        # Pattern 3: Text display
        pattern3 = r"Implied Volatility[^>]*>(\d+(?:\.\d+)?)%"
        match3 = re.search(pattern3, html, re.IGNORECASE)
        if match3:
            print(f"✓ Pattern 3 (text 'Implied Volatility'): {match3.group(1)}%")
        else:
            print("✗ Pattern 3 not found")

        # Search for any percentage near "volatility"
        pattern4 = r"volatility[^0-9]*(\d+(?:\.\d+)?)%"
        matches4 = re.findall(pattern4, html, re.IGNORECASE)
        if matches4:
            print(
                f"✓ Pattern 4 (any 'volatility' + %): {matches4[:5]}"
            )  # First 5 matches
        else:
            print("✗ Pattern 4 not found")

        # Save HTML snippet around "volatility" for manual inspection
        volatility_snippet = re.search(r"(.{200}volatility.{200})", html, re.IGNORECASE)
        if volatility_snippet:
            print("\n" + "=" * 60)
            print("HTML snippet around 'volatility':")
            print("=" * 60)
            print(volatility_snippet.group(1))

        browser.close()

    print("\n" + "=" * 60)
    print("Reconnaissance complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
