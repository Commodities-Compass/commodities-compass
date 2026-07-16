"""US-3c: press review English (Ghana) edition.

The EN run writes a native English summary of the SAME sources as its own
`language='en'` article row, coexisting with the FR row per (date, provider).
Article SEGMENTS (pl_article_segment) stay owned by the FR run — they feed the
language-agnostic ensemble macro signal and must not be double-counted, so the
EN run discards its theme_sentiments (enforced in main.py).
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models.pipeline import PlFundamentalArticle
from scripts.press_review_agent.config import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_EN,
    Provider,
)
from scripts.press_review_agent.db_writer import (
    DuplicateArticleError,
    write_article,
)


def _parsed(tag: str) -> dict[str, str]:
    return {
        "resume": f"{tag} review body summarising supply, fundamentals and market tone.",
        "mots_cle": f"{tag}; London CAN26 2,531 GBP/t; grindings down",
        "impact_synthetiques": f"{tag} net impact paragraph for a cocoa hedger.",
        "theme_sentiments": {
            "production": {"score": 0.2, "confidence": 0.5, "rationale": "x"},
            "chocolat": {"score": 0.0, "confidence": 0.3, "rationale": "y"},
            "transformation": {"score": -0.1, "confidence": 0.4, "rationale": "z"},
            "economie": {"score": 0.1, "confidence": 0.6, "rationale": "w"},
        },
    }


class TestSystemPromptEn:
    def test_en_prompt_is_english_and_keeps_contract(self):
        assert "English-language press review" in SYSTEM_PROMPT_EN
        assert "Write in English" in SYSTEM_PROMPT_EN
        # Output contract identical: same JSON keys the parser/validator expect.
        for key in (
            '"resume"',
            '"mots_cle"',
            '"impact_synthetiques"',
            '"theme_sentiments"',
        ):
            assert key in SYSTEM_PROMPT_EN
        # EN section labels, not the French ones.
        assert "SUPPLY" in SYSTEM_PROMPT_EN and "FUNDAMENTALS" in SYSTEM_PROMPT_EN
        assert "FONDAMENTAUX" not in SYSTEM_PROMPT_EN
        # Grounding (D3 exception) preserved.
        assert "GROUNDING" in SYSTEM_PROMPT_EN

    def test_fr_prompt_still_french(self):
        assert "French-language press review" in SYSTEM_PROMPT
        assert "Write in French" in SYSTEM_PROMPT


class TestWriteArticleLanguage:
    def test_fr_and_en_rows_coexist_per_date_provider(self, sync_db_session):
        day = date(2026, 5, 11)
        write_article(
            sync_db_session,
            Provider.OPENAI,
            _parsed("FR"),
            article_date=day,
            language="fr",
        )
        write_article(
            sync_db_session,
            Provider.OPENAI,
            _parsed("EN"),
            article_date=day,
            language="en",
        )
        rows = sync_db_session.execute(
            select(PlFundamentalArticle.language, PlFundamentalArticle.summary).where(
                PlFundamentalArticle.date == day
            )
        ).all()
        by_lang = {lang: summ for lang, summ in rows}
        assert set(by_lang) == {"fr", "en"}
        assert by_lang["fr"].startswith("FR")
        assert by_lang["en"].startswith("EN")

    def test_en_write_does_not_collide_with_existing_fr(self, sync_db_session):
        day = date(2026, 5, 12)
        write_article(
            sync_db_session,
            Provider.OPENAI,
            _parsed("FR"),
            article_date=day,
            language="fr",
        )
        en_id = write_article(
            sync_db_session,
            Provider.OPENAI,
            _parsed("EN"),
            article_date=day,
            language="en",
        )
        assert en_id is not None

    def test_duplicate_same_language_fails_loud(self, sync_db_session):
        day = date(2026, 5, 13)
        write_article(
            sync_db_session,
            Provider.OPENAI,
            _parsed("EN"),
            article_date=day,
            language="en",
        )
        with pytest.raises(DuplicateArticleError, match="language=en"):
            write_article(
                sync_db_session,
                Provider.OPENAI,
                _parsed("EN2"),
                article_date=day,
                language="en",
            )

    def test_force_overwrites_same_language_row(self, sync_db_session):
        day = date(2026, 5, 14)
        first = write_article(
            sync_db_session,
            Provider.OPENAI,
            _parsed("EN"),
            article_date=day,
            language="en",
        )
        second = write_article(
            sync_db_session,
            Provider.OPENAI,
            _parsed("EN-UPDATED"),
            article_date=day,
            language="en",
            force=True,
        )
        assert first == second
        summary = sync_db_session.execute(
            select(PlFundamentalArticle.summary).where(
                PlFundamentalArticle.date == day,
                PlFundamentalArticle.language == "en",
            )
        ).scalar_one()
        assert summary.startswith("EN-UPDATED")
