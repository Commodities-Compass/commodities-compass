"""US-0 locale foundation: content is language-scoped and never leaks across
languages. The three content tables can hold FR + EN rows for the same date,
and the serving layer must return exactly the requested language — never FR
content under an EN label (or vice versa).
"""

from datetime import date

from app.models.pipeline import PlFundamentalArticle, PlWeatherObservation
from app.services.dashboard_service import (
    get_latest_market_research,
    get_latest_weather_data,
)


class TestWeatherLanguage:
    async def test_fr_and_en_coexist_and_filter(self, db_session):
        d = date(2026, 3, 13)
        db_session.add(
            PlWeatherObservation(date=d, observation="Bulletin FR", language="fr")
        )
        db_session.add(
            PlWeatherObservation(date=d, observation="EN bulletin", language="en")
        )
        await db_session.flush()

        fr = await get_latest_weather_data(db_session, d, language="fr")
        en = await get_latest_weather_data(db_session, d, language="en")

        assert fr is not None and fr["text"] == "Bulletin FR"
        assert en is not None and en["text"] == "EN bulletin"

    async def test_no_cross_language_leak(self, db_session):
        d = date(2026, 3, 14)
        db_session.add(
            PlWeatherObservation(date=d, observation="Only FR", language="fr")
        )
        await db_session.flush()

        assert await get_latest_weather_data(db_session, d, language="fr") is not None
        # Never serve FR content under the EN label.
        assert await get_latest_weather_data(db_session, d, language="en") is None

    async def test_default_language_is_french(self, db_session):
        d = date(2026, 3, 15)
        db_session.add(
            PlWeatherObservation(date=d, observation="Defaut FR", language="fr")
        )
        await db_session.flush()

        # No explicit language → 'fr' default matches existing content (retro-compat).
        result = await get_latest_weather_data(db_session, d)
        assert result is not None and result["text"] == "Defaut FR"


class TestArticleLanguage:
    async def test_fr_and_en_coexist_same_provider(self, db_session):
        d = date(2026, 3, 13)
        db_session.add(
            PlFundamentalArticle(
                date=d,
                llm_provider="openai",
                language="fr",
                is_active=True,
                summary="Resume FR",
            )
        )
        db_session.add(
            PlFundamentalArticle(
                date=d,
                llm_provider="openai",
                language="en",
                is_active=True,
                summary="EN summary",
            )
        )
        await db_session.flush()

        fr = await get_latest_market_research(db_session, d, language="fr")
        en = await get_latest_market_research(db_session, d, language="en")

        assert fr is not None and fr["summary"] == "Resume FR"
        assert en is not None and en["summary"] == "EN summary"

    async def test_no_cross_language_leak(self, db_session):
        d = date(2026, 3, 14)
        db_session.add(
            PlFundamentalArticle(
                date=d,
                llm_provider="openai",
                language="fr",
                is_active=True,
                summary="FR only",
            )
        )
        await db_session.flush()

        assert await get_latest_market_research(db_session, d, language="en") is None
