"""Date utility functions for the commodities trading application.

Provides reusable date parsing, validation, and formatting.
Trading-day resolution lives in trading_calendar.py.
"""

from datetime import date, datetime
from typing import Optional


def parse_date_string(date_str: str) -> date:
    """
    Parse a date string in YYYY-MM-DD format to a date object.

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        Parsed date object

    Raises:
        ValueError: If date format is invalid
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"Invalid date format. Use YYYY-MM-DD format: {e}")


def validate_date_format(date_str: str) -> bool:
    """
    Validate if a date string is in correct YYYY-MM-DD format.

    Args:
        date_str: Date string to validate

    Returns:
        True if valid format, False otherwise
    """
    try:
        parse_date_string(date_str)
        return True
    except ValueError:
        return False


def get_year_start_date(reference_date: Optional[date] = None) -> date:
    """
    Get the start date of the year for a given reference date.

    Args:
        reference_date: Reference date (defaults to today)

    Returns:
        January 1st of the reference year
    """
    if reference_date is None:
        reference_date = date.today()

    return date(reference_date.year, 1, 1)


def format_date_for_display(date_obj: date) -> str:
    """
    Format a date object for display in API responses.

    Args:
        date_obj: Date object to format

    Returns:
        Formatted date string (e.g., "January 15, 2024")
    """
    return date_obj.strftime("%B %d, %Y")
