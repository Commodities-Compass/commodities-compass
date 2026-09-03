"""Intraday delayed-quote scraper tests — inline `raw` block extraction.

Two Barchart posture changes in three days:
  2026-09-01 — CloudFront `public, s-maxage=300` stripped `Set-Cookie`, killing
               the `core-api` XSRF flow. Switched to reading the inline JSON.
  2026-09-03 — AWS WAF JS challenge (HTTP 202) killed httpx entirely. The
               transport moved to a headless browser; this parser is unchanged.

Hence the split: `parse_delayed_quote` is pure and carries every rule, while
`fetch_delayed_quote` only wires a fetcher to it. The next posture change should
touch the transport and leave these tests alone.

Fixtures mirror the real page shape captured on 2026-09-01: one outer JSON
object carrying display strings, one nested `"raw"` object carrying the
numerics, and sibling blocks for other symbols that must never be picked.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from scripts._shared.barchart_browser import BarchartWafError
from scripts.intraday_monitor.scraper import (
    IntradayFetchError,
    IntradayQuote,
    fetch_delayed_quote,
    parse_delayed_quote,
)

CONTRACT = "CAZ26"
OVERVIEW_URL = f"https://www.barchart.com/futures/quotes/{CONTRACT}/overview"

# Epoch of the real capture: 2026-09-01T10:15:28Z.
TRADE_TIME_EPOCH = 1788257728


def _raw_block(
    symbol: str, last_price: object, trade_time: object = TRADE_TIME_EPOCH
) -> str:
    """One `"raw":{...}` block, shaped like Barchart's."""
    price = "null" if last_price is None else str(last_price)
    tt = "null" if trade_time is None else str(trade_time)
    return (
        '"raw":{"symbolType":2,"symbolName":"Cocoa #7",'
        f'"lastPrice":{price},"symbol":"{symbol}","symbolCode":"FUT",'
        '"symbolRoot":"CA","exchange":"ICE\\/EU","category":"Softs",'
        '"marketCap":null,"sectors":[],"industry":null,"isActive":true,'
        f'"pointValue":10,"tradeTime":{tt}}}'
    )


def _page(*blocks: str) -> str:
    """Wrap raw blocks in the surrounding page noise, decoys included."""
    inner = ",".join(blocks)
    return (
        "<!DOCTYPE html><html><head>"
        "<title>Cocoa #7 Dec &#039;26 Futures Price - Barchart.com</title>"
        "</head><body><div class='quote'></div>"
        '<script>var data = {"symbol":"CAZ26","lastPrice":"4,899",'
        '"tradeTime":"05:15 CT","marketCap":"N\\/A","opinion":"100% Buy",'
        f"{inner}}};</script>"
        "</body></html>"
    )


def _quote(body: str | None = None) -> IntradayQuote:
    """Parse a page body straight through the pure parser."""
    return parse_delayed_quote(
        _page(_raw_block(CONTRACT, 4899)) if body is None else body, CONTRACT
    )


class TestHappyPath:
    def test_extracts_price_and_symbol_from_inline_block(self):
        quote = _quote()

        assert quote.symbol == CONTRACT
        assert quote.last_price == Decimal("4899")

    def test_price_is_exact_decimal_not_float(self):
        body = _page(_raw_block(CONTRACT, 4899.5))
        quote = _quote(body)

        assert quote.last_price == Decimal("4899.5")

    def test_trade_time_decoded_as_utc(self):
        quote = _quote()

        assert quote.trade_time == datetime.fromtimestamp(
            TRADE_TIME_EPOCH, tz=timezone.utc
        )

    def test_observed_at_is_now_utc(self):
        before = datetime.now(timezone.utc)
        quote = _quote()

        assert before <= quote.observed_at <= datetime.now(timezone.utc)
        assert quote.observed_at.tzinfo is timezone.utc

    @pytest.mark.parametrize("missing", [None, 0])
    def test_absent_trade_time_is_none_not_epoch_zero(self, missing):
        body = _page(_raw_block(CONTRACT, 4899, trade_time=missing))
        quote = _quote(body)

        assert quote.trade_time is None
        assert quote.last_price == Decimal("4899")


