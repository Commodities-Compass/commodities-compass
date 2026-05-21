"""Apply the 4 SQL migrations against a local Postgres, verify schema shape.

Marked ``integration``: requires ``DATABASE_URL_TEST`` env var pointing at a
disposable Postgres (e.g. a Docker container started in CI). Each test runs
the migrations on a unique schema and tears it down.

Validates:
    1. ``pl_model_artifact`` table is created with the expected columns,
       constraints, and indexes.
    2. ``pl_specialist_prediction`` + ``pl_orchestrator_decision`` created
       per CAMPAIGN_5_PROD_DEPLOYMENT.md §4.1 / §4.2.
    3. ``004_seed_pl_algorithm_version.sql`` is idempotent — running it twice
       produces no duplicates.
"""

from __future__ import annotations

import os
from pathlib import Path
import uuid

import pytest


SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _connection_or_skip():
    try:
        import psycopg2  # noqa: WPS433
    except ImportError:
        pytest.skip("psycopg2 not installed")
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST env var not set")
    return psycopg2.connect(url)


def _create_temp_schema(conn) -> str:
    schema = f"c5test_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{schema}"')
        cur.execute(f'SET search_path TO "{schema}", public')
        # Minimal stand-ins for FK targets so the migrations can be applied
        # without the full prod schema available.
        cur.execute("""
            CREATE TABLE pl_algorithm_version (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(64) NOT NULL,
                version VARCHAR(16) NOT NULL,
                horizon VARCHAR(32) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                compute_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                description TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE pl_algorithm_config (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                algorithm_version_id UUID NOT NULL REFERENCES pl_algorithm_version(id),
                parameter_name VARCHAR(128) NOT NULL,
                value TEXT NOT NULL,
                description TEXT,
                UNIQUE (algorithm_version_id, parameter_name)
            )
        """)
        cur.execute("""
            CREATE TABLE ref_contract (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                code VARCHAR(32) NOT NULL UNIQUE
            )
        """)
    conn.commit()
    return schema


def _drop_schema(conn, schema: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()


def _apply(conn, sql_file: Path) -> None:
    with conn.cursor() as cur:
        cur.execute(sql_file.read_text())
    conn.commit()


@pytest.mark.integration
def test_001_creates_pl_model_artifact() -> None:
    conn = _connection_or_skip()
    schema = _create_temp_schema(conn)
    try:
        _apply(conn, SQL_DIR / "001_create_pl_model_artifact.sql")
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{schema}", public')
            cur.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'pl_model_artifact'
            """, (schema,))
            cols = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        assert "payload" in cols and cols["payload"][0] == "bytea"
        assert "sha256" in cols and cols["sha256"][1] == "NO"
        assert "training_month" in cols and cols["training_month"][1] == "YES"
        assert "lib_versions" in cols and cols["lib_versions"][0] == "jsonb"
    finally:
        _drop_schema(conn, schema)
        conn.close()


@pytest.mark.integration
def test_002_003_create_decision_tables() -> None:
    conn = _connection_or_skip()
    schema = _create_temp_schema(conn)
    try:
        _apply(conn, SQL_DIR / "002_create_pl_specialist_prediction.sql")
        _apply(conn, SQL_DIR / "003_create_pl_orchestrator_decision.sql")
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{schema}", public')
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name IN ('pl_specialist_prediction', 'pl_orchestrator_decision')
            """, (schema,))
            assert cur.fetchone()[0] == 2
    finally:
        _drop_schema(conn, schema)
        conn.close()


@pytest.mark.integration
def test_004_seed_is_idempotent() -> None:
    conn = _connection_or_skip()
    schema = _create_temp_schema(conn)
    try:
        # Apply twice; the second application must not create duplicates.
        _apply(conn, SQL_DIR / "004_seed_pl_algorithm_version.sql")
        _apply(conn, SQL_DIR / "004_seed_pl_algorithm_version.sql")
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{schema}", public')
            cur.execute("SELECT COUNT(*) FROM pl_algorithm_version WHERE name = 'ensemble_v1_softgate_wrapper'")
            assert cur.fetchone()[0] == 1
            cur.execute("""
                SELECT COUNT(*) FROM pl_algorithm_config
                WHERE parameter_name LIKE 'cluster_%'
            """)
            assert cur.fetchone()[0] == 14
    finally:
        _drop_schema(conn, schema)
        conn.close()
