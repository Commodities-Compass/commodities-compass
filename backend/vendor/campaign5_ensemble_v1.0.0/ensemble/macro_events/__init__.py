"""Macro event layer (Campaign 4 Phase 3).

Aggregates LLM-extracted sentiment from `pl_article_segment` (already populated
upstream by the news-extraction pipeline) into a daily macro event signal:
direction, surprise, half-life.

Phase 3's production layer does NOT make live LLM calls in this campaign
session — the sentiment_score column is already LLM-extracted at ingestion
time, and the production `score_today()` for FUTURE dates needs only a
rotated API key (deferred).
"""

from ensemble.macro_events.pipeline import MacroEventLayer, MacroEventScore

__all__ = ["MacroEventLayer", "MacroEventScore"]