class TestBlockSelection:
    """The wrong-block bug that bit the daily scraper must not recur here."""

    def test_picks_the_block_matching_the_contract_not_the_first(self):
        body = _page(
            _raw_block("CAH27", 5200),
            _raw_block(CONTRACT, 4899),
            _raw_block("CAK27", 5310),
        )
        quote = _quote(body)

        assert quote.symbol == CONTRACT
        assert quote.last_price == Decimal("4899")

    def test_no_block_for_the_contract_is_an_error(self):
        body = _page(_raw_block("CAH27", 5200), _raw_block("CAK27", 5310))

        with pytest.raises(IntradayFetchError, match=CONTRACT):
            _quote(body)

    def test_nested_braces_do_not_truncate_the_block(self):
        nested = (
            '"raw":{"symbol":"CAZ26","lastPrice":4899,'
            '"meta":{"depth":{"bid":4898,"ask":4900}},'
            f'"tradeTime":{TRADE_TIME_EPOCH}}}'
        )
        quote = _quote(_page(nested))

        assert quote.last_price == Decimal("4899")

    def test_duplicate_blocks_that_agree_are_accepted(self):
        """The real page repeats the quoted contract's block three times."""
        body = _page(*[_raw_block(CONTRACT, 4899)] * 3)
        quote = _quote(body)

        assert quote.last_price == Decimal("4899")

    def test_duplicate_blocks_that_disagree_raise(self):
        """First-match would be a coin flip — refuse rather than guess."""
        body = _page(_raw_block(CONTRACT, 4899), _raw_block(CONTRACT, 5100))

        with pytest.raises(IntradayFetchError, match="disagree"):
            _quote(body)

    def test_symbolless_sidebar_blocks_are_ignored(self):
        """~15 blocks on the real page quote other markets and carry no symbol."""
        sidebar = '"raw":{"lastPrice":91.32,"percentChange":0.01}'
        body = _page(sidebar, _raw_block(CONTRACT, 4899), sidebar)
        quote = _quote(body)

        assert quote.last_price == Decimal("4899")

    def test_html_escaped_block_is_decoded(self):
        escaped = _page(_raw_block(CONTRACT, 4899)).replace('"', "&quot;")
        quote = _quote(escaped)

        assert quote.last_price == Decimal("4899")


class TestFailLoud:
    def test_page_without_any_raw_block_raises(self):
        body = "<html><body>Just a moment...</body></html>"

        with pytest.raises(IntradayFetchError):
            _quote(body)

    @pytest.mark.parametrize("bad", [None, '"n/a"'])
    def test_non_numeric_last_price_raises(self, bad):
        body = _page(_raw_block(CONTRACT, bad))

        with pytest.raises(IntradayFetchError, match="lastPrice"):
            _quote(body)

    @pytest.mark.parametrize("price", [1499.0, 20001.0])
    def test_price_outside_sanity_range_raises(self, price):
        body = _page(_raw_block(CONTRACT, price))

        with pytest.raises(IntradayFetchError, match="sanity range"):
            _quote(body)


class TestFetchWiring:
    """`fetch_delayed_quote` only wires a fetcher to the parser."""

    def test_fetches_the_overview_url_for_the_contract(self):
        calls: list[str] = []

        def fake(url: str) -> str:
            calls.append(url)
            return _page(_raw_block(CONTRACT, 4899))

        quote = fetch_delayed_quote(CONTRACT, fetch_html=fake)

        assert calls == [OVERVIEW_URL]
        assert quote.last_price == Decimal("4899")

    def test_no_retry_on_failure(self):
        """Fail-loud contract: one fetch, no silent second attempt."""
        calls: list[str] = []

        def fake(url: str) -> str:
            calls.append(url)
            raise BarchartWafError("challenge did not clear")

        with pytest.raises(IntradayFetchError):
            fetch_delayed_quote(CONTRACT, fetch_html=fake)

        assert len(calls) == 1

    def test_waf_failure_surfaces_as_intraday_fetch_error(self):
        """Callers catch IntradayFetchError — the WAF type must not leak past."""

        def fake(url: str) -> str:
            raise BarchartWafError("AWS WAF challenge did not clear")

        with pytest.raises(IntradayFetchError, match="WAF"):
            fetch_delayed_quote(CONTRACT, fetch_html=fake)
