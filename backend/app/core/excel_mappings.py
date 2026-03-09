"""
Excel to Database Column Mapping Configuration.

This module contains the mapping between Excel sheets/columns and database tables/columns
for the Commodities Compass data import pipeline.
"""

from app.models import (
    Technicals,
    Indicator,
    MarketResearch,
    WeatherData,
    TestRange,
)


# Excel to Database Column Mapping Configuration
EXCEL_MAPPINGS = {
    "TECHNICALS": {
        "table_model": Technicals,
        "sheet_name": "TECHNICALS",
        "column_mapping": {
            # Excel Column → Database Column
            "Timestamp": "timestamp",
            "CLOSE": "close",
            "HIGH": "high",
            "LOW": "low",
            "VOLUME": "volume",
            "OPEN INTEREST": "open_interest",
            "IMPLIED VOLATILITY": "implied_volatility",
            "STOCK US": "stock_us",
            "COM NET US": "com_net_us",
            "R3": "r3",
            "R2": "r2",
            "R1": "r1",
            "Pivot": "pivot",
            "S1": "s1",
            "S2": "s2",
            "S3": "s3",
            "EMA12": "ema12",
            "EMA26": "ema26",
            "MACD": "macd",
            "SIGNAL": "signal",
            "RSI 14D": "rsi_14d",
            "ATR(14d)": "atr_14d",
            "Limites de Bolinger": "bollinger_width",
            "Gain": "gain_14d",  # Assuming this is 14-day gain
            "Perte": "loss_14d",  # Assuming this is 14-day loss
            "Gain(14d)": "gain_14d",
            "Perte(14d)": "loss_14d",
            "RS": "rs",
            # "RSI(14d)": "rsi_14d",  # Removed: duplicate of RSI 14D
            "Stochastic %K (14)": "stochastic_k_14",
            "Stochastic %D (14)": "stochastic_d_14",
            "Close/Pivot": "close_pivot_ratio",
            "Volatility": "volatility",
            "Volume/OI": "volume_oi_ratio",
            "ATR": "atr",
            "BOLLINGER": "bollinger",
            "BANDE SUP": "bollinger_upper",
            "BANDE INF": "bollinger_lower",
            "DECISION": "decision",
            "CONFIANCE": "confidence",
            "DIRECTION": "direction",
            "SCORE": "score",
            "CONCLUSION": "conclusion",
            "ROW": "row_number",
        },
        "transforms": {
            # Column transformations for data cleaning
            "timestamp": "parse_datetime",
            "close": "parse_decimal",
            "high": "parse_decimal",
            "low": "parse_decimal",
            "volume": "parse_integer",  # US number format with commas
            "open_interest": "parse_integer",  # US number format with commas
            # Pivot points with US comma formatting
            "r3": "parse_decimal",
            "r2": "parse_decimal",
            "r1": "parse_decimal",
            "pivot": "parse_decimal",
            "s1": "parse_decimal",
            "s2": "parse_decimal",
            "s3": "parse_decimal",
            "ema12": "parse_decimal",
            "ema26": "parse_decimal",
            "macd": "parse_decimal",
            "bollinger": "parse_decimal",
            "bollinger_upper": "parse_decimal",
            "bollinger_lower": "parse_decimal",
            "atr_14d": "parse_decimal_from_string",  # May contain formulas
            "atr": "parse_decimal_from_string",  # May contain formulas
            "gain_14d": "parse_decimal_from_string",  # May contain formulas
            "loss_14d": "parse_decimal_from_string",  # May contain formulas
            "close_pivot_ratio": "parse_decimal_from_string",  # May contain formulas
            "row_number": "parse_integer",  # String integer values
        },
    },
    "INDICATOR": {
        "table_model": Indicator,
        "sheet_name": "INDICATOR",
        "column_mapping": {
            "DATE": "date",
            "RSI SCORE": "rsi_score",
            "MACD SCORE": "macd_score",
            "STOCHASTIC SCORE": "stochastic_score",
            "ATR SCORE": "atr_score",
            "# CLOSE/PIVOT": "close_pivot",  # Note: special character
            "VOLUME/OI": "volume_oi",
            "RSI NORM": "rsi_norm",
            "MACD NORM": "macd_norm",
            "STOCH %K NORM": "stoch_k_norm",
            "ATR NORM": "atr_norm",
            "CLOSE/PIVOT NORM": "close_pivot_norm",
            "VOL/OI NORM": "vol_oi_norm",
            "INDICATOR": "indicator",
            "MOMENTUM": "momentum",
            "MACROECO BONUS": "macroeco_bonus",
            "FINAL INDICATOR": "final_indicator",
            "CONCLUSION": "conclusion",
            "MACROECO SCORE": "macroeco_score",
            "ECO": "eco",
            "FINAL INDICATOR DERNIER": "final_indicator_previous",
            "DERNIER MACROECO": "previous_macroeco",
            "DERNIER RSI": "previous_rsi",
            "DERNIER MACD": "previous_macd",
            "DERNIER %K": "previous_k",
            "DERNIER ATR": "previous_atr",
            "DERNIER CLOSE/PIVOT": "previous_close_pivot",
            "DERNIER VOL/OI": "previous_vol_oi",
            "DERNIERE CONCLUSION": "previous_conclusion",
        },
        "transforms": {"date": "parse_datetime"},
    },
    "BIBLIO_ALL": {
        "table_model": MarketResearch,
        "sheet_name": "BIBLIO_ALL",
        "column_mapping": {
            "DATE": "date",
            "AUTEUR": "author",
            "RESUME": "summary",
            "MOTS-CLE": "keywords",
            "IMPACT SYNTHETIQUES": "impact_synthesis",
            "DATE TEXT": "date_text",
        },
        "transforms": {"date": "parse_datetime"},
    },
    "METEO_ALL": {
        "table_model": WeatherData,
        "sheet_name": "METEO_ALL",
        "column_mapping": {
            "DATE": "date",
            "TEXTE": "text",
            "RESUME": "summary",
            "MOTS-CLE": "keywords",
            "IMPACT SYNTHETIQUES": "impact_synthesis",
        },
        "transforms": {"date": "parse_datetime"},
    },
    "TEST RANGE": {
        "table_model": TestRange,
        "sheet_name": "TEST RANGE",
        "column_mapping": {
            "indicator": "indicator",
            "range_low": "range_low",
            "range_high": "range_high",
            "area": "area",
        },
        "transforms": {
            "range_low": "parse_decimal",
            "range_high": "parse_decimal",
        },
    },
}


def get_sheet_mapping(sheet_name: str) -> dict:
    """Get mapping configuration for a specific sheet."""
    for mapping in EXCEL_MAPPINGS.values():
        if mapping["sheet_name"] == sheet_name:
            return mapping
    return None  # type: ignore[return-value]


def get_model_for_sheet(sheet_name: str):
    """Get the SQLAlchemy model class for a specific sheet."""
    mapping = get_sheet_mapping(sheet_name)
    return mapping["table_model"] if mapping else None


def get_column_mapping_for_sheet(sheet_name: str) -> dict:
    """Get the column mapping for a specific sheet."""
    mapping = get_sheet_mapping(sheet_name)
    return mapping["column_mapping"] if mapping else {}


def get_all_sheet_names() -> list:
    """Get all Excel sheet names that have mappings."""
    return [mapping["sheet_name"] for mapping in EXCEL_MAPPINGS.values()]
