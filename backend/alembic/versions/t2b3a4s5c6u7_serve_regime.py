"""Serve regime+judge. The bascule.

This is the only migration in the sequence that changes what a user sees. It
moves three integers and touches nothing else.

    before :  ensemble = 1 · legacy = 2 · regime = NULL
    after  :  regime = 1 · ensemble = 2 · legacy = 3

Effective within the resolver's cache TTL (5 minutes). No deploy is needed
beyond applying it, and ``downgrade()`` is a genuine rollback: the reverse
UPDATE, which works for as long as the ensemble jobs keep writing rows — which
is why they stay scheduled through the stability window.

### Why the order matters

Two partial unique indexes guard the column (``q2s3e4r5v6i7``): one rank per
row, one ranked row per name. So the ranks cannot be reassigned in any order —
each statement has to target a slot that is already free. Working bottom-up does
that: 3 is free, then 2, then 1.

Each statement is also keyed on the CURRENT rank rather than on the name alone.
Two reasons. ``legacy`` has two version rows and only 1.0.1 is ranked; an
UPDATE by name would rank both and violate the one-ranked-row-per-name index.
And keying on the current value makes a replay inert instead of shuffling ranks
a second time.

### What this migration does NOT do

``is_active`` and ``compute_enabled`` are untouched. They belong to the compute
layer — ``engine/runner.py`` resolves the legacy version through ``is_active``,
and clearing it would break ``cc-compute-indicators``, the job that still feeds
``pl_derived_indicators`` and the dashboard gauges. An earlier draft of this
bascule flipped them and would have taken the nightly pipeline down.

``judge`` never gets a rank. It writes no ``pl_indicator_daily`` row; its verdict
reaches the dashboard fused into regime's decision by the adapter. Its version
row exists only as the provenance key on ``pl_judge_shadow``.

Revision ID: t2b3a4s5c6u7
Revises: s4j5u6d7g8e9
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op

revision: str = "t2b3a4s5c6u7"
down_revision: Union[str, Sequence[str], None] = "s4j5u6d7g8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENSEMBLE = "ensemble_v1_softgate_wrapper"
LEGACY = "legacy"
REGIME = "regime"
REGIME_VERSION = "1.0.0"


def upgrade() -> None:
    # Bottom-up: every statement lands on a slot that is already vacant.
    op.execute(
        f"UPDATE pl_algorithm_version SET serving_rank = 3 "
        f"WHERE name = '{LEGACY}' AND serving_rank = 2"
    )
    op.execute(
        f"UPDATE pl_algorithm_version SET serving_rank = 2 "
        f"WHERE name = '{ENSEMBLE}' AND serving_rank = 1"
    )
    op.execute(
        f"UPDATE pl_algorithm_version SET serving_rank = 1 "
        f"WHERE name = '{REGIME}' AND version = '{REGIME_VERSION}'"
    )


def downgrade() -> None:
    # Top-down on the way back, same reason: free the slot before claiming it.
    op.execute(
        f"UPDATE pl_algorithm_version SET serving_rank = NULL WHERE name = '{REGIME}'"
    )
    op.execute(
        f"UPDATE pl_algorithm_version SET serving_rank = 1 "
        f"WHERE name = '{ENSEMBLE}' AND serving_rank = 2"
    )
    op.execute(
        f"UPDATE pl_algorithm_version SET serving_rank = 2 "
        f"WHERE name = '{LEGACY}' AND serving_rank = 3"
    )
