"""Tests for the Python review fixes — covers the highest-risk changes.

These tests verify behavioral correctness of the CRITICAL and HIGH fixes
from the 2026-04-29 code review, focused on files with zero prior coverage.
"""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# C1: SSRF — _resolve_file_url validates origin
# ---------------------------------------------------------------------------


class TestResolveFileUrl:
    """C1: Verify _resolve_file_url rejects non-Drive URLs."""

    def test_valid_drive_download_url(self):
        from app.api.api_v1.endpoints.audio import _resolve_file_url

        url = "https://drive.google.com/uc?id=abc123&export=download"
        assert _resolve_file_url(url) == url

    def test_valid_drive_share_url(self):
        from app.api.api_v1.endpoints.audio import _resolve_file_url

        url = "https://drive.google.com/file/d/abc123/view"
        result = _resolve_file_url(url)
        assert result == "https://drive.google.com/uc?id=abc123&export=download"

    def test_rejects_non_drive_url(self):
        from fastapi import HTTPException

        from app.api.api_v1.endpoints.audio import _resolve_file_url

        with pytest.raises(HTTPException) as exc_info:
            _resolve_file_url("https://evil.com/uc?id=abc&export=download")
        assert exc_info.value.status_code == 500
        assert "Invalid audio source" in exc_info.value.detail

    def test_rejects_url_without_protocol(self):
        from fastapi import HTTPException

        from app.api.api_v1.endpoints.audio import _resolve_file_url

        with pytest.raises(HTTPException):
            _resolve_file_url("drive.google.com/uc?id=abc&export=download")


# ---------------------------------------------------------------------------
# C2: JWKS async lock — verify lock exists and is used
# ---------------------------------------------------------------------------


class TestJWKSCacheLock:
    """C2: Verify JWKS cache uses asyncio.Lock."""

    def test_lock_exists(self):
        from app.core.auth import _jwks_lock

        assert isinstance(_jwks_lock, asyncio.Lock)

    def test_jwks_cache_is_ttl(self):
        from cachetools import TTLCache

        from app.core.auth import jwks_cache

        assert isinstance(jwks_cache, TTLCache)


# ---------------------------------------------------------------------------
# C3: SCORE_COLS/NORM_COLS imported from types.py
# ---------------------------------------------------------------------------


class TestColumnListsImported:
    """C3: Verify db_writer uses the same lists as types.py."""

    def test_score_cols_match(self):
        from app.engine.db_writer import _INDICATOR_SCORE_COLS
        from app.engine.types import SCORE_COLS

        assert _INDICATOR_SCORE_COLS is SCORE_COLS

    def test_norm_cols_match(self):
        from app.engine.db_writer import _INDICATOR_NORM_COLS
        from app.engine.types import NORM_COLS

        assert _INDICATOR_NORM_COLS is NORM_COLS


# ---------------------------------------------------------------------------
# C7: LLM parse failure sets success=False
# ---------------------------------------------------------------------------


