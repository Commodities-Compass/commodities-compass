"""Tests for Phase 2 scraper db_writer modules."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.models.audit import AudLlmCall
from app.models.pipeline import (
    PlContractDataDaily,
    PlFundamentalArticle,
    PlWeatherObservation,
)
from app.models.reference import RefCommodity, RefContract, RefExchange
from scripts.contract_resolver import (
    ContractResolverError,
    resolve_active,
    resolve_active_code,
    resolve_by_code,
)


# ---------------------------------------------------------------------------
# Shared fixture: exchange → commodity → contract chain (sync)
# ---------------------------------------------------------------------------


@pytest.fixture()
def ref_chain_sync(sync_db_session):
    """Create reference chain for sync session tests."""
    exchange = RefExchange(
        code="IFEU", name="ICE Futures Europe", timezone="Europe/London"
    )
    sync_db_session.add(exchange)
    sync_db_session.flush()

    commodity = RefCommodity(code="CC", name="London Cocoa #7", exchange_id=exchange.id)
    sync_db_session.add(commodity)
    sync_db_session.flush()

    contract = RefContract(
        commodity_id=commodity.id,
        code="CAK26",
        contract_month="2026-05",
        expiry_date=date(2026, 5, 15),
        is_active=True,
    )
    sync_db_session.add(contract)
    sync_db_session.flush()

    return {"exchange": exchange, "commodity": commodity, "contract": contract}


# ---------------------------------------------------------------------------
# Contract Resolver
# ---------------------------------------------------------------------------


class TestContractResolver:
    def test_resolve_by_code(self, sync_db_session, ref_chain_sync):
        contract_id = resolve_by_code(sync_db_session, "CAK26")
        assert contract_id == ref_chain_sync["contract"].id

    def test_resolve_by_code_not_found(self, sync_db_session, ref_chain_sync):
        with pytest.raises(ContractResolverError, match="Contract not found"):
            resolve_by_code(sync_db_session, "NONEXISTENT")

    def test_resolve_active(self, sync_db_session, ref_chain_sync):
        contract_id = resolve_active(sync_db_session)
        assert contract_id == ref_chain_sync["contract"].id

    def test_resolve_active_none(self, sync_db_session):
        with pytest.raises(ContractResolverError, match="No active contract"):
            resolve_active(sync_db_session)

    def test_resolve_active_code(self, sync_db_session, ref_chain_sync):
        code = resolve_active_code(sync_db_session)
        assert code == "CAK26"

    def test_resolve_active_code_none(self, sync_db_session):
        with pytest.raises(ContractResolverError, match="No active contract"):
            resolve_active_code(sync_db_session)


# ---------------------------------------------------------------------------
# Barchart DB Writer
# ---------------------------------------------------------------------------


class TestBarchartDbWriter:
    def _make_data(self, **overrides):
        defaults = {
            "timestamp": datetime(2026, 3, 17, 21, 0, 0),
            "close": 8500.0,
            "high": 8600.0,
            "low": 8400.0,
            "volume": 5000,
            "open_interest": 40000,
            "implied_volatility": 48.99,
        }
        return {**defaults, **overrides}

    def test_insert_new_row(self, sync_db_session, ref_chain_sync):
        from scripts.barchart_scraper.db_writer import write_ohlcv

        write_ohlcv(sync_db_session, self._make_data(), "CAK26")

        row = sync_db_session.execute(select(PlContractDataDaily)).scalar_one()
        assert row.date == date(2026, 3, 17)
        assert row.close == Decimal("8500.0")
        assert row.high == Decimal("8600.0")
        assert row.low == Decimal("8400.0")
        assert row.volume == 5000
        assert row.oi == 40000
        assert row.implied_volatility == Decimal("48.99") / 100

    def test_upsert_existing_row(self, sync_db_session, ref_chain_sync):
        from scripts.barchart_scraper.db_writer import write_ohlcv

        contract_id = ref_chain_sync["contract"].id
        existing = PlContractDataDaily(
            date=date(2026, 3, 17),
            contract_id=contract_id,
            close=Decimal("8000"),
        )
        sync_db_session.add(existing)
        sync_db_session.flush()

        write_ohlcv(sync_db_session, self._make_data(), "CAK26")

        rows = sync_db_session.execute(select(PlContractDataDaily)).scalars().all()
        assert len(rows) == 1
        assert rows[0].close == Decimal("8500.0")

    def test_dry_run_no_write(self, sync_db_session, ref_chain_sync):
        from scripts.barchart_scraper.db_writer import write_ohlcv

        write_ohlcv(sync_db_session, self._make_data(), "CAK26", dry_run=True)

        rows = sync_db_session.execute(select(PlContractDataDaily)).scalars().all()
        assert len(rows) == 0

    def test_iv_none_handled(self, sync_db_session, ref_chain_sync):
        from scripts.barchart_scraper.db_writer import write_ohlcv

        write_ohlcv(
            sync_db_session,
            self._make_data(implied_volatility=None),
            "CAK26",
        )

        row = sync_db_session.execute(select(PlContractDataDaily)).scalar_one()
        assert row.implied_volatility is None

    def test_invalid_contract_raises(self, sync_db_session, ref_chain_sync):
        from scripts.barchart_scraper.db_writer import write_ohlcv

        with pytest.raises(ContractResolverError):
            write_ohlcv(sync_db_session, self._make_data(), "INVALID")


# ---------------------------------------------------------------------------
# ICE Stocks DB Writer
# ---------------------------------------------------------------------------


class TestIceStocksDbWriter:
    def test_inserts_observation(self, sync_db_session, ref_chain_sync):
        from scripts.ice_stocks_scraper.db_writer import write_stock_us

        _ = ref_chain_sync  # fixture ensures ref tables seeded
        write_stock_us(sync_db_session, 150000, report_date=date(2026, 3, 17))
        sync_db_session.flush()

        row = sync_db_session.execute(
            text(
                "SELECT region, report_date, value_native, unit_native, "
                "value_tonnes, source FROM pl_stock_observation"
            )
        ).fetchone()
        assert row.region == "us"
        assert row.report_date == date(2026, 3, 17)
        assert row.value_native == Decimal("150000")
        assert row.unit_native == "tonnes"
        assert row.value_tonnes == Decimal("150000")
        assert row.source == "ice_us_report41"

    def test_updates_specific_report_date(self, sync_db_session, ref_chain_sync):
        from scripts.ice_stocks_scraper.db_writer import write_stock_us

        _ = ref_chain_sync
        write_stock_us(sync_db_session, 140000, report_date=date(2026, 3, 14))
        write_stock_us(sync_db_session, 160000, report_date=date(2026, 3, 17))
        sync_db_session.flush()

        rows = sync_db_session.execute(
            text(
                "SELECT report_date, value_tonnes FROM pl_stock_observation "
                "ORDER BY report_date"
            )
        ).fetchall()
        assert [(r.report_date, r.value_tonnes) for r in rows] == [
            (date(2026, 3, 14), Decimal("140000")),
            (date(2026, 3, 17), Decimal("160000")),
        ]

    def test_upsert_on_same_report_date_overwrites(
        self, sync_db_session, ref_chain_sync
    ):
        from scripts.ice_stocks_scraper.db_writer import write_stock_us

        _ = ref_chain_sync
        write_stock_us(sync_db_session, 150000, report_date=date(2026, 3, 17))
        write_stock_us(sync_db_session, 152000, report_date=date(2026, 3, 17))
        sync_db_session.flush()

        rows = sync_db_session.execute(
            text("SELECT value_tonnes FROM pl_stock_observation")
        ).fetchall()
        assert len(rows) == 1
        assert rows[0].value_tonnes == Decimal("152000")

    def test_dry_run_no_write(self, sync_db_session, ref_chain_sync):
        from scripts.ice_stocks_scraper.db_writer import write_stock_us

        _ = ref_chain_sync
        write_stock_us(
            sync_db_session, 150000, report_date=date(2026, 3, 17), dry_run=True
        )

        count = sync_db_session.execute(
            text("SELECT count(*) FROM pl_stock_observation")
        ).scalar_one()
        assert count == 0


# ---------------------------------------------------------------------------
# CFTC DB Writer
# ---------------------------------------------------------------------------


class TestCftcDbWriter:
    @staticmethod
    def _make_obs(report_date: date, prod_net: int = -5000):
        from scripts.cftc_scraper.scraper import CocoaCotUsObservation

        return CocoaCotUsObservation(
            release_date=report_date + timedelta(days=3),
            report_date=report_date,
            open_interest=162_798,
            prod_merc_long=max(prod_net, 0),
            prod_merc_short=abs(min(prod_net, 0)),
            swap_long=10_000,
            swap_short=5_000,
            swap_spreading=1_000,
            m_money_long=20_000,
            m_money_short=15_000,
            m_money_spreading=2_000,
            other_rept_long=3_000,
            other_rept_short=2_000,
            other_rept_spreading=500,
            non_rept_long=4_000,
            non_rept_short=3_500,
        )

    def test_inserts_row(self, sync_db_session, ref_chain_sync):
        from scripts.cftc_scraper.db_writer import upsert_cot_us_weekly

        _ = ref_chain_sync
        obs = self._make_obs(date(2026, 3, 17), prod_net=-5000)
        upsert_cot_us_weekly(sync_db_session, obs)
        sync_db_session.flush()

        row = sync_db_session.execute(
            text(
                "SELECT release_date, report_date, prod_merc_long, prod_merc_short, "
                "prod_merc_net, m_money_long, m_money_short, m_money_net, "
                "open_interest FROM pl_cot_us_weekly"
            )
        ).fetchone()
        assert row.release_date == date(2026, 3, 20)
        assert row.report_date == date(2026, 3, 17)
        assert row.prod_merc_long == 0
        assert row.prod_merc_short == 5000
        assert row.prod_merc_net == -5000
        assert row.m_money_long == 20000
        assert row.m_money_net == 5000
        assert row.open_interest == 162_798

    def test_upsert_overwrites_on_same_release_date(
        self, sync_db_session, ref_chain_sync
    ):
        from scripts.cftc_scraper.db_writer import upsert_cot_us_weekly

        _ = ref_chain_sync
        upsert_cot_us_weekly(
            sync_db_session, self._make_obs(date(2026, 3, 17), prod_net=-5000)
        )
        upsert_cot_us_weekly(
            sync_db_session, self._make_obs(date(2026, 3, 17), prod_net=-7000)
        )
        sync_db_session.flush()

        rows = sync_db_session.execute(
            text("SELECT prod_merc_net FROM pl_cot_us_weekly")
        ).fetchall()
        assert len(rows) == 1
        assert rows[0].prod_merc_net == -7000

    def test_dry_run_no_write(self, sync_db_session, ref_chain_sync):
        from scripts.cftc_scraper.db_writer import upsert_cot_us_weekly

        _ = ref_chain_sync
        upsert_cot_us_weekly(
            sync_db_session, self._make_obs(date(2026, 3, 17)), dry_run=True
        )

        count = sync_db_session.execute(
            text("SELECT count(*) FROM pl_cot_us_weekly")
        ).scalar_one()
        assert count == 0


# ---------------------------------------------------------------------------
# Press Review DB Writer
# ---------------------------------------------------------------------------


class TestPressReviewDbWriter:
    def test_insert_article(self, sync_db_session):
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_article

        parsed = {
            "resume": "Le marche du cacao reste sous pression",
            "mots_cle": "cocoa; rally; 8500 GBP/t",
            "impact_synthetiques": "Impact haussier modere",
        }
        article_id = write_article(
            sync_db_session, Provider.OPENAI, parsed, article_date=date(2026, 3, 17)
        )
        assert article_id is not None

        row = sync_db_session.execute(select(PlFundamentalArticle)).scalar_one()
        assert row.summary == "Le marche du cacao reste sous pression"
        assert row.keywords == "cocoa; rally; 8500 GBP/t"
        assert row.impact_synthesis == "Impact haussier modere"
        assert row.llm_provider == "openai"
        assert row.source == "LLM Agent (o4-mini)"
        assert row.category == "macro"

    def test_insert_llm_call(self, sync_db_session):
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_llm_call

        write_llm_call(
            sync_db_session,
            Provider.CLAUDE,
            usage={"input_tokens": 5000, "output_tokens": 1200},
            latency_ms=3400,
        )

        row = sync_db_session.execute(select(AudLlmCall)).scalar_one()
        assert row.provider == "claude"
        assert row.model == "claude-sonnet-4-5-20250929"
        assert row.input_tokens == 5000
        assert row.output_tokens == 1200
        assert row.latency_ms == 3400

    def test_multiple_providers(self, sync_db_session):
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_article

        parsed = {"resume": "Test", "mots_cle": "test", "impact_synthetiques": "test"}
        write_article(
            sync_db_session, Provider.CLAUDE, parsed, article_date=date(2026, 3, 17)
        )
        write_article(
            sync_db_session, Provider.OPENAI, parsed, article_date=date(2026, 3, 17)
        )
        write_article(
            sync_db_session, Provider.GEMINI, parsed, article_date=date(2026, 3, 17)
        )

        rows = sync_db_session.execute(select(PlFundamentalArticle)).scalars().all()
        assert len(rows) == 3
        providers = {r.llm_provider for r in rows}
        assert providers == {"claude", "openai", "gemini"}

    def test_duplicate_date_provider_raises(self, sync_db_session):
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import (
            DuplicateArticleError,
            write_article,
        )

        parsed = {"resume": "Test", "mots_cle": "test", "impact_synthetiques": "test"}

        write_article(
            sync_db_session, Provider.OPENAI, parsed, article_date=date(2026, 3, 17)
        )

        with pytest.raises(DuplicateArticleError, match="already exists"):
            write_article(
                sync_db_session,
                Provider.OPENAI,
                parsed,
                article_date=date(2026, 3, 17),
            )

        rows = sync_db_session.execute(select(PlFundamentalArticle)).scalars().all()
        assert len(rows) == 1

    def test_dry_run_no_write(self, sync_db_session):
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_article

        parsed = {"resume": "Test", "mots_cle": "test", "impact_synthetiques": "test"}
        result = write_article(sync_db_session, Provider.OPENAI, parsed, dry_run=True)
        assert result is None

        rows = sync_db_session.execute(select(PlFundamentalArticle)).scalars().all()
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# Press Review Theme Sentiments — soft-fill
# ---------------------------------------------------------------------------


class TestPressReviewThemeSentimentsSoftFill:
    """Guarantees all 4 themes are written every day so the dashboard
    always renders 4 sentiment gauges. Missing themes are filled with a
    neutral fallback and a Sentry warning is emitted.
    """

    def _make_article(self, sync_db_session, article_date=date(2026, 5, 5)):
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_article

        parsed = {
            "resume": "x" * 50,
            "mots_cle": "k",
            "impact_synthetiques": "i",
        }
        article_id = write_article(
            sync_db_session, Provider.OPENAI, parsed, article_date=article_date
        )
        assert article_id is not None
        return article_id

    def test_all_four_themes_present_inserts_four_rows(self, sync_db_session):
        from app.models.pipeline import PlArticleSegment
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_theme_sentiments

        article_id = self._make_article(sync_db_session)
        theme_sentiments = {
            "production": {
                "score": 0.5,
                "confidence": 0.8,
                "rationale": "Arrivages en hausse",
            },
            "chocolat": {
                "score": -0.3,
                "confidence": 0.7,
                "rationale": "Demande chocolat en repli",
            },
            "transformation": {
                "score": 0.2,
                "confidence": 0.6,
                "rationale": "Broyages stables",
            },
            "economie": {"score": 0.0, "confidence": 0.4, "rationale": "USD neutre"},
        }

        count = write_theme_sentiments(
            sync_db_session,
            article_id,
            date(2026, 5, 5),
            theme_sentiments,
            Provider.OPENAI,
        )

        assert count == 4
        rows = sync_db_session.execute(select(PlArticleSegment)).scalars().all()
        assert {r.theme for r in rows} == {
            "production",
            "chocolat",
            "transformation",
            "economie",
        }

    def test_missing_themes_are_soft_filled_with_neutral(
        self, sync_db_session, monkeypatch
    ):
        from app.models.pipeline import PlArticleSegment
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import (
            NEUTRAL_FALLBACK_CONFIDENCE,
            NEUTRAL_FALLBACK_RATIONALE,
            NEUTRAL_FALLBACK_SCORE,
            write_theme_sentiments,
        )

        captures: list[dict] = []
        monkeypatch.setattr(
            "scripts.press_review_agent.db_writer.sentry_sdk.capture_message",
            lambda msg, **kw: captures.append({"msg": msg, **kw}),
        )
        contexts: list[dict] = []
        monkeypatch.setattr(
            "scripts.press_review_agent.db_writer.sentry_sdk.set_context",
            lambda name, ctx: contexts.append({"name": name, "ctx": ctx}),
        )

        article_id = self._make_article(sync_db_session)
        # LLM only emitted 2 themes — transformation and economie are missing.
        partial = {
            "production": {
                "score": 0.5,
                "confidence": 0.8,
                "rationale": "Arrivages en hausse",
            },
            "chocolat": {
                "score": -0.3,
                "confidence": 0.7,
                "rationale": "Demande chocolat en repli",
            },
        }

        count = write_theme_sentiments(
            sync_db_session, article_id, date(2026, 5, 5), partial, Provider.OPENAI
        )

        assert count == 4
        rows = sync_db_session.execute(select(PlArticleSegment)).scalars().all()
        assert {r.theme for r in rows} == {
            "production",
            "chocolat",
            "transformation",
            "economie",
        }

        filled_rows = [r for r in rows if r.theme in ("transformation", "economie")]
        for row in filled_rows:
            assert float(row.sentiment_score) == NEUTRAL_FALLBACK_SCORE
            assert float(row.confidence) == NEUTRAL_FALLBACK_CONFIDENCE
            assert row.facts == NEUTRAL_FALLBACK_RATIONALE
            assert row.sentiment == "neutral"

        assert len(captures) == 1
        assert "press_review_partial_themes" in captures[0]["msg"]
        assert captures[0]["level"] == "warning"
        assert any(c["name"] == "press_review_partial_themes" for c in contexts)
        ctx = next(
            c["ctx"] for c in contexts if c["name"] == "press_review_partial_themes"
        )
        assert set(ctx["missing_themes"]) == {"transformation", "economie"}
        assert ctx["provider"] == "openai"
        assert ctx["article_date"] == "2026-05-05"

    def test_empty_theme_sentiments_produces_four_neutral_rows(
        self, sync_db_session, monkeypatch
    ):
        from app.models.pipeline import PlArticleSegment
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_theme_sentiments

        monkeypatch.setattr(
            "scripts.press_review_agent.db_writer.sentry_sdk.capture_message",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "scripts.press_review_agent.db_writer.sentry_sdk.set_context",
            lambda *a, **kw: None,
        )

        article_id = self._make_article(sync_db_session)
        count = write_theme_sentiments(
            sync_db_session, article_id, date(2026, 5, 5), {}, Provider.OPENAI
        )

        assert count == 4
        rows = sync_db_session.execute(select(PlArticleSegment)).scalars().all()
        assert all(r.sentiment == "neutral" for r in rows)
        assert all(float(r.sentiment_score) == 0.0 for r in rows)

    def test_dry_run_does_not_write(self, sync_db_session, monkeypatch):
        from app.models.pipeline import PlArticleSegment
        from scripts.press_review_agent.config import Provider
        from scripts.press_review_agent.db_writer import write_theme_sentiments

        monkeypatch.setattr(
            "scripts.press_review_agent.db_writer.sentry_sdk.capture_message",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "scripts.press_review_agent.db_writer.sentry_sdk.set_context",
            lambda *a, **kw: None,
        )

        article_id = self._make_article(sync_db_session)
        count = write_theme_sentiments(
            sync_db_session,
            article_id,
            date(2026, 5, 5),
            {"production": {"score": 0.5, "confidence": 0.8, "rationale": "x"}},
            Provider.OPENAI,
            dry_run=True,
        )
        assert count == 0
        rows = sync_db_session.execute(select(PlArticleSegment)).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# Meteo DB Writer
# ---------------------------------------------------------------------------


class TestMeteoDbWriter:
    def test_insert_observation(self, sync_db_session):
        from scripts.meteo_agent.db_writer import write_observation

        parsed = {
            "texte": "Analyse complete des conditions meteorologiques",
            "resume": "Pluies abondantes a Daloa, stress hydrique a Kumasi",
            "mots_cle": "pluie, stress hydrique, Daloa, Kumasi",
            "impact_synthetiques": "7/10; conditions globalement favorables",
        }
        obs_id = write_observation(
            sync_db_session, parsed, observation_date=date(2026, 3, 17)
        )
        assert obs_id is not None

        row = sync_db_session.execute(select(PlWeatherObservation)).scalar_one()
        assert row.observation == "Analyse complete des conditions meteorologiques"
        assert row.summary == "Pluies abondantes a Daloa, stress hydrique a Kumasi"
        assert row.keywords == "pluie, stress hydrique, Daloa, Kumasi"
        assert row.impact_assessment == "7/10; conditions globalement favorables"
        assert row.date == date(2026, 3, 17)

    def test_insert_llm_call(self, sync_db_session):
        from scripts.meteo_agent.db_writer import write_llm_call

        write_llm_call(
            sync_db_session,
            usage={"input_tokens": 3000, "output_tokens": 800},
            latency_ms=2100,
        )

        row = sync_db_session.execute(select(AudLlmCall)).scalar_one()
        assert row.provider == "openai"
        assert row.model == "gpt-4.1"
        assert row.input_tokens == 3000
        assert row.output_tokens == 800
        assert row.latency_ms == 2100

    def test_duplicate_date_raises(self, sync_db_session):
        from scripts.meteo_agent.db_writer import (
            DuplicateObservationError,
            write_observation,
        )

        parsed = {
            "texte": "First observation",
            "resume": "First summary",
            "mots_cle": "v1",
            "impact_synthetiques": "5/10",
        }

        write_observation(sync_db_session, parsed, observation_date=date(2026, 3, 17))

        with pytest.raises(DuplicateObservationError, match="already exists"):
            write_observation(
                sync_db_session, parsed, observation_date=date(2026, 3, 17)
            )

        rows = sync_db_session.execute(select(PlWeatherObservation)).scalars().all()
        assert len(rows) == 1

    def test_dry_run_no_write(self, sync_db_session):
        from scripts.meteo_agent.db_writer import write_observation

        parsed = {
            "texte": "Test",
            "resume": "Test",
            "mots_cle": "test",
            "impact_synthetiques": "test",
        }
        result = write_observation(sync_db_session, parsed, dry_run=True)
        assert result is None

        rows = sync_db_session.execute(select(PlWeatherObservation)).scalars().all()
        assert len(rows) == 0
