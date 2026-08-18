"""Grant read:feature:judge_overlay to every account that bought Conviction.

The "Conviction" row of the commercial matrix is sold on 6 of the 7 tiers (all
but coop_essentiel). Until now it was backed by two ensemble-specific keys —
``read:feature:ensemble_diagnostics`` and ``read:feature:specialist_votes``.
Campaign 6 replaces that surface with ``/judge-diagnostics``, gated by
``read:feature:judge_overlay``.

Without this migration the flip to regime would silently remove a **billed
capability** from every tier except the entry one: the endpoint would exist, the
tier template would list the key, but the accounts provisioned before today
would hold no grant for it and see a 403.

``tenant_entitlement`` is APPEND-ONLY (grant = INSERT active, revoke = INSERT an
``active=false`` tombstone). So this is an INSERT, never an UPDATE, and the two
ensemble keys are deliberately **left untouched**: the ensemble endpoints keep
serving until their jobs are descheduled, and they are the rollback path. They
get their tombstones when the code that backs them is deleted.

``internal`` accounts need nothing — ``resolve_principal`` short-circuits them to
the full catalogue at read time, which is exactly why that marker exists.

Idempotent: re-running inserts nothing (NOT EXISTS on the account+key pair).

Revision ID: s4j5u6d7g8e9
Revises: r3g4a5u6g7e8
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "s4j5u6d7g8e9"
down_revision: Union[str, Sequence[str], None] = "r3g4a5u6g7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JUDGE_OVERLAY_KEY = "read:feature:judge_overlay"
# The grant that identifies a Conviction customer. Both ensemble keys always
# travel together in every tier template, so either one identifies the same
# population; matching on one keeps the query readable.
CONVICTION_MARKER_KEY = "read:feature:ensemble_diagnostics"


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("tenant_entitlement"):
        # Environment provisioned before the tenancy tables — nothing to grant.
        return

    # The "latest active row per (account, key)" logic is inlined rather than
    # read from v_tenant_entitlement_current: a migration that depends on a view
    # breaks the day the view is renamed, and it must run on environments
    # provisioned before the view existed.
    #
    # effective_from is copied from the marker grant rather than stamped today:
    # the account has been paying for Conviction since that date, and the judge
    # key is the same right under a new implementation. Backdating also keeps
    # the row current no matter which day the migration lands on.
    op.execute(
        f"""
        INSERT INTO tenant_entitlement (id, account_id, entitlement_key,
                                        effective_from, active)
        SELECT gen_random_uuid(), c.account_id, '{JUDGE_OVERLAY_KEY}',
               c.effective_from, true
        FROM (
            SELECT DISTINCT ON (account_id, entitlement_key)
                   account_id, entitlement_key, effective_from, active
            FROM tenant_entitlement
            WHERE effective_from <= CURRENT_DATE
            ORDER BY account_id, entitlement_key, effective_from DESC
        ) c
        WHERE c.active
          AND c.entitlement_key = '{CONVICTION_MARKER_KEY}'
          AND NOT EXISTS (
              SELECT 1 FROM tenant_entitlement e
              WHERE e.account_id = c.account_id
                AND e.entitlement_key = '{JUDGE_OVERLAY_KEY}'
          )
        """
    )


def downgrade() -> None:
    # The table is append-only by contract, but a downgrade is precisely the one
    # case where the row must disappear rather than be tombstoned: leaving a
    # tombstone would deny the key to any account re-granted it later.
    if not _has_table("tenant_entitlement"):
        return
    op.execute(
        f"DELETE FROM tenant_entitlement WHERE entitlement_key = '{JUDGE_OVERLAY_KEY}'"
    )
