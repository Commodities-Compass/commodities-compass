"""Audit tables for the MVP schema.

Observability and lineage tracking: pipeline runs, LLM calls, data quality checks.
All in public schema with aud_ prefix, ready for eventual schema split.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    DECIMAL,
    INTEGER,
    TEXT,
    TIMESTAMP,
    VARCHAR,
    Boolean,
    ForeignKey,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AudPipelineRun(Base):
    """Pipeline execution log. Tracks each scraper, ETL, or analysis run."""

    __tablename__ = "aud_pipeline_run"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pipeline_name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP)
    status: Mapped[str] = mapped_column(VARCHAR(50), nullable=False, default="running")
    error: Mapped[Optional[str]] = mapped_column(TEXT)
    row_count: Mapped[Optional[int]] = mapped_column(INTEGER)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class AudLlmCall(Base):
    """LLM invocation audit. Every call to GPT/Claude/Gemini is tracked."""

    __tablename__ = "aud_llm_call"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pipeline_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("aud_pipeline_run.id")
    )
    provider: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    model: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    prompt: Mapped[Optional[str]] = mapped_column(TEXT)
    response: Mapped[Optional[str]] = mapped_column(TEXT)
    input_tokens: Mapped[Optional[int]] = mapped_column(INTEGER)
    output_tokens: Mapped[Optional[int]] = mapped_column(INTEGER)
    cost_usd: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 6))
    latency_ms: Mapped[Optional[int]] = mapped_column(INTEGER)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())


class AudDataQualityCheck(Base):
    """Data validation results per pipeline run."""

    __tablename__ = "aud_data_quality_check"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pipeline_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("aud_pipeline_run.id")
    )
    check_name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[Optional[str]] = mapped_column(TEXT)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
