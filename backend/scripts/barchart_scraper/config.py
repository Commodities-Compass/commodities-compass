"""Configuration for Barchart scraper."""

import logging
import os

# Barchart URLs
BARCHART_BASE_URL = "https://www.barchart.com/futures/quotes"

_logger = logging.getLogger(__name__)

# Cached contract code — resolved once per process.
_resolved_contract: str | None = None


def get_current_contract_code() -> str:
    """Return the active contract code, resolved from DB or env var fallback.

    Resolution order:
    1. Database: ref_contract WHERE is_active = true
    2. Fallback: ACTIVE_CONTRACT env var (graceful degradation if DB unavailable)

    Caches the result for the lifetime of the process.
    """
    global _resolved_contract
    if _resolved_contract is not None:
        return _resolved_contract

    # Try DB first — only fall back to env var for transient DB errors
    try:
        from scripts.contract_resolver import resolve_active_code
        from scripts.db import get_session

        with get_session() as session:
            code = resolve_active_code(session)
        _resolved_contract = code
        _logger.info("Active contract: %s (source: database)", code)
        return code
    except (OSError, ConnectionError) as exc:
        # Transient: network/connection issues → env var fallback is acceptable
        _logger.warning("DB contract lookup failed (%s), trying env var fallback", exc)
    except Exception as exc:
        # Import, Attribute, Type, Key errors = code bugs → must not hide
        try:
            from sqlalchemy.exc import OperationalError, InterfaceError

            if isinstance(exc, (OperationalError, InterfaceError)):
                _logger.warning(
                    "DB contract lookup failed (%s), trying env var fallback", exc
                )
            else:
                raise
        except ImportError:
            raise exc from None

    # Fallback to env var
    env_code = os.getenv("ACTIVE_CONTRACT", "")
    if not env_code:
        raise RuntimeError(
            "Cannot resolve active contract: database lookup failed and "
            "ACTIVE_CONTRACT env var not set."
        )
    _resolved_contract = env_code
    _logger.info("Active contract: %s (source: env var fallback)", env_code)
    return env_code


def get_prices_url() -> str:
    contract = get_current_contract_code()
    return f"{BARCHART_BASE_URL}/{contract}/overview"


def get_volatility_url() -> str:
    contract = get_current_contract_code()
    return f"{BARCHART_BASE_URL}/{contract}/volatility-greeks?futuresOptionsView=merged"


# Validation ranges
VALIDATION_RANGES = {
    "close": (1500.0, 20000.0),  # GBP/tonne
    "high": (1500.0, 20000.0),
    "low": (1500.0, 20000.0),
    "volume": (1, 500000),  # Contracts
    "open_interest": (1, 1000000),  # Contracts
    "implied_volatility": (0.0, 200.0),  # Percentage (0-200%)
}

# Playwright browser settings
BROWSER_TIMEOUT = 60000  # 60 seconds
BROWSER_WAIT = 2000  # 2 seconds wait after page load
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Logging
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
