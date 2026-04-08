"""Pydantic models for structured extraction output."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

ENTITY_TYPE_ALIASES: dict[str, str] = {
    "org": "org",
    "organisme": "org",
    "organisation": "org",
    "organization": "org",
    "lieu": "lieu",
    "location": "lieu",
    "pays": "lieu",
    "region": "lieu",
    "ville": "lieu",
    "chiffre": "chiffre",
    "nombre": "chiffre",
    "number": "chiffre",
    "montant": "chiffre",
    "pourcentage": "chiffre",
    "produit": "produit",
    "product": "produit",
    "commodity": "produit",
    "matiere_premiere": "produit",
}

DIRECTION_ALIASES: dict[str, str] = {
    "haussier": "haussier",
    "haussiere": "haussier",
    "bullish": "haussier",
    "hausse": "haussier",
    "baissier": "baissier",
    "baissiere": "baissier",
    "bearish": "baissier",
    "baisse": "baissier",
    "neutre": "neutre",
    "neutral": "neutre",
    "stable": "neutre",
}


class CausalChain(BaseModel):
    cause: str
    effect: str
    direction: Literal["haussier", "baissier", "neutre"]

    @field_validator("direction", mode="before")
    @classmethod
    def normalize_direction(cls, v: str) -> str:
        if isinstance(v, str):
            normalized = DIRECTION_ALIASES.get(v.lower().strip())
            if normalized:
                return normalized
        return v


class Entity(BaseModel):
    type: Literal["org", "lieu", "chiffre", "produit"]
    value: str

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, v: str) -> str:
        if isinstance(v, str):
            normalized = ENTITY_TYPE_ALIASES.get(v.lower().strip())
            if normalized:
                return normalized
        return v


ZONE_ALIASES: dict[str, str] = {
    "afrique_ouest": "afrique_ouest",
    "afrique_de_l_ouest": "afrique_ouest",
    "afrique de l'ouest": "afrique_ouest",
    "west_africa": "afrique_ouest",
    "africa": "afrique_ouest",
    "monde": "monde",
    "world": "monde",
    "ameriques": "monde",
    "europe": "monde",
    "asie": "monde",
    "asia": "monde",
    "americas": "monde",
    "international": "monde",
    "global": "monde",
}

THEME_ALIASES: dict[str, str] = {
    "production": "production",
    "cocoa_production": "production",
    "offre": "production",
    "supply": "production",
    "transformation": "transformation",
    "grinding": "transformation",
    "broyage": "transformation",
    "broyages": "transformation",
    "first_transformation": "transformation",
    "premiere_transformation": "transformation",
    "chocolat": "chocolat",
    "chocolate": "chocolat",
    "demande": "chocolat",
    "demand": "chocolat",
    "economie": "economie",
    "economy": "economie",
    "marche": "economie",
    "market": "economie",
    "prix": "economie",
    "finance": "economie",
}


class SegmentExtraction(BaseModel):
    zone: Literal["afrique_ouest", "monde"]
    theme: Literal["production", "transformation", "chocolat", "economie"]
    facts: str = Field(min_length=5)
    causal_chains: list[CausalChain] = Field(default_factory=list)
    sentiment: Literal["haussier", "baissier", "neutre"]
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    entities: list[Entity] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("zone", mode="before")
    @classmethod
    def normalize_zone(cls, v: str) -> str:
        if isinstance(v, str):
            normalized = ZONE_ALIASES.get(v.lower().strip())
            if normalized:
                return normalized
        return v

    @field_validator("theme", mode="before")
    @classmethod
    def normalize_theme(cls, v: str) -> str:
        if isinstance(v, str):
            normalized = THEME_ALIASES.get(v.lower().strip())
            if normalized:
                return normalized
        return v


class ExtractionOutput(BaseModel):
    segments: list[SegmentExtraction] = Field(min_length=1)


def _merge_duplicate_segments(
    segments: list[SegmentExtraction],
) -> list[SegmentExtraction]:
    """Merge segments that share the same zone x theme.

    LLMs sometimes split one zone/theme into multiple segments (e.g. two
    monde/economie entries). We merge them: concatenate facts, combine
    causal chains and entities, average sentiment scores, take min confidence.
    """
    grouped: dict[tuple[str, str], list[SegmentExtraction]] = {}
    for seg in segments:
        key = (seg.zone, seg.theme)
        grouped.setdefault(key, []).append(seg)

    merged: list[SegmentExtraction] = []
    for (zone, theme), group in grouped.items():
        if len(group) == 1:
            merged.append(group[0])
            continue

        logger.info(
            "Merging %d segments for zone=%s theme=%s",
            len(group),
            zone,
            theme,
        )
        all_facts = " | ".join(s.facts for s in group)
        all_chains = [c for s in group for c in s.causal_chains]
        all_entities = [e for s in group for e in s.entities]
        avg_score = sum(s.sentiment_score for s in group) / len(group)
        min_confidence = min(s.confidence for s in group)

        # Majority vote for sentiment direction
        sentiments = [s.sentiment for s in group]
        sentiment = max(set(sentiments), key=sentiments.count)

        merged.append(
            SegmentExtraction(
                zone=zone,
                theme=theme,
                facts=all_facts,
                causal_chains=all_chains,
                entities=all_entities,
                sentiment=sentiment,
                sentiment_score=round(avg_score, 2),
                confidence=min_confidence,
            )
        )
    return merged


def parse_extraction(data: dict[str, Any]) -> ExtractionOutput:
    """Parse, validate, and merge LLM extraction output.

    Raises ValueError on validation failure.
    """
    try:
        raw = ExtractionOutput.model_validate(data)
    except Exception as e:
        logger.error("Extraction validation failed: %s", e)
        raise ValueError(f"Invalid extraction output: {e}") from e

    merged_segments = _merge_duplicate_segments(raw.segments)
    return ExtractionOutput(segments=merged_segments)


def serialize_causal_chains(chains: list[CausalChain]) -> str:
    """Serialize causal chains to JSON string for DB storage."""
    return json.dumps(
        [c.model_dump() for c in chains],
        ensure_ascii=False,
    )


def serialize_entities(entities: list[Entity]) -> str:
    """Serialize entities to JSON string for DB storage."""
    return json.dumps(
        [e.model_dump() for e in entities],
        ensure_ascii=False,
    )
