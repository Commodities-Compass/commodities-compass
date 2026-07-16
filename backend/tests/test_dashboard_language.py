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


class TestStressHistoryLanguage:
    """Review fix: get_stress_history filters by language, else the LIMIT window
    collapses to half the dates once EN weather rows coexist."""

    async def test_language_filter_prevents_window_collapse(self, db_session):
        from datetime import timedelta

        from app.services.dashboard_service import get_stress_history

        base = date(2026, 5, 20)
        for i in range(3):
            d = base - timedelta(days=i)
            db_session.add(
                PlWeatherObservation(
                    date=d,
                    language="fr",
                    observation="fr",
                    diagnostics={"Kumasi": "stress"},
                )
            )
            db_session.add(
                PlWeatherObservation(
                    date=d,
                    language="en",
                    observation="en",
                    diagnostics={"Kumasi": "normal"},
                )
            )
        await db_session.flush()

        hist = await get_stress_history(
            db_session, days=3, target_date=base, language="fr"
        )
        kumasi = next(h for h in hist if h["location_name"] == "Kumasi")
        # 3 distinct fr sessions — not collapsed by fr+en duplicates; and the
        # fr diagnostics ("stress"), never the en row's "normal".
        assert kumasi["history"] == ["stress", "stress", "stress"]
        assert kumasi["current_status"] == "stress"


class TestYtdLanguageDedup:
    """Review fix (high): the YTD decision query pins language='fr'. Without it,
    EN indicator rows double each date and corrupt the horizon-indexed score."""

    async def test_en_rows_do_not_change_ytd(self, db_session):
        from datetime import timedelta
        from decimal import Decimal

        from app.models.pipeline import (
            PlAlgorithmVersion,
            PlContractDataDaily,
            PlIndicatorDaily,
        )
        from app.models.reference import RefCommodity, RefContract, RefExchange
        from app.services.dashboard_service import calculate_ytd_performance

        ex = RefExchange(code="IFEU-ytd", name="ICE", timezone="Europe/London")
        db_session.add(ex)
        await db_session.flush()
        com = RefCommodity(code="CC-ytd", name="Cocoa", exchange_id=ex.id)
        db_session.add(com)
        await db_session.flush()
        contract = RefContract(
            commodity_id=com.id,
            code="CAK26-ytd",
            contract_month="2026-05",
            expiry_date=date(2026, 5, 15),
            is_active=True,
        )
        db_session.add(contract)
        legacy = PlAlgorithmVersion(
            name="legacy",
            version="1.0.1",
            horizon="short_term",
            is_active=True,
            compute_enabled=True,
            description="l",
        )
        db_session.add(legacy)
        await db_session.flush()

        ref = date(2026, 5, 20)
        dates = [ref - timedelta(days=i) for i in range(9)][::-1]
        for i, d in enumerate(dates):
            db_session.add(
                PlContractDataDaily(
                    date=d,
                    contract_id=contract.id,
                    close=Decimal(str(3000 + i * 20)),
                    high=Decimal("1"),
                    low=Decimal("1"),
                    volume=1,
                    oi=1000,
                )
            )
            db_session.add(
                PlIndicatorDaily(
                    date=d,
                    contract_id=contract.id,
                    algorithm_version_id=legacy.id,
                    language="fr",
                    decision="OPEN",
                )
            )
        await db_session.flush()
        ytd_fr = await calculate_ytd_performance(db_session, ref)

        # Add EN copies (identical decision) — must be filtered out.
        for d in dates:
            db_session.add(
                PlIndicatorDaily(
                    date=d,
                    contract_id=contract.id,
                    algorithm_version_id=legacy.id,
                    language="en",
                    decision="OPEN",
                )
            )
        await db_session.flush()
        ytd_both = await calculate_ytd_performance(db_session, ref)

        assert ytd_fr == ytd_both, (
            "EN rows must not affect the language-agnostic YTD score"
        )