class TestLLMParseFailure:
    """C7: Verify extract_json failure → success=False + raw logged."""

    def test_meteo_parse_failure_returns_false(self):

        # Simulate what happens when extract_json raises ValueError
        from unittest.mock import patch

        with patch(
            "scripts.meteo_agent.llm_client.extract_json",
            side_effect=ValueError("bad json"),
        ):
            result = asyncio.run(self._call_meteo_with_mock())
        assert result.success is False
        assert "JSON parse failed" in (result.error or "")
        assert result.raw_text != ""  # raw text preserved

    async def _call_meteo_with_mock(self):
        """Call the meteo LLM client with a mocked OpenAI response."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not valid json {"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        with patch("scripts.meteo_agent.llm_client.openai.AsyncOpenAI") as MockClient:
            instance = AsyncMock()
            MockClient.return_value = instance
            instance.chat.completions.create = AsyncMock(return_value=mock_response)

            from scripts.meteo_agent.llm_client import call_openai

            return await call_openai("system", "user")

    def test_press_review_parse_failure_returns_false(self):
        from scripts.press_review_agent.llm_client import _try_parse_json
        from scripts.press_review_agent.config import Provider

        with patch(
            "scripts.press_review_agent.llm_client.extract_json",
            side_effect=ValueError("bad json"),
        ):
            result = _try_parse_json("raw text", Provider.OPENAI, {}, 100)
        assert result.success is False
        assert result.raw_text == "raw text"
        assert "JSON parse failed" in (result.error or "")

    def test_press_review_parse_success(self):
        from scripts.press_review_agent.llm_client import _try_parse_json
        from scripts.press_review_agent.config import Provider

        with patch(
            "scripts.press_review_agent.llm_client.extract_json",
            return_value={"key": "value"},
        ):
            result = _try_parse_json("raw text", Provider.OPENAI, {}, 100)
        assert result.success is True
        assert result.parsed == {"key": "value"}


# ---------------------------------------------------------------------------
# H4: Position coercion logs error
# ---------------------------------------------------------------------------


class TestPositionCoercion:
    """H4: Unexpected position values trigger error log."""

    def test_valid_positions_pass_through(self):
        from app.services.dashboard_transformers import (
            transform_to_position_status_response,
        )

        for pos in ("OPEN", "HEDGE", "MONITOR"):
            resp = transform_to_position_status_response(pos, 5.0, date.today())
            assert resp.position == pos

    def test_none_defaults_to_monitor_with_log(self, caplog):
        from app.services.dashboard_transformers import (
            transform_to_position_status_response,
        )

        import logging

        with caplog.at_level(logging.ERROR):
            resp = transform_to_position_status_response(None, 5.0, date.today())
        assert resp.position == "MONITOR"
        assert "UNEXPECTED POSITION VALUE" in caplog.text

    def test_invalid_value_defaults_to_monitor_with_log(self, caplog):
        from app.services.dashboard_transformers import (
            transform_to_position_status_response,
        )

        import logging

        with caplog.at_level(logging.ERROR):
            resp = transform_to_position_status_response("OUVERT", 5.0, date.today())
        assert resp.position == "MONITOR"
        assert "UNEXPECTED POSITION VALUE" in caplog.text

    def test_whitespace_stripped(self):
        from app.services.dashboard_transformers import (
            transform_to_position_status_response,
        )

        resp = transform_to_position_status_response("  open  ", 5.0, date.today())
        assert resp.position == "OPEN"


# ---------------------------------------------------------------------------
# H7: Response models serialize correctly
# ---------------------------------------------------------------------------


class TestAuthResponseModels:
    """H7: Auth response schemas work."""

    def test_user_response_from_jwt_payload(self):
        from app.schemas.auth import UserResponse

        payload = {
            "sub": "auth0|123",
            "email": "test@example.com",
            "name": "Test User",
            "permissions": ["read:data"],
        }
        resp = UserResponse(**payload)
        assert resp.sub == "auth0|123"
        assert resp.email == "test@example.com"

    def test_user_response_strips_extra_fields(self):
        from app.schemas.auth import UserResponse

        payload = {
            "sub": "auth0|123",
            "email": "test@example.com",
            "name": "Test",
            "permissions": [],
            "iss": "https://evil.auth0.com/",
            "aud": "secret-audience",
            "internal_claim": "should_not_leak",
        }
        resp = UserResponse(**payload)
        data = resp.model_dump()
        assert "iss" not in data
        assert "aud" not in data
        assert "internal_claim" not in data

    def test_token_verify_response(self):
        from app.schemas.auth import TokenVerifyResponse

        resp = TokenVerifyResponse(valid=True, user_id="auth0|123")
        assert resp.valid is True

    def test_non_trading_days_response(self):
        from app.schemas.auth import NonTradingDaysResponse

        resp = NonTradingDaysResponse(
            dates=["2026-01-01", "2026-12-25"],
            latest_trading_day="2026-04-28",
        )
        assert len(resp.dates) == 2


# ---------------------------------------------------------------------------
# H12: Vectorized composite produces same results as scalar
# ---------------------------------------------------------------------------


class TestVectorizedComposite:
    """H12: Vectorized compute_signals matches scalar compute_score."""

    @pytest.fixture
    def config(self):
        from app.engine.types import LEGACY_V1

        return LEGACY_V1

    def test_vectorized_power_term_matches_scalar(self, config):
        from app.engine.composite import _power_term, _vectorized_power_term

        values = np.array([-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, np.nan])
        coeff, exp = config.a, config.b

        vectorized = _vectorized_power_term(coeff, exp, values)
        for i, v in enumerate(values):
            scalar = _power_term(
                coeff, exp, float(v) if not np.isnan(v) else float("nan")
            )
            if np.isnan(v):
                assert vectorized[i] == 0.0  # NaN → 0.0
            else:
                assert abs(vectorized[i] - scalar) < 1e-10, (
                    f"Mismatch at index {i}: {vectorized[i]} vs {scalar}"
                )

    def test_vectorized_decision_matches_scalar(self, config):
        from app.engine.composite import _vectorized_decision, compute_decision

        scores = np.array([3.0, -3.0, 0.0, np.nan, 1.5, -1.5])
        vectorized = _vectorized_decision(scores, config)
        for i, s in enumerate(scores):
            scalar = compute_decision(
                float(s) if not np.isnan(s) else float("nan"), config
            )
            assert vectorized[i] == scalar, (
                f"Mismatch at index {i}: {vectorized[i]} vs {scalar}"
            )

    def test_full_pipeline_consistency(self, config):
        """Run compute_signals on test data and verify key properties."""
        from app.engine.composite import compute_signals

        n = 20
        rng = np.random.RandomState(42)
        df = pd.DataFrame(
            {
                "rsi_norm": rng.randn(n),
                "macd_norm": rng.randn(n),
                "stoch_k_norm": rng.randn(n),
                "atr_norm": rng.randn(n),
                "close_pivot_norm": rng.randn(n),
                "vol_oi_norm": rng.randn(n),
                "macroeco_bonus": rng.uniform(-0.1, 0.1, n),
            }
        )

        result = compute_signals(df, config)

        # All expected columns present
        assert "indicator_value" in result.columns
        assert "momentum" in result.columns
        assert "final_indicator" in result.columns
        assert "decision" in result.columns
        assert "macroeco_score" in result.columns

        # Decisions are valid
        assert set(result["decision"].unique()).issubset({"OPEN", "HEDGE", "MONITOR"})

        # First row momentum is NaN (no previous day)
        assert pd.isna(result["momentum"].iloc[0])

        # macroeco_score = 1.0 + macroeco_bonus
        for i in range(n):
            expected = 1.0 + df["macroeco_bonus"].iloc[i]
            actual = result["macroeco_score"].iloc[i]
            assert abs(actual - expected) < 1e-10


# ---------------------------------------------------------------------------
# H15: output_parser delegates to llm_utils
# ---------------------------------------------------------------------------


class TestOutputParserDelegation:
    """H15: output_parser._extract_json delegates to shared llm_utils."""

    def test_extract_json_handles_markdown(self):
        from scripts.daily_analysis.output_parser import _extract_json

        raw = '```json\n{"decision": "OPEN", "confiance": 3}\n```'
        result = _extract_json(raw)
        assert result["decision"] == "OPEN"

    def test_extract_json_handles_unescaped_newlines(self):
        from scripts.daily_analysis.output_parser import _extract_json

        raw = '{"conclusion": "line1\nline2"}'
        result = _extract_json(raw)
        assert "line1" in result["conclusion"]

    def test_extract_json_raises_on_garbage(self):
        from scripts.daily_analysis.output_parser import _extract_json

        with pytest.raises(ValueError, match="No JSON"):
            _extract_json("this is not json at all")


# ---------------------------------------------------------------------------
# H16: _compute_final_indicator raises on missing data
# ---------------------------------------------------------------------------


class TestComputeFinalIndicatorFailsLoud:
    """H16: Missing indicator data raises RuntimeError, not 0.0/MONITOR."""

    def test_missing_data_raises(self):
        from unittest.mock import MagicMock

        from scripts.daily_analysis.db_analysis_engine import DBAnalysisEngine

        session = MagicMock()
        # Mock execute to return empty result
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session.execute.return_value = mock_result

        engine = DBAnalysisEngine.__new__(DBAnalysisEngine)
        engine._session = session
        engine._config = MagicMock()

        with pytest.raises(RuntimeError, match="No indicator data found"):
            engine._compute_final_indicator(date(2026, 4, 28), "CAN26", 0.05)


# ---------------------------------------------------------------------------
# C5: compass_brief db_reader uses pre-built queries (no f-string SQL)
# ---------------------------------------------------------------------------


class TestCompassBriefQueries:
    """C5: Verify queries are pre-built text() objects, not f-strings."""

    def test_queries_are_text_objects(self):
        from sqlalchemy import TextClause

        from scripts.compass_brief.db_reader import (
            _CONFIDENCE_QUERY,
            _DIRECTION_QUERY,
            _INDICATOR_FULL_QUERY,
            _SCORE_TEXT_QUERY,
        )

        assert isinstance(_INDICATOR_FULL_QUERY, TextClause)
        assert isinstance(_CONFIDENCE_QUERY, TextClause)
        assert isinstance(_DIRECTION_QUERY, TextClause)
        assert isinstance(_SCORE_TEXT_QUERY, TextClause)

    def test_queries_contain_parameterized_date(self):
        from scripts.compass_brief.db_reader import _INDICATOR_FULL_QUERY

        # The query text should contain :target_date (parameterized), not f-string
        query_text = str(_INDICATOR_FULL_QUERY)
        assert ":target_date" in query_text


# ---------------------------------------------------------------------------
# H5: audio_service error discrimination
# ---------------------------------------------------------------------------


class TestAudioServiceErrorDiscrimination:
    """H5: Drive 404 → None, other errors → raise."""

    def test_drive_404_returns_none(self):
        from app.services.audio_service import AudioService

        service = AudioService.__new__(AudioService)
        service.drive_service = MagicMock()
        service._file_cache = {}

        from googleapiclient.errors import HttpError

        resp = MagicMock()
        resp.status = 404
        error = HttpError(resp, b"not found")

        with patch.object(service, "_file_cache", {}):
            with patch("asyncio.to_thread", side_effect=error):
                service.drive_service = MagicMock()
                result = asyncio.run(service.get_audio_file_info(date(2026, 4, 28)))
        assert result is None

    def test_drive_403_raises(self):
        from app.services.audio_service import AudioService

        service = AudioService.__new__(AudioService)
        service.drive_service = MagicMock()
        service._file_cache = {}

        from googleapiclient.errors import HttpError

        resp = MagicMock()
        resp.status = 403
        error = HttpError(resp, b"forbidden")

        with patch("asyncio.to_thread", side_effect=error):
            with pytest.raises(HttpError):
                asyncio.run(service.get_audio_file_info(date(2026, 4, 28)))
