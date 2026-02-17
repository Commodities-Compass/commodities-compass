"""ICE Certified Cocoa Stocks scraper (Report 41).

Discovery (2026-02-17):
ICE publishes daily XLS files at a public, predictable URL:
  https://www.ice.com/publicdocs/futures_us_reports/cocoa/cocoa_cert_stock_YYYYMMDD.xls

No authentication, no reCAPTCHA, no browser needed. Just httpx + xlrd.

Data extracted:
  - Certified Stock Total (bags): sum of all origins across DR + NY ports
  - Grand Total warehouse bags: total bags in ICE US licensed warehouses
"""

import logging
from datetime import date, datetime, timedelta
from io import BytesIO

import httpx
import pandas as pd

from scripts.ice_stocks_scraper.config import (
    ICE_XLS_BASE_URL,
    USER_AGENT,
    VALIDATION_RANGE,
)

logger = logging.getLogger(__name__)


class ICEScraperError(Exception):
    pass


def _business_date(d: date) -> date:
    """Convert weekend dates to previous Friday."""
    weekday = d.weekday()
    if weekday == 5:  # Saturday
        return d - timedelta(days=1)
    if weekday == 6:  # Sunday
        return d - timedelta(days=2)
    return d


def _build_url(d: date, suffix: str = "") -> str:
    """Build XLS download URL for a given date."""
    date_str = d.strftime("%Y%m%d")
    return f"{ICE_XLS_BASE_URL}/cocoa_cert_stock_{date_str}{suffix}.xls"


def download_xls(target_date: date | None = None) -> tuple[bytes, date]:
    """Download ICE certified stock XLS for the given date.

    Tries the target date, then falls back to previous business days.

    Returns:
        Tuple of (xls_bytes, actual_date)
    """
    if target_date is None:
        target_date = _business_date(date.today())

    headers = {"User-Agent": USER_AGENT}
    suffixes = ["", "a"]  # Some files have an 'a' suffix (e.g., 20260205a.xls)
    max_retries = 5  # Try up to 5 previous business days

    for attempt in range(max_retries):
        d = target_date - timedelta(days=attempt)
        d = _business_date(d)

        for suffix in suffixes:
            url = _build_url(d, suffix)
            logger.debug(f"Trying {url}")

            try:
                with httpx.Client(timeout=30) as client:
                    resp = client.get(url, headers=headers)

                if resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "")
                    if (
                        "excel" in content_type
                        or "xls" in content_type
                        or len(resp.content) > 1000
                    ):
                        logger.info(f"Downloaded {url} ({len(resp.content):,} bytes)")
                        return resp.content, d

                logger.debug(f"{url} → {resp.status_code}")

            except httpx.HTTPError as e:
                logger.debug(f"{url} → error: {e}")

    raise ICEScraperError(
        f"No XLS found for {target_date} or {max_retries} previous business days"
    )


def parse_xls(xls_bytes: bytes) -> dict:
    """Parse ICE certified stock XLS and extract US stock data.

    Returns:
        Dict with certified_total_bags, grand_total_bags, report_date, port_data
    """
    df = pd.read_excel(BytesIO(xls_bytes))
    result: dict = {
        "certified_total_bags": None,
        "grand_total_bags": None,
        "port_dr_bags": None,
        "port_ny_bags": None,
        "report_date": None,
    }

    # Extract report date from first column header (format: "Date: M/D/YYYY")
    first_col = str(df.columns[0])
    if "Date:" in first_col:
        date_str = first_col.replace("Date:", "").strip()
        try:
            result["report_date"] = datetime.strptime(date_str, "%m/%d/%Y").date()
        except ValueError:
            pass

    # Iterate rows to find key data points
    for idx, row in df.iterrows():
        first_cell = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        first_cell_lower = first_cell.lower()

        # "Total Bags" row → certified stock total (column "Total" = index 3)
        if first_cell_lower == "total bags":
            for col_idx in [3, 2, 1]:  # Try Total, NY, DR columns
                val = row.iloc[col_idx]
                if pd.notna(val):
                    try:
                        result["certified_total_bags"] = int(float(val))
                        logger.info(
                            f"Certified stock total: {result['certified_total_bags']:,} bags"
                        )
                        break
                    except (ValueError, TypeError):
                        continue

        # "Port of Delaware River" → DR warehouse total
        if "delaware" in first_cell_lower:
            val = row.iloc[1]
            if pd.notna(val):
                try:
                    result["port_dr_bags"] = int(float(val))
                except (ValueError, TypeError):
                    pass

        # "Port of New York" → NY warehouse total
        if "new york" in first_cell_lower:
            val = row.iloc[1]
            if pd.notna(val):
                try:
                    result["port_ny_bags"] = int(float(val))
                except (ValueError, TypeError):
                    pass

        # "GRAND TOTAL" → total US warehouse bags
        if "grand total" in first_cell_lower:
            val = row.iloc[1]
            if pd.notna(val):
                try:
                    result["grand_total_bags"] = int(float(val))
                    logger.info(
                        f"Grand total warehouse: {result['grand_total_bags']:,} bags"
                    )
                except (ValueError, TypeError):
                    pass

    return result


def scrape(target_date: date | None = None) -> dict:
    """Full scrape: download XLS → parse → validate.

    Returns:
        Dict with all extracted data + validation status
    """
    xls_bytes, actual_date = download_xls(target_date)
    data = parse_xls(xls_bytes)
    data["actual_date"] = actual_date

    # Use certified total as the primary value for STOCK US
    us_bags = data.get("certified_total_bags")

    if us_bags is None:
        raise ICEScraperError(
            "Could not extract certified stock total from XLS. "
            "File structure may have changed."
        )

    min_val, max_val = VALIDATION_RANGE
    if not (min_val <= us_bags <= max_val):
        raise ICEScraperError(
            f"Certified stock {us_bags:,} bags outside range [{min_val:,}, {max_val:,}]"
        )

    logger.info(
        f"Report {actual_date}: certified={us_bags:,} bags, "
        f"grand_total={data.get('grand_total_bags', '?')}, "
        f"DR={data.get('port_dr_bags', '?')}, NY={data.get('port_ny_bags', '?')}"
    )

    return data
