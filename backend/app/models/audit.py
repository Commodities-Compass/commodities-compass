"""Audit tables for the MVP schema.

Observability and lineage tracking: pipeline runs, LLM calls, data quality checks.
All in public schema with aud_ prefix, ready for eventual schema split.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    DATE,
    DECIMAL,
    INTEGER,
    TEXT,
    TIMESTAMP,
    VARCHAR,
    Boolean,
    ForeignKey,
    Index,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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


class AudAlertEvent(Base):
    """Fired intraday-alert journal (cc-intraday-monitor).

    Append-only. Doubles as the dedup guard: first-cross-only per session is
    enforced by UNIQUE(rule_id, session_date, crossing_seq) — the engine
    INSERTs with ON CONFLICT DO NOTHING, so a manual re-run never re-sends.
    """

    __tablename__ = "aud_alert_event"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_alert_rule.id"), nullable=False
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ref_contract.id"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(DATE, nullable=False)
    # MVP: always 1 (first-cross-only). Re-arm/multi-fire = P2.
    crossing_seq: Mapped[int] = mapped_column(
        INTEGER, nullable=False, server_default="1"
    )
    level_value: Mapped[Decimal] = mapped_column(DECIMAL(15, 6), nullable=False)
    observed_price: Mapped[Decimal] = mapped_column(DECIMAL(15, 6), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    # OPEN/HEDGE/MONITOR at fire time — message context, not a lookup key.
    signal_decision: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    channel: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    delivery_status: Mapped[str] = mapped_column(
        VARCHAR(20), nullable=False, server_default="pending"
    )
    provider_message_id: Mapped[Optional[str]] = mapped_column(VARCHAR(60))
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "rule_id", "session_date", "crossing_seq", name="uq_alert_event_dedup"
        ),
        Index("ix_alert_event_session_date", "session_date"),
    )


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
