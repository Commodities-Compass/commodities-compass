"""extract stock + CFTC US into dedicated tables with publication-date provenance

Revision ID: r2m3n4o5p6q7
Revises: q1l2m3n4o5p6
Create Date: 2026-05-27

Why
---
``pl_contract_data_daily`` was mixing two orthogonal cadences:
  * OHLCV / IV — daily (real new data every business day)
  * stock_us / stock_eu_bags60kg / com_net_us — weekly (US: ~daily but often
    flat; EU: Tuesday; CFTC: Friday)

The legacy writers stamped each weekly value onto every daily session row,
overwriting on each scraper run and discarding the publisher's actual
``report_date``. Consequence: the dashboard could not distinguish a fresh
publication from a 6-day-old stale value, and the units between EU (bags) and
US (tonnes) were mixed in the same response payload.

What this migration does (atomic)
---------------------------------
1. CREATE ``pl_stock_observation`` — generic ICE certified stocks, keyed on
   (region, report_date, contract_market). Stores both native unit and a
   normalized ``value_tonnes`` so consumers can compare regions without
   re-implementing the bag→tonne math.
2. CREATE ``pl_cot_us_weekly`` — mirrors ``pl_cot_eu_weekly`` for the CFTC US
   COT report (Producer/Merchant + Managed Money decomposition, Friday
   release / Tuesday snapshot).
3. BACKFILL both tables from the legacy columns of ``pl_contract_data_daily``.
   Heuristic: group consecutive identical values per (contract, column) and
   keep the FIRST date a value appeared = best-available proxy for the true
   ``report_date``. ~1 business-day error is acceptable (Mon overwrite of
   prev-Friday value at most). Real future ingestion will carry the
   publisher's actual date going forward.
4. RECREATE ``v_contract_data_chained`` without the 3 legacy columns. The C5
   ensemble loader selects them today but no specialist consumes them
   (cf cartographie 2026-05-27).
5. DROP the 3 legacy columns from ``pl_contract_data_daily``. Atomic switch:
   rollback is ``alembic downgrade -1`` which restores columns + replays
   backfill in reverse.

Backfill provenance note
------------------------
The first ICE-US backfill row will have ``report_date = MIN(date) where stock_us
IS NOT NULL`` per contract — likely several days late vs the true ICE
publication. This is acceptable because (a) downstream consumers always use
"latest on/before target_date" semantics, (b) we cannot reconstruct true dates
from the lossy legacy storage, and (c) all NEW data captures the real
``report_date`` from the source.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "r2m3n4o5p6q7"
down_revision = "q1l2m3n4o5p6"
branch_labels = None
depends_on = None


# Conversion constants (must match positioning_service)
EU_BAG_KG = 60
KG_PER_TONNE = 1000


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------
def upgrade() -> None:
    _create_pl_stock_observation()
    _create_pl_cot_us_weekly()
    _backfill_pl_stock_observation()
    _backfill_pl_cot_us_weekly()
    _recreate_view_without_legacy_columns()
    _drop_legacy_columns()


def _create_pl_stock_observation() -> None:
    """Generic ICE certified stocks table — region-agnostic, multi-source.

    UNIQUE on (region, report_date, contract_market) — one observation per
    publisher per snapshot date. Indexed on (region, contract_market,
    report_date DESC) for the dashboard's "latest on/before target_date"
    pattern.
    """
    op.create_table(
        "pl_stock_observation",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # 'us' (ICE US Report 41) or 'eu' (Barchart IC345DRW mirroring ICE EU).
        sa.Column("region", sa.VARCHAR(10), nullable=False),
        # Snapshot date as published by the source (the publisher's date, not
        # the scraper's run date).
        sa.Column("report_date", sa.DATE(), nullable=False),
        # Value as published, in the source's native unit.
        sa.Column("value_native", sa.DECIMAL(15, 6), nullable=False),
        # 'tonnes' (ICE US) or 'bags_60kg' (Barchart EU).
        sa.Column("unit_native", sa.VARCHAR(15), nullable=False),
        # Normalized to tonnes so cross-region ratios and gauges can render
        # without re-implementing the bag→tonne conversion at each consumer.
        sa.Column("value_tonnes", sa.DECIMAL(15, 6), nullable=False),
        # Multi-market ready ('cocoa' for now, extensible later).
        sa.Column(
            "contract_market",
            sa.VARCHAR(50),
            nullable=False,
            server_default="cocoa",
        ),
        # Provenance tag: which scraper/source produced this row.
        sa.Column("source", sa.VARCHAR(40), nullable=False),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "region IN ('us', 'eu')", name="ck_stock_observation_region"
        ),
        sa.CheckConstraint(
            "unit_native IN ('tonnes', 'bags_60kg')",
            name="ck_stock_observation_unit_native",
        ),
        sa.UniqueConstraint(
            "region",
            "report_date",
            "contract_market",
            name="uq_stock_observation",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_stock_observation_lookup",
        "pl_stock_observation",
        ["region", "contract_market", sa.text("report_date DESC")],
        if_not_exists=True,
    )


def _create_pl_cot_us_weekly() -> None:
    """CFTC US COT report — mirrors ``pl_cot_eu_weekly`` schema.

    Both ``prod_merc_net`` and ``m_money_net`` are GENERATED columns
    (Postgres auto-computed). m_money_* and other_rept_* are nullable today
    because the current ``cftc_scraper`` only extracts Producer/Merchant
    — schema is future-proof for when we extend the parser.
    """
    op.create_table(
        "pl_cot_us_weekly",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # When CFTC published the report (Friday for Tuesday snapshot).
        sa.Column("release_date", sa.DATE(), nullable=False),
        # The Tuesday the report covers.
        sa.Column("report_date", sa.DATE(), nullable=False),
        sa.Column(
            "contract_market",
            sa.VARCHAR(50),
            nullable=False,
            server_default="cocoa",
        ),
        # Producer / Merchant / Processor / User (commercial hedgers)
        sa.Column("prod_merc_long", sa.INTEGER(), nullable=True),
        sa.Column("prod_merc_short", sa.INTEGER(), nullable=True),
        sa.Column(
            "prod_merc_net",
            sa.INTEGER(),
            sa.Computed("prod_merc_long - prod_merc_short", persisted=True),
        ),
        # Managed Money (non-commercial speculative — future R&D parity with EU)
        sa.Column("m_money_long", sa.INTEGER(), nullable=True),
        sa.Column("m_money_short", sa.INTEGER(), nullable=True),
        sa.Column(
            "m_money_net",
            sa.INTEGER(),
            sa.Computed("m_money_long - m_money_short", persisted=True),
        ),
        # Other Reportables + Non-Reportable (audit-only categories)
        sa.Column("other_rept_long", sa.INTEGER(), nullable=True),
        sa.Column("other_rept_short", sa.INTEGER(), nullable=True),
        sa.Column("non_rept_long", sa.INTEGER(), nullable=True),
        sa.Column("non_rept_short", sa.INTEGER(), nullable=True),
        # Total OI on the report — for %OI normalization downstream
        sa.Column("open_interest", sa.INTEGER(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("release_date", "contract_market", name="uq_cot_us_weekly"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_cot_us_weekly_report_date",
        "pl_cot_us_weekly",
        ["report_date"],
        if_not_exists=True,
    )


def _backfill_pl_stock_observation() -> None:
    """Backfill stock observations from the legacy ``pl_contract_data_daily``.

    Heuristic per (region, contract): walk through all rows ordered by date,
    keep the FIRST date a new value appears (consecutive duplicates are the
    same publication overwritten by the daily scraper). This collapses
    ~5 daily rows per real EU publication down to 1 historical observation
    with ~1 business-day error on report_date — acceptable because the
    consumer pattern is "latest on/before target_date".

    Uses ``DISTINCT ON`` + lag/lead window via grouping by change-point.

    For ``stock_us``: native unit is tonnes (the scraper converted at
    ingest). value_tonnes = value_native.

    For ``stock_eu_bags60kg``: native unit is 60kg bags. value_tonnes is
    computed via bags × 60 / 1000.

    ON CONFLICT DO NOTHING because re-running upgrade after a partial
    failure should be idempotent (the new rows ingested by the refactored
    scrapers will have higher-precision dates and win on UPSERT in the
    application layer).
    """
    # US — value already in tonnes.
    op.execute(
        sa.text(
            """
            INSERT INTO pl_stock_observation
                (region, report_date, value_native, unit_native, value_tonnes,
                 contract_market, source)
            SELECT
                'us'              AS region,
                first_date        AS report_date,
                value             AS value_native,
                'tonnes'          AS unit_native,
                value             AS value_tonnes,
                'cocoa'           AS contract_market,
                'backfill_pcdd'   AS source
            FROM (
                SELECT
                    value,
                    MIN(date) AS first_date
                FROM (
                    SELECT
                        date,
                        stock_us AS value,
                        stock_us
                            - LAG(stock_us)
                                OVER (PARTITION BY contract_id ORDER BY date)
                            AS delta
                    FROM pl_contract_data_daily
                    WHERE stock_us IS NOT NULL
                ) AS marked
                WHERE delta IS NULL OR delta <> 0
                GROUP BY value
            ) AS first_occurrences
            ON CONFLICT (region, report_date, contract_market) DO NOTHING;
            """
        )
    )

    # EU — native value in 60kg bags; normalize to tonnes.
    op.execute(
        sa.text(
            f"""
            INSERT INTO pl_stock_observation
                (region, report_date, value_native, unit_native, value_tonnes,
                 contract_market, source)
            SELECT
                'eu'              AS region,
                first_date        AS report_date,
                value             AS value_native,
                'bags_60kg'       AS unit_native,
                value * {EU_BAG_KG} / {KG_PER_TONNE}::numeric AS value_tonnes,
                'cocoa'           AS contract_market,
                'backfill_pcdd'   AS source
            FROM (
                SELECT
                    value,
                    MIN(date) AS first_date
                FROM (
                    SELECT
                        date,
                        stock_eu_bags60kg AS value,
                        stock_eu_bags60kg
                            - LAG(stock_eu_bags60kg)
                                OVER (PARTITION BY contract_id ORDER BY date)
                            AS delta
                    FROM pl_contract_data_daily
                    WHERE stock_eu_bags60kg IS NOT NULL
                ) AS marked
                WHERE delta IS NULL OR delta <> 0
                GROUP BY value
            ) AS first_occurrences
            ON CONFLICT (region, report_date, contract_market) DO NOTHING;
            """
        )
    )


def _backfill_pl_cot_us_weekly() -> None:
    """Backfill CFTC US weekly from legacy ``com_net_us`` column.

    Heuristic same as stocks: first date a value appears = release_date
    (CFTC publishes Friday → most "first date" rows should land on Mon
    since the scraper runs weekday-only and Friday's release first appears
    on the following Monday's session row).

    We have no Long/Short decomposition in the legacy data — only the net.
    ``prod_merc_net`` is a GENERATED column (long − short) so we cannot
    INSERT into it directly. Workaround that preserves both the correct
    net AND a defensible sign convention (long ≥ 0, short ≥ 0):

        prod_merc_long  = GREATEST(value, 0)        -- positive part
        prod_merc_short = ABS(LEAST(value, 0))      -- |negative part|
        prod_merc_net   = long - short = value      ✓ (GENERATED)

    So a row backfilled from ``com_net_us = -30000`` becomes
    (long=0, short=30000, net=-30000) — semantically valid (commercials
    net short in commodities is typical) and mathematically exact on the
    net. The new scraper will extract real long+short going forward.

    report_date is derived as ``release_date - INTERVAL '3 days'`` (CFTC
    snapshot Tuesday → release Friday convention, mirrors ICE EU parser).
    """
    op.execute(
        sa.text(
            """
            INSERT INTO pl_cot_us_weekly
                (release_date, report_date, contract_market,
                 prod_merc_long, prod_merc_short)
            SELECT
                first_date                              AS release_date,
                first_date - INTERVAL '3 days'          AS report_date,
                'cocoa'                                 AS contract_market,
                GREATEST(value, 0)::INTEGER             AS prod_merc_long,
                ABS(LEAST(value, 0))::INTEGER           AS prod_merc_short
            FROM (
                SELECT
                    value,
                    MIN(date) AS first_date
                FROM (
                    SELECT
                        date,
                        com_net_us AS value,
                        com_net_us
                            - LAG(com_net_us)
                                OVER (PARTITION BY contract_id ORDER BY date)
                            AS delta
                    FROM pl_contract_data_daily
                    WHERE com_net_us IS NOT NULL
                ) AS marked
                WHERE delta IS NULL OR delta <> 0
                GROUP BY value
            ) AS first_occurrences
            ON CONFLICT (release_date, contract_market) DO NOTHING;
            """
        )
    )


def _recreate_view_without_legacy_columns() -> None:
    """Recreate ``v_contract_data_chained`` without the 3 legacy columns.

    Must DROP first because changing the projection of a VIEW that's not
    a simple add is not allowed by ``CREATE OR REPLACE VIEW`` semantics
    (you can only add columns, not remove). Then recreate with the new
    column list.

    The C5 ensemble loader currently SELECTs these columns from the view
    but no specialist consumes them. The loader will be updated in the
    same PR to stop selecting them.
    """
    op.execute("DROP VIEW IF EXISTS v_contract_data_chained;")
    op.execute(
        """
        CREATE VIEW v_contract_data_chained AS
        SELECT DISTINCT ON (date)
            date,
            display_date,
            contract_id,
            open,
            high,
            low,
            close,
            volume,
            oi,
            implied_volatility
        FROM pl_contract_data_daily
        WHERE close IS NOT NULL
        ORDER BY
            date ASC,
            COALESCE(oi, 0) DESC,
            COALESCE(volume, 0) DESC,
            contract_id ASC;
        """
    )


def _drop_legacy_columns() -> None:
    """Drop the 3 legacy weekly columns from ``pl_contract_data_daily``.

    Safe to drop now that:
      * Data is backfilled into the new tables (idempotent ON CONFLICT).
      * The view has been recreated without the columns.
      * All application-layer consumers will be updated in the same PR
        before the migration ships to prod (per
        migrations-prod-via-main-only).
    """
    with op.batch_alter_table("pl_contract_data_daily") as batch:
        batch.drop_column("stock_us")
        batch.drop_column("stock_eu_bags60kg")
        batch.drop_column("com_net_us")


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------
def downgrade() -> None:
    """Re-add legacy columns + repopulate them from the new tables, then
    drop the new tables. Best-effort restoration — exact byte-for-byte
    parity isn't possible because pl_contract_data_daily lost the "every
    row carries the same weekly value" pattern.

    Restoration strategy: for each session date in pl_contract_data_daily,
    pick the latest stock/cot observation on/before that date and write
    the value back to the corresponding row. This reproduces the
    overwrite-every-row pattern the legacy code expected.
    """
    _readd_legacy_columns()
    _repopulate_legacy_columns()
    _recreate_view_with_legacy_columns()
    op.drop_index("ix_cot_us_weekly_report_date", table_name="pl_cot_us_weekly")
    op.drop_table("pl_cot_us_weekly")
    op.drop_index("ix_stock_observation_lookup", table_name="pl_stock_observation")
    op.drop_table("pl_stock_observation")


def _readd_legacy_columns() -> None:
    with op.batch_alter_table("pl_contract_data_daily") as batch:
        batch.add_column(sa.Column("stock_us", sa.DECIMAL(15, 6), nullable=True))
        batch.add_column(
            sa.Column("stock_eu_bags60kg", sa.DECIMAL(15, 6), nullable=True)
        )
        batch.add_column(sa.Column("com_net_us", sa.DECIMAL(15, 6), nullable=True))


def _repopulate_legacy_columns() -> None:
    op.execute(
        sa.text(
            """
            UPDATE pl_contract_data_daily AS pcdd
            SET stock_us = sub.value_tonnes
            FROM (
                SELECT DISTINCT ON (pcdd2.id)
                    pcdd2.id,
                    pso.value_tonnes
                FROM pl_contract_data_daily AS pcdd2
                JOIN pl_stock_observation AS pso
                    ON pso.region = 'us'
                    AND pso.contract_market = 'cocoa'
                    AND pso.report_date <= pcdd2.date
                ORDER BY pcdd2.id, pso.report_date DESC
            ) AS sub
            WHERE pcdd.id = sub.id;
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE pl_contract_data_daily AS pcdd
            SET stock_eu_bags60kg = sub.value_native
            FROM (
                SELECT DISTINCT ON (pcdd2.id)
                    pcdd2.id,
                    pso.value_native
                FROM pl_contract_data_daily AS pcdd2
                JOIN pl_stock_observation AS pso
                    ON pso.region = 'eu'
                    AND pso.contract_market = 'cocoa'
                    AND pso.report_date <= pcdd2.date
                ORDER BY pcdd2.id, pso.report_date DESC
            ) AS sub
            WHERE pcdd.id = sub.id;
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE pl_contract_data_daily AS pcdd
            SET com_net_us = sub.prod_merc_net
            FROM (
                SELECT DISTINCT ON (pcdd2.id)
                    pcdd2.id,
                    cw.prod_merc_net
                FROM pl_contract_data_daily AS pcdd2
                JOIN pl_cot_us_weekly AS cw
                    ON cw.contract_market = 'cocoa'
                    AND cw.release_date <= pcdd2.date
                ORDER BY pcdd2.id, cw.release_date DESC
            ) AS sub
            WHERE pcdd.id = sub.id;
            """
        )
    )


def _recreate_view_with_legacy_columns() -> None:
    op.execute("DROP VIEW IF EXISTS v_contract_data_chained;")
    op.execute(
        """
        CREATE VIEW v_contract_data_chained AS
        SELECT DISTINCT ON (date)
            date,
            display_date,
            contract_id,
            open,
            high,
            low,
            close,
            volume,
            oi,
            implied_volatility,
            stock_us,
            stock_eu_bags60kg,
            com_net_us
        FROM pl_contract_data_daily
        WHERE close IS NOT NULL
        ORDER BY
            date ASC,
            COALESCE(oi, 0) DESC,
            COALESCE(volume, 0) DESC,
            contract_id ASC;
        """
    )
