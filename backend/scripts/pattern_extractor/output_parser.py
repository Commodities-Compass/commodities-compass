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


class SegmentExtraction(BaseModel):
    zone: Literal["afrique_ouest", "monde"]
    theme: Literal["production", "transformation", "chocolat", "economie"]
    facts: str = Field(min_length=5)
    causal_chains: list[CausalChain] = Field(default_factory=list)
    sentiment: Literal["haussier", "baissier", "neutre"]
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    entities: list[Entity] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractionOutput(BaseModel):
    segments: list[SegmentExtraction] = Field(min_length=1, max_length=8)


def parse_extraction(data: dict[str, Any]) -> ExtractionOutput:
    """Parse and validate LLM extraction output.

    Raises ValueError on validation failure.
    """
    try:
        return ExtractionOutput.model_validate(data)
    except Exception as e:
        logger.error("Extraction validation failed: %s", e)
        raise ValueError(f"Invalid extraction output: {e}") from e


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
