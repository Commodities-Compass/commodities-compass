"""Generates a structured text brief from Sheets data.

Produces a single .txt file with yesterday + today sections,
mirroring the content of the Looker Studio PDFs for NotebookLM consumption.
"""

from datetime import datetime

from scripts.compass_brief.sheets_reader import BriefData, DayData

MOIS_FR = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}

SEP = "=" * 70


def generate_brief(data: BriefData) -> str:
    """Generate the full brief text from BriefData."""
    lines: list[str] = []

    # Header
    lines.append(SEP)
    lines.append("COMMODITIES COMPASS — DAILY BRIEF")
    lines.append(f"Date : {_format_date(data.today.date)}")
    lines.append(SEP)
    lines.append("")

    # Yesterday
    lines.append(_day_section(data.yesterday, "VEILLE"))
    lines.append("")

    # Today
    lines.append(_day_section(data.today, "AUJOURD'HUI"))

    return "\n".join(lines)


def _day_section(day: DayData, label: str) -> str:
    lines: list[str] = []

    lines.append(SEP)
    lines.append(f"DONNÉES DU {_format_date(day.date)} ({label})")
    lines.append(SEP)
    lines.append("")

    # --- Signal / Decision ---
    conclusion = day.indicators.get("CONCLUSION", "")
    if conclusion:
        lines.append(f"SIGNAL DU JOUR : {conclusion}")
    if day.decision:
        lines.append(
            f"Décision : {day.decision} | Confiance : {day.confiance}/5 "
            f"| Direction : {day.direction}"
        )
    lines.append("")

    # --- Technical data ---
    lines.append("--- DONNÉES TECHNIQUES ---")
    t = day.technicals
    lines.append(
        f"CLOSE : {t.get('CLOSE', '')}    HIGH : {t.get('HIGH', '')}    LOW : {t.get('LOW', '')}"
    )
    lines.append(
        f"VOLUME : {t.get('VOLUME', '')}    OI : {t.get('OI', '')}    IV : {t.get('IV', '')}"
    )
    lines.append(
        f"RSI 14D : {t.get('RSI 14D', '')}    MACD : {t.get('MACD', '')}    Signal MACD : {t.get('SIGNAL', '')}"
    )
    lines.append(
        f"%K : {t.get('%K', '')}    %D : {t.get('%D', '')}    ATR : {t.get('ATR', '')}"
    )
    lines.append(
        f"PIVOT : {t.get('PIVOT', '')}    S1 : {t.get('S1', '')}    R1 : {t.get('R1', '')}"
    )
    lines.append(f"EMA9 : {t.get('EMA9', '')}    EMA21 : {t.get('EMA21', '')}")
    lines.append(f"Bollinger : [{t.get('BANDE INF', '')} — {t.get('BANDE SUP', '')}]")
    lines.append(
        f"STOCK US : {t.get('STOCK US', '')}    COM NET US : {t.get('COM NET US', '')}"
    )
    lines.append("")

    # --- Indicator scores ---
    ind = day.indicators
    lines.append("--- SCORES INDICATEURS ---")
    lines.append(
        f"RSI : {ind.get('RSI SCORE', '')}    MACD : {ind.get('MACD SCORE', '')}    Stochastic : {ind.get('STOCHASTIC SCORE', '')}"
    )
    lines.append(
        f"ATR : {ind.get('ATR SCORE', '')}    Close/Pivot : {ind.get('CLOSE/PIVOT', '')}    Volume/OI : {ind.get('VOLUME/OI', '')}"
    )
    lines.append(
        f"Indicateur agrégé : {ind.get('FINAL INDICATOR', '')}    Score Macroéco : {ind.get('MACROECO SCORE', '')}"
    )
    lines.append("")

    # --- Macro eco analysis ---
    eco = ind.get("ECO", "")
    if eco:
        lines.append("--- ANALYSE MACROÉCONOMIQUE ---")
        lines.append(eco)
        lines.append("")

    # --- Recommendations ---
    if day.score_text:
        lines.append("--- RECOMMANDATIONS DU JOUR ---")
        lines.append(day.score_text)
        lines.append("")

    # --- Press review ---
    if day.press_review:
        lines.append("--- PRESS REVIEW ---")
        lines.append(day.press_review)
        lines.append("")

    # --- Meteo ---
    if day.meteo_resume or day.meteo_impact:
        lines.append("--- MÉTÉO ---")
        if day.meteo_resume:
            lines.append(day.meteo_resume)
        if day.meteo_impact:
            lines.append(f"Impact : {day.meteo_impact}")
        lines.append("")

    return "\n".join(lines)


def _format_date(date_str: str) -> str:
    """Convert MM/DD/YYYY -> '20 février 2026'."""
    try:
        dt = datetime.strptime(date_str, "%m/%d/%Y")
        return f"{dt.day} {MOIS_FR[dt.month]} {dt.year}"
    except (ValueError, TypeError):
        return date_str
