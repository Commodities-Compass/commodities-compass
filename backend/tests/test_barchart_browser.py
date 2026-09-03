"""Barchart AWS WAF challenge detection.

Barchart put barchart.com behind AWS WAF on 2026-09-03: every page answers
HTTP 202 with a ~2KB JS interstitial that mints an ``aws-waf-token`` cookie via
``challenge.js`` and reloads. httpx cannot solve it; a headless browser can.

These tests cover the pure detector. The browser lifecycle itself needs a real
Chromium/WebKit and is exercised by the live jobs, not by CI.
"""

import pytest

from scripts._shared.barchart_browser import (
    BarchartWafError,
    describe_failure,
    is_ready,
    looks_challenged,
)

# Trimmed from the real 1983-byte interstitial served on 2026-09-03.
CHALLENGE_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title></title>
<script type="text/javascript">
    window.awsWafCookieDomainList = [];
    window.gokuProps = {"key":"AQIDAHjcYu","iv":"grC60wCsQ","context":"HMGYw"};
</script>
<script src="https://d24c13e85910.1af6e18a.eu-west-3.token.awswaf.com/challenge.js"></script>
</head><body><div id="challenge-container"></div>
<script type="text/javascript">
    AwsWafIntegration.saveReferrer();
    AwsWafIntegration.getToken().then(() => { window.location.reload(true); });
</script>
<noscript><h1>JavaScript is disabled</h1>
In order to continue, we need to verify that you're not a robot.</noscript>
</body></html>"""

# The settled page carries none of the markers (verified against the live
# 574KB render on 2026-09-03).
REAL_HTML = """<!DOCTYPE html><html><head>
<title>Cocoa #7 Dec '26 Futures Price - Barchart.com</title></head><body>
<script>var data = {"symbol":"CAZ26","raw":{"symbol":"CAZ26","lastPrice":4540}};</script>
</body></html>"""


class TestLooksChallenged:
    def test_interstitial_is_challenged(self):
        assert looks_challenged(CHALLENGE_HTML) is True

    def test_settled_page_is_not_challenged(self):
        assert looks_challenged(REAL_HTML) is False

    @pytest.mark.parametrize(
        "marker",
        [
            '<script src="https://x.token.awswaf.com/challenge.js"></script>',
            '<div id="challenge-container"></div>',
            "window.gokuProps = {};",
            "AwsWafIntegration.getToken()",
        ],
    )
    def test_each_marker_alone_is_enough(self, marker):
        assert looks_challenged(f"<html><body>{marker}</body></html>") is True

    def test_detection_is_case_insensitive(self):
        assert looks_challenged("<html>AWSWAF.COM/CHALLENGE.JS</html>") is True

    @pytest.mark.parametrize("empty", ["", "   ", None])
    def test_empty_content_counts_as_challenged(self, empty):
        """Mid-navigation content() can come back empty — keep polling, never
        hand an empty string to a parser as if it were a settled page."""
        assert looks_challenged(empty) is True

    def test_price_bearing_page_survives_the_word_token(self):
        """A real page mentioning 'token' generically must not read as a challenge."""
        html = REAL_HTML.replace("</body>", "<p>token of appreciation</p></body>")
        assert looks_challenged(html) is False


class TestErrorType:
    def test_waf_error_is_a_runtime_error(self):
        assert issubclass(BarchartWafError, RuntimeError)


class TestIsReady:
    """A page is ready only on POSITIVE evidence.

    The 2026-09-03 prod failure: Cloud Run got a page carrying none of the
    challenge markers, so "not challenged" was read as "settled" and an
    unusable page reached the parser in 288ms. Absence of a challenge is not
    presence of content.
    """

    def test_page_with_the_marker_is_ready(self):
        assert is_ready(REAL_HTML, '"symbol":"CAZ26"') is True

    def test_page_without_the_marker_is_not_ready(self):
        assert is_ready(REAL_HTML, "cmdty-quote-table") is False

    def test_challenge_page_is_never_ready_even_if_it_holds_the_marker(self):
        """A challenge mentioning the marker must not count as settled."""
        html = CHALLENGE_HTML.replace("</body>", '<!-- "symbol":"CAZ26" --></body>')
        assert is_ready(html, '"symbol":"CAZ26"') is False

    @pytest.mark.parametrize("empty", ["", "   ", None])
    def test_empty_page_is_never_ready(self, empty):
        assert is_ready(empty, '"symbol":"CAZ26"') is False

    def test_blocked_page_without_challenge_markers_is_not_ready(self):
        """The prod case: a small block page, no awswaf markers, no content."""
        blocked = "<html><head><title>403 Forbidden</title></head><body>Access Denied</body></html>"

        assert looks_challenged(blocked) is False  # no challenge markers...
        assert is_ready(blocked, '"symbol":"CAZ26"') is False  # ...but not ready


class TestDescribeFailure:
    """The error must carry its own evidence — no second round-trip to diagnose."""

    def test_names_the_url_status_and_marker(self):
        msg = describe_failure(
            url="https://www.barchart.com/x",
            status=403,
            html="<html>nope</html>",
            marker='"symbol":"CAZ26"',
        )

        assert "https://www.barchart.com/x" in msg
        assert "403" in msg
        assert '"symbol":"CAZ26"' in msg

    def test_distinguishes_still_challenged_from_never_ready(self):
        challenged = describe_failure(
            url="u", status=202, html=CHALLENGE_HTML, marker="x"
        )
        never_ready = describe_failure(
            url="u", status=403, html="<html>no</html>", marker="x"
        )

        assert "challenge" in challenged.lower()
        assert "challenge" not in never_ready.lower()

    def test_includes_a_body_snippet(self):
        msg = describe_failure(
            url="u",
            status=403,
            html="<html><body>Access Denied by WAF</body></html>",
            marker="x",
        )

        assert "Access Denied by WAF" in msg

    def test_snippet_is_bounded(self):
        msg = describe_failure(url="u", status=200, html="<p>" + "x" * 9000, marker="m")

        assert len(msg) < 1500

    def test_reports_the_page_length(self):
        msg = describe_failure(url="u", status=200, html="y" * 4242, marker="m")

        assert "4242" in msg

    def test_handles_unknown_status(self):
        msg = describe_failure(url="u", status=None, html="<html/>", marker="m")

        assert "unknown" in msg.lower()
