"""Tests for the daily analysis DB reader (unit tests, no DB required).

Tests the data formatting and variable mapping logic.
"""

from __future__ import annotations


from scripts.daily_analysis.db_reader import _format_value, _DB_TO_PROMPT_VARS


class TestFormatValue:
    def test_none(self) -> None:
        assert _format_value(None) == ""

    def test_integer(self) -> None:
        assert _format_value(10463) == "10463"

    def test_float_clean(self) -> None:
        assert _format_value(2057.0) == "2057"

    def test_float_decimal(self) -> None:
        assert _format_value(0.5625) == "0.5625"

    def test_string(self) -> None:
        assert _format_value("test") == "test"

    def test_negative(self) -> None:
        assert _format_value(-12301) == "-12301"

    def test_small_float(self) -> None:
        # Should not use scientific notation
        result = _format_value(0.0004)
        assert "e" not in result.lower()


class TestPromptVariableMapping:
    def test_all_21_variables_mapped(self) -> None:
        """Should have exactly 21 DB→prompt variable mappings."""
        assert len(_DB_TO_PROMPT_VARS) == 21

    def test_raw_ohlcv_mapped(self) -> None:
        assert _DB_TO_PROMPT_VARS["close"] == "CLOSE"
        assert _DB_TO_PROMPT_VARS["high"] == "HIGH"
        assert _DB_TO_PROMPT_VARS["low"] == "LOW"
        assert _DB_TO_PROMPT_VARS["volume"] == "VOL"
        assert _DB_TO_PROMPT_VARS["oi"] == "OI"

    def test_derived_indicators_mapped(self) -> None:
        assert _DB_TO_PROMPT_VARS["macd"] == "MACD"
        assert _DB_TO_PROMPT_VARS["rsi_14d"] == "RSI14"
        assert _DB_TO_PROMPT_VARS["stochastic_k_14"] == "%K"
        assert _DB_TO_PROMPT_VARS["atr_14d"] == "ATR"

    def test_bollinger_mapped(self) -> None:
        assert _DB_TO_PROMPT_VARS["bollinger_upper"] == "BSUP"
        assert _DB_TO_PROMPT_VARS["bollinger_lower"] == "BBINF"

    def test_tod_yes_suffix_format(self) -> None:
        """Verify that the mapping produces valid TOD/YES keys for prompts."""
        for db_col, prompt_var in _DB_TO_PROMPT_VARS.items():
            tod_key = f"{prompt_var}TOD"
            # Keys should not contain characters that break str.format()
            assert "{" not in tod_key
            assert "}" not in tod_key
            # %K and %D will be converted to pctK/pctD by build_call2_prompt
