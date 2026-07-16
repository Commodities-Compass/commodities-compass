"""US-3c: meteo agent English (Ghana) edition.

The EN run writes a native English bulletin as its own `language='en'` row that
coexists with the FR row for the same session. Numeric thresholds are shared
(single source of truth in SeasonalProfile); only the prose is native English.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models.pipeline import PlWeatherObservation
from scripts.meteo_agent.config import (
    build_seasonal_context,
    build_seasonal_context_en,
)
from scripts.meteo_agent.db_writer import (
    DuplicateObservationError,
    write_observation,
)


def _parsed(tag: str) -> dict[str, str]:
    return {
        "texte": f"{tag} bulletin body — flowing narrative well over the two "
        "hundred character minimum so the validator would be satisfied. "
        "Conditions across the Ghana and Ivorian cocoa belt are described here "
        "with the water balances and temperatures woven into the prose.",
        "resume": f"{tag} summary: current diagnosis plus horizon risk and price impact.",
        "mots_cle": f"{tag}, Ghana, main rainy season",
        "impact_synthetiques": "4/10; justified with current and forecast figures",
        "diagnostics": {"Kumasi": "normal", "Takoradi": "degraded"},
    }


class TestSeasonalContextEn:
    def test_en_is_english_and_shares_thresholds(self):
        # July → grande_saison_pluies (main rainy season).
        en = build_seasonal_context_en(7)
        fr = build_seasonal_context(7)
        assert "SEASONAL CONTEXT" in en
        assert "MAIN RAINY SEASON" in en
        assert "brown pod risk" in en
        # No French season prose leaks into the EN block.
        assert "CONTEXTE SAISONNIER" not in en
        assert "pourriture brune" not in en
        # Numeric thresholds identical across languages (shared SeasonalProfile).
        assert "32.0°C" in en and "32.0°C" in fr

    def test_en_surplus_line_only_in_rainy_season(self):
        assert "Water surplus (rainy season)" in build_seasonal_context_en(6)  # rainy
        assert "Water surplus (rainy season)" not in build_seasonal_context_en(1)  # dry


class TestWriteObservationLanguage:
    def test_fr_and_en_rows_coexist_per_date(self, sync_db_session):
        day = date(2026, 5, 11)
        write_observation(
            sync_db_session, _parsed("FR"), observation_date=day, language="fr"
        )
        write_observation(
            sync_db_session, _parsed("EN"), observation_date=day, language="en"
        )

        rows = sync_db_session.execute(
            select(
                PlWeatherObservation.language, PlWeatherObservation.observation
            ).where(PlWeatherObservation.date == day)
        ).all()
        by_lang = {lang: obs for lang, obs in rows}
        assert set(by_lang) == {"fr", "en"}
        assert by_lang["fr"].startswith("FR")
        assert by_lang["en"].startswith("EN")

    def test_en_write_does_not_collide_with_existing_fr(self, sync_db_session):
        day = date(2026, 5, 12)
        write_observation(
            sync_db_session, _parsed("FR"), observation_date=day, language="fr"
        )
        # No --force needed: the en row is a different key, so no duplicate raise.
        en_id = write_observation(
            sync_db_session, _parsed("EN"), observation_date=day, language="en"
        )
        assert en_id is not None

    def test_duplicate_same_language_fails_loud(self, sync_db_session):
        day = date(2026, 5, 13)
        write_observation(
            sync_db_session, _parsed("EN"), observation_date=day, language="en"
        )
        with pytest.raises(DuplicateObservationError, match="language=en"):
            write_observation(
                sync_db_session, _parsed("EN2"), observation_date=day, language="en"
            )

    def test_force_overwrites_same_language_row(self, sync_db_session):
        day = date(2026, 5, 14)
        first = write_observation(
            sync_db_session, _parsed("EN"), observation_date=day, language="en"
        )
        second = write_observation(
            sync_db_session,
            _parsed("EN-UPDATED"),
            observation_date=day,
            language="en",
            force=True,
        )
        assert first == second  # same row updated in place
        obs = sync_db_session.execute(
            select(PlWeatherObservation.observation).where(
                PlWeatherObservation.date == day,
                PlWeatherObservation.language == "en",
            )
        ).scalar_one()
        assert obs.startswith("EN-UPDATED")
