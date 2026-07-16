"""US-4a — English (Ghana) ensemble brief.

Three layers, matching the change:
  * Catalog — every specialist carries a native-EN label/description distinct
    from the FR pair, and the per-language accessors switch correctly.
  * Renderer — the brief scaffolding (section headers, field labels, editorial
    framing, dates, theme convergence) is native-EN in EN mode and unchanged in
    FR mode; no cross-language leak either way.
  * db_reader — the language-scoped reads (ensemble narrative, press, meteo)
    return the requested language's row, while the persistence read stays pinned
    to the canonical FR series.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from scripts.compass_brief_ensemble.brief_generator import (
    UnsafeBriefContentError,
    _format_date,
    _render_theme_convergence,
    render_brief,
)
from scripts.compass_brief_ensemble.config import (
    FILENAME_PATTERN,
    FILENAME_PATTERN_EN,
    filename_for,
)
from app.models.pipeline import PlSeasonalScore
from scripts.compass_brief_ensemble.db_reader import (
    EnsembleBriefData,
    EnsembleBriefDataMissingError,
    SpecialistVote,
    _read_ensemble_row,
    _read_meteo,
    _read_persistence_days,
    _read_press,
    _read_seasonal_trajectory,
)
from scripts.compass_brief_ensemble.specialist_catalog import SPECIALIST_CATALOG
from tests.factories import (
    make_pl_algorithm_version,
    make_pl_fundamental_article,
    make_pl_indicator_daily,
    make_pl_weather_observation,
    make_ref_commodity,
    make_ref_contract,
    make_ref_exchange,
)


# ── Test data builder ──────────────────────────────────────────────────────
def _make_brief_data(**overrides) -> EnsembleBriefData:
    base = {
        "target_date": date(2026, 7, 15),
        "decision": "MONITOR",
        "confidence": 3,
        "confidence_rationale": "Technical SUPPORT, Macro SUPPORT",
        "direction": "NEUTRE",
        "conclusion": "> Stay flexible.\n> A SURVEILLER: RSI",
        "eco": "Cocoa held firm on steady grind demand.",
        "soft_gate_decision": "OPEN",
        "wrapper_active": True,
        "net_score": Decimal("0.4"),
        "n_committed_specialists": 6,
        "fired_running_acc": False,
        "fired_trend": True,
        "fired_dispersion": False,
        "fired_three_way": False,
        "running_acc_5d": Decimal("0.8"),
        "realized_return_5d": Decimal("0.01"),
        "anomaly_score_z": Decimal("0.2"),
        "macro_direction": 1,
        "macro_surprise": Decimal("0.1"),
        "macro_half_life_days": 5,
        "prior_open": Decimal("0.5"),
        "prior_hedge": Decimal("0.2"),
        "prior_monitor": Decimal("0.3"),
        "winter_vote_signed": 1,
        "spring_vote_signed": -1,
        "specialists": [
            SpecialistVote(name="exp_optim_002", pred="OPEN", window_months=6),
            SpecialistVote(name="exp_optim_011", pred="OPEN", window_months=6),
            SpecialistVote(name="exp_optim_017_bear_4", pred="HEDGE", window_months=6),
        ],
        "press_summary": "Ghana COCOBOD raised the farm-gate price.",
        "press_impact": "Supportive for supply retention.",
        "press_sentiment": "cautiously bullish",
        "meteo_summary": "Dry spell easing across Ashanti.",
        "meteo_impact": "Neutral for pod set.",
        "meteo_trajectory": "",
        "technicals_snapshot": "Session close : 2026-07-14\n  CLOSE=2,438.00",
        "persistence_days": 2,
        "ytd_score": Decimal("12.34"),
    }
    return EnsembleBriefData(**(base | overrides))


# ── Catalog parity ─────────────────────────────────────────────────────────
class TestCatalogEnglishParity:
    def test_every_specialist_has_native_english_pair(self):
        assert len(SPECIALIST_CATALOG) == 14
        for name, profile in SPECIALIST_CATALOG.items():
            assert profile.label_en, f"{name} missing label_en"
            assert profile.description_en, f"{name} missing description_en"
            # Native rewrite, not a copy of the FR field.
            assert profile.label_en != profile.label, f"{name} label_en == label"
            assert profile.description_en != profile.description, (
                f"{name} description_en == description"
            )

    def test_english_descriptions_have_no_french_diacritics(self):
        # A cheap proxy for "actually rewritten in English": the EN strings must
        # not carry French-only accented characters.
        french_only = set("àâçéèêëîïôùûœ")
        for name, profile in SPECIALIST_CATALOG.items():
            leaked = french_only & set(profile.label_en.lower())
            leaked |= french_only & set(profile.description_en.lower())
            assert not leaked, f"{name} EN text carries French chars: {leaked}"

    def test_accessors_switch_by_language(self):
        profile = SPECIALIST_CATALOG["exp_optim_002"]
        assert profile.label_for("en") == profile.label_en
        assert profile.label_for("fr") == profile.label
        assert profile.description_for("en") == profile.description_en
        # Unknown language falls back to FR (never raises).
        assert profile.label_for("de") == profile.label


# ── Renderer — bilingual, no leak ──────────────────────────────────────────
class TestBilingualRender:
    def test_english_brief_uses_english_scaffolding(self):
        out = render_brief(_make_brief_data(), language="en")
        for token in (
            "II — EDITORIAL READ",
            "III — ECO & PRESS REVIEW",
            "V — TECHNICAL SNAPSHOT — LAST SESSION",
            "VI — OPERATIONAL RECOMMENDATIONS",
            "Confidence",
            "YTD performance",
            "Headline read of the day:",
            "Other reads converge on this verdict",
            "Decision horizon: 4 to 5 trading sessions",
            "15 July 2026",
            "Trend reader — benchmark",  # EN specialist label
        ):
            assert token in out, f"EN brief missing {token!r}"

    def test_english_brief_has_no_french_scaffolding(self):
        out = render_brief(_make_brief_data(), language="en")
        for token in (
            "LECTURE ÉDITORIALE",
            "Confiance",
            "Horizon décisionnel",
            "Lecture phare du jour",
            "D'autres lectures convergent",
            "RECOMMANDATIONS OPÉRATIONNELLES",
            "Lecteur de tendance",  # FR specialist label
            "juillet",
        ):
            assert token not in out, f"EN brief leaked FR token {token!r}"

    def test_french_brief_unchanged(self):
        out = render_brief(_make_brief_data(), language="fr")
        assert "II — LECTURE ÉDITORIALE" in out
        assert "Confiance          :" in out
        assert "Lecture phare du jour :" in out
        assert "Horizon décisionnel : 4 à 5 sessions boursières" in out
        assert "15 juillet 2026" in out
        # No EN scaffolding bleeds into the FR brief.
        assert "EDITORIAL READ" not in out
        assert "YTD performance" not in out

    def test_default_language_is_french(self):
        assert render_brief(_make_brief_data()) == render_brief(
            _make_brief_data(), language="fr"
        )

    def test_no_engaged_fallback_is_localised(self):
        data = _make_brief_data(
            specialists=[
                SpecialistVote(name="exp_optim_002", pred="MONITOR", window_months=6)
            ]
        )
        assert "the market is watched without taking a position" in render_brief(
            data, language="en"
        )
        assert "le marché est observé sans prise de position" in render_brief(
            data, language="fr"
        )

    def test_redaction_guard_still_fires_in_english(self):
        # The fail-loud engine-leak guard is language-independent.
        data = _make_brief_data(eco="The soft-gate leans bullish today.")
        with pytest.raises(UnsafeBriefContentError):
            render_brief(data, language="en")


# ── Theme convergence grammar ──────────────────────────────────────────────
class TestThemeConvergence:
    def test_single_theme_english(self):
        others = [SpecialistVote(name="exp_optim_011", pred="OPEN", window_months=6)]
        out = _render_theme_convergence(others, "en")
        assert out == "Other reads converge on this verdict, including a macro read."

    def test_two_themes_english_uses_and(self):
        others = [
            SpecialistVote(name="exp_optim_011", pred="OPEN", window_months=6),  # macro
            SpecialistVote(
                name="exp_optim_017_bear_4", pred="HEDGE", window_months=6
            ),  # fx
        ]
        out = _render_theme_convergence(others, "en")
        assert out.startswith("Other reads converge on this verdict — ")
        assert " and " in out
        assert "a macro read" in out and "an FX read" in out

    def test_single_theme_french_unchanged(self):
        others = [SpecialistVote(name="exp_optim_011", pred="OPEN", window_months=6)]
        out = _render_theme_convergence(others, "fr")
        assert (
            out
            == "D'autres lectures convergent sur ce verdict, dont une lecture macro."
        )


# ── Filename + date ────────────────────────────────────────────────────────
class TestFilenameAndDate:
    def test_filename_english_gets_en_suffix(self):
        assert filename_for("20260715", "en") == FILENAME_PATTERN_EN.format(
            date="20260715"
        )
        assert filename_for("20260715", "en").endswith("-Ensemble-EN.txt")

    def test_filename_french_and_unknown_default_plain(self):
        expected = FILENAME_PATTERN.format(date="20260715")
        assert filename_for("20260715", "fr") == expected
        assert filename_for("20260715", "de") == expected  # fail-safe default

    def test_format_date_months(self):
        d = date(2026, 7, 15)
        assert _format_date(d, "en") == "15 July 2026"
        assert _format_date(d, "fr") == "15 juillet 2026"


# ── db_reader language filtering ───────────────────────────────────────────
def _seed_ref_chain(session: Session):
    exchange = make_ref_exchange(code="ICE_EU_I18N")
    session.add(exchange)
    session.flush()
    commodity = make_ref_commodity(exchange.id, code="CC_I18N")
    session.add(commodity)
    session.flush()
    contract = make_ref_contract(commodity.id, code="CAU26I")
    session.add(contract)
    algo = make_pl_algorithm_version(name="ensemble_i18n", version="1.0.0")
    session.add(algo)
    session.flush()
    return contract.id, algo.id


class TestDbReaderLanguageFilter:
    def test_ensemble_row_returns_requested_language(self, sync_db_session: Session):
        contract_id, algo_id = _seed_ref_chain(sync_db_session)
        d = date(2026, 7, 14)
        sync_db_session.add(
            make_pl_indicator_daily(
                contract_id, algo_id, date=d, language="fr", eco="FR eco"
            )
        )
        sync_db_session.add(
            make_pl_indicator_daily(
                contract_id, algo_id, date=d, language="en", eco="EN eco"
            )
        )
        sync_db_session.flush()

        assert (
            _read_ensemble_row(sync_db_session, d, contract_id, algo_id, "en")["eco"]
            == "EN eco"
        )
        assert (
            _read_ensemble_row(sync_db_session, d, contract_id, algo_id, "fr")["eco"]
            == "FR eco"
        )

    def test_ensemble_row_missing_language_fails_loud(self, sync_db_session: Session):
        contract_id, algo_id = _seed_ref_chain(sync_db_session)
        d = date(2026, 7, 14)
        sync_db_session.add(
            make_pl_indicator_daily(
                contract_id, algo_id, date=d, language="fr", eco="FR only"
            )
        )
        sync_db_session.flush()
        with pytest.raises(EnsembleBriefDataMissingError):
            _read_ensemble_row(sync_db_session, d, contract_id, algo_id, "en")

    def test_press_and_meteo_read_requested_language(self, sync_db_session: Session):
        _seed_ref_chain(sync_db_session)
        d = date(2026, 7, 14)
        sync_db_session.add(
            make_pl_fundamental_article(
                date=d, language="fr", is_active=True, summary="revue FR"
            )
        )
        sync_db_session.add(
            make_pl_fundamental_article(
                date=d, language="en", is_active=True, summary="EN review"
            )
        )
        sync_db_session.add(
            make_pl_weather_observation(date=d, language="fr", summary="météo FR")
        )
        sync_db_session.add(
            make_pl_weather_observation(date=d, language="en", summary="EN weather")
        )
        sync_db_session.flush()

        assert _read_press(sync_db_session, d, "en")[0] == "EN review"
        assert _read_press(sync_db_session, d, "fr")[0] == "revue FR"
        assert _read_meteo(sync_db_session, d, "en")[0] == "EN weather"
        assert _read_meteo(sync_db_session, d, "fr")[0] == "météo FR"

    def test_seasonal_trajectory_translates_season_slug(self, sync_db_session: Session):
        # The in-progress season of the latest campaign (FR slug in the DB) must
        # render as a native English season name in EN mode, and de-underscored
        # French in FR mode. pl_seasonal_score has no language dimension.
        for loc, score in (("Takoradi", "3.0"), ("Soubre", "4.5")):
            sync_db_session.add(
                PlSeasonalScore(
                    campaign="2026-27",
                    season_name="grande_saison_pluies",
                    location_name=loc,
                    months_covered="juil-sept (en cours)",
                    start_date=date(2026, 7, 1),
                    end_date=date(2026, 9, 30),
                    score=score,
                    days_heavy_rain=5,
                )
            )
        sync_db_session.flush()

        en = _read_seasonal_trajectory(sync_db_session, date(2026, 7, 15), "en")
        assert "main rainy season" in en
        assert "grande" not in en and "_" not in en.split(":")[0]

        fr = _read_seasonal_trajectory(sync_db_session, date(2026, 7, 15), "fr")
        assert "grande saison pluies" in fr

    def test_persistence_pinned_to_fr_ignores_en_rows(self, sync_db_session: Session):
        # FR series: MONITOR on T & T-1, OPEN on T-2 → persistence must be 2.
        # EN rows (also MONITOR on T & T-1) must NOT inflate the count — the
        # read is pinned to language='fr'. Without the pin the interleaved
        # fr+en window would count 4 before the OPEN break.
        contract_id, algo_id = _seed_ref_chain(sync_db_session)
        for d, dec, lang in (
            (date(2026, 7, 14), "MONITOR", "fr"),
            (date(2026, 7, 13), "MONITOR", "fr"),
            (date(2026, 7, 10), "OPEN", "fr"),
            (date(2026, 7, 14), "MONITOR", "en"),
            (date(2026, 7, 13), "MONITOR", "en"),
        ):
            sync_db_session.add(
                make_pl_indicator_daily(
                    contract_id, algo_id, date=d, decision=dec, language=lang
                )
            )
        sync_db_session.flush()

        persistence = _read_persistence_days(
            sync_db_session, date(2026, 7, 14), contract_id, algo_id, "MONITOR"
        )
        assert persistence == 2
