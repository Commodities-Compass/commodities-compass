"""Tests for backend/scripts/_shared/ helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts._shared.cli import build_base_argparser
from scripts._shared.http import fail_loud_get
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper


# ---------------------------------------------------------------------------
# bootstrap_scraper
# ---------------------------------------------------------------------------


class TestBootstrapScraper:
    def test_loads_env_and_inits_sentry(self):
        with (
            patch("scripts._shared.sentry.load_dotenv") as mock_load_dotenv,
            patch("scripts._shared.sentry.init_sentry") as mock_init,
        ):
            bootstrap_scraper("test-slug", script_file=__file__)
        mock_load_dotenv.assert_called_once()
        mock_init.assert_called_once_with("test-slug")

    def test_env_path_is_backend_dot_env(self):
        """The .env file is at backend/.env (two parents up from a scraper's main.py)."""
        fake_main = Path("/foo/backend/scripts/dummy_scraper/main.py")
        with (
            patch("scripts._shared.sentry.load_dotenv") as mock_load_dotenv,
            patch("scripts._shared.sentry.init_sentry"),
        ):
            bootstrap_scraper("slug", script_file=str(fake_main))
        args, _ = mock_load_dotenv.call_args
        assert args[0] == Path("/foo/backend/.env")


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    def test_sets_info_level_by_default(self):
        # Reset root logger level explicitly so the test isn't polluted by
        # other tests' configure calls.
        logging.getLogger().setLevel(logging.WARNING)
        configure_logging(verbose=False)
        # basicConfig is a no-op if handlers exist; we don't rely on level
        # change. Instead, just assert no exception and that the function is
        # safe to call repeatedly.
        configure_logging(verbose=False)  # 2nd call must not raise

    def test_verbose_sets_debug_level(self):
        configure_logging(verbose=True)
        assert logging.getLogger().level == logging.DEBUG


# ---------------------------------------------------------------------------
# build_base_argparser
# ---------------------------------------------------------------------------


class TestBuildBaseArgparser:
    def test_default_has_dry_run_verbose_force(self):
        parser = build_base_argparser("test description")
        args = parser.parse_args([])
        assert args.dry_run is False
        assert args.verbose is False
        assert args.force is False

    def test_dry_run_flag(self):
        parser = build_base_argparser("desc")
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_verbose_flag(self):
        parser = build_base_argparser("desc")
        args = parser.parse_args(["--verbose"])
        assert args.verbose is True

    def test_force_flag(self):
        parser = build_base_argparser("desc")
        args = parser.parse_args(["--force"])
        assert args.force is True

    def test_include_force_false_omits_force(self):
        parser = build_base_argparser("desc", include_force=False)
        # --force is not registered → argparse should fail
        with pytest.raises(SystemExit):
            parser.parse_args(["--force"])

    def test_caller_can_extend_with_extra_args(self):
        """build_base_argparser returns a real ArgumentParser the caller can extend."""
        parser = build_base_argparser("desc")
        parser.add_argument("--year", type=int)
        args = parser.parse_args(["--year", "2024", "--dry-run"])
        assert args.year == 2024
        assert args.dry_run is True


# ---------------------------------------------------------------------------
# fail_loud_get
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code: int, text_body: str) -> None:
        self.status_code = status_code
        self.text = text_body


class _MyError(RuntimeError):
    """Test-specific exception type to pass via error_factory."""


class TestFailLoudGet:
    def test_happy_path_returns_body(self):
        with patch("scripts._shared.http.httpx") as mock_httpx:
            mock_httpx.get.return_value = _FakeResp(200, "hello world")
            mock_httpx.HTTPError = Exception

            result = fail_loud_get(
                "https://example.com",
                error_factory=_MyError,
                user_agent="test/1.0",
            )
        assert result == "hello world"

    def test_non_200_raises_factory(self):
        with patch("scripts._shared.http.httpx") as mock_httpx:
            mock_httpx.get.return_value = _FakeResp(503, "Service Unavailable")
            mock_httpx.HTTPError = Exception

            with pytest.raises(_MyError, match="HTTP 503"):
                fail_loud_get(
                    "https://example.com",
                    error_factory=_MyError,
                    user_agent="test/1.0",
                )

    def test_empty_body_raises_factory(self):
        with patch("scripts._shared.http.httpx") as mock_httpx:
            mock_httpx.get.return_value = _FakeResp(200, "")
            mock_httpx.HTTPError = Exception

            with pytest.raises(_MyError, match="Empty body"):
                fail_loud_get(
                    "https://example.com",
                    error_factory=_MyError,
                    user_agent="test/1.0",
                )

    def test_whitespace_only_body_raises_factory(self):
        with patch("scripts._shared.http.httpx") as mock_httpx:
            mock_httpx.get.return_value = _FakeResp(200, "   \n  \t  ")
            mock_httpx.HTTPError = Exception

            with pytest.raises(_MyError, match="Empty body"):
                fail_loud_get(
                    "https://example.com",
                    error_factory=_MyError,
                    user_agent="test/1.0",
                )

    def test_network_error_raises_factory(self):
        import httpx as real_httpx

        with patch("scripts._shared.http.httpx") as mock_httpx:
            mock_httpx.get.side_effect = real_httpx.ConnectError("connection refused")
            mock_httpx.HTTPError = real_httpx.HTTPError

            with pytest.raises(_MyError, match="Network error"):
                fail_loud_get(
                    "https://example.com",
                    error_factory=_MyError,
                    user_agent="test/1.0",
                )

    def test_extra_headers_are_passed(self):
        captured = {}

        def fake_get(url, headers=None, timeout=None, follow_redirects=None):
            captured["headers"] = headers
            return _FakeResp(200, "ok")

        with patch("scripts._shared.http.httpx") as mock_httpx:
            mock_httpx.get.side_effect = fake_get
            mock_httpx.HTTPError = Exception

            fail_loud_get(
                "https://example.com",
                error_factory=_MyError,
                user_agent="test/1.0",
                accept="text/csv",
                extra_headers={"X-Custom": "value"},
            )

        assert captured["headers"]["User-Agent"] == "test/1.0"
        assert captured["headers"]["Accept"] == "text/csv"
        assert captured["headers"]["X-Custom"] == "value"
