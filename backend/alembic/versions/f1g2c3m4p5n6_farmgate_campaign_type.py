"""farmgate: distinguish principale vs intermediaire sub-campaign

Adds ``campaign_type`` ('principale' | 'intermediaire') to
pl_official_farmgate_price so the CCC/COCOBOD guaranteed price can be shown per
sub-campaign (main crop Oct→Mar vs mid-crop Apr→Sep). Existing rows default to
'principale'; the unique key gains campaign_type so both can coexist per season.

Idempotent (safe re-apply on GCP).

Revision ID: f1g2c3m4p5n6
Revises: t1e2n3a4n5t6
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "f1g2c3m4p5n6"
down_revision: Union[str, Sequence[str], None] = "t1e2n3a4n5t6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_UQ = "uq_farmgate_region_effective_announced"
_NEW_UQ = "uq_farmgate_region_campaign_effective_announced"


def _has_column(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(op.get_bind()).get_columns(table)]


def _has_constraint(table: str, name: str) -> bool:
    insp = inspect(op.get_bind())
    names = [c["name"] for c in insp.get_unique_constraints(table)]
    names += [c["name"] for c in insp.get_check_constraints(table)]
    return name in names


def upgrade() -> None:
    if not _has_column("pl_official_farmgate_price", "campaign_type"):
        op.execute(
            "ALTER TABLE pl_official_farmgate_price "
            "ADD COLUMN campaign_type VARCHAR(16) NOT NULL DEFAULT 'principale'"
        )
    if not _has_constraint("pl_official_farmgate_price", "ck_farmgate_campaign"):
        op.execute(
            "ALTER TABLE pl_official_farmgate_price "
            "ADD CONSTRAINT ck_farmgate_campaign "
            "CHECK (campaign_type IN ('principale', 'intermediaire'))"
        )
    # Widen the unique key to include campaign_type (both sub-campaigns per season).
    if _has_constraint("pl_official_farmgate_price", _OLD_UQ):
        op.execute(f"ALTER TABLE pl_official_farmgate_price DROP CONSTRAINT {_OLD_UQ}")
    if not _has_constraint("pl_official_farmgate_price", _NEW_UQ):
        op.execute(
            "ALTER TABLE pl_official_farmgate_price "
            f"ADD CONSTRAINT {_NEW_UQ} "
            "UNIQUE (region, campaign_type, effective_date, announced_date)"
        )


def downgrade() -> None:
    if _has_constraint("pl_official_farmgate_price", _NEW_UQ):
        op.execute(f"ALTER TABLE pl_official_farmgate_price DROP CONSTRAINT {_NEW_UQ}")
    if not _has_constraint("pl_official_farmgate_price", _OLD_UQ):
        op.execute(
            "ALTER TABLE pl_official_farmgate_price "
            f"ADD CONSTRAINT {_OLD_UQ} "
            "UNIQUE (region, effective_date, announced_date)"
        )
    if _has_constraint("pl_official_farmgate_price", "ck_farmgate_campaign"):
        op.execute(
            "ALTER TABLE pl_official_farmgate_price DROP CONSTRAINT ck_farmgate_campaign"
        )
    if _has_column("pl_official_farmgate_price", "campaign_type"):
        op.execute("ALTER TABLE pl_official_farmgate_price DROP COLUMN campaign_type")
