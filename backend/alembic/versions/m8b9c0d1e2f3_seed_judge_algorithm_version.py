"""seed judge algorithm version (Campaign 6 macro overlay, INERT)

Revision ID: m8b9c0d1e2f3
Revises: l7a8b9c0d1e2
Create Date: 2026-08-10

Prod-lands the ``judge`` v0.1 algorithm row. Judge is a Layer-3 macro overlay
above ``regime``: reads the last N Compass daily briefs (press + weather),
detects drift versus the technical call, and via a deterministic policy may
confirm, abstain (MONITOR), or flip the base decision. LLM judgment behind a
pinned prompt + o4-mini adapter.

Ships INERT (is_active=FALSE, compute_enabled=FALSE): the shadow-compute path
writes only ``pl_judge_shadow``, never ``pl_indicator_daily.decision``. Promotion
is a Compass-side flag flip AFTER shadow clears the go/no-go over >=30 sessions
(intervention confusion matrix + calibration curve — see judge/README.md §
"Shadow-eval spec").

Config thresholds live in ``vendor/judge_v0.1/judge/config.py`` (flip conf >= 4,
monitor conf = 3, ignore conf <= 2, brief window = 3, prompt version, model id).
Not seeded here — retuning is a code-side change per R&D's explicit design
choice ("retune config.py, not the prompt"). If future eval needs DB-tunability,
promote them to ``pl_algorithm_config`` in a follow-up migration.

Idempotent (safe re-apply on GCP): NOT EXISTS guard on the version row.
"""

from alembic import op

revision = "m8b9c0d1e2f3"
down_revision = "l7a8b9c0d1e2"
branch_labels = None
depends_on = None


_SEED_VERSION = """
INSERT INTO pl_algorithm_version (id, name, version, horizon, is_active, compute_enabled, description)
SELECT gen_random_uuid(),
       'judge', '0.1', 'short_term',
       FALSE, FALSE,
       'Layer-3 macro overlay above regime. Reads the last N Compass briefs (press + weather), detects drift vs the technical call, and via a deterministic policy may confirm / MONITOR / flip. LLM judgment (o4-mini, temp 0, pinned prompt) behind a JudgeLLM Protocol. SHIPPED INERT for shadow validation — advises never controls until >=30 sessions clear the go/no-go (intervention confusion matrix + calibration curve).'
WHERE NOT EXISTS (
    SELECT 1 FROM pl_algorithm_version WHERE name = 'judge' AND version = '0.1'
);
"""


def upgrade() -> None:
    op.execute(_SEED_VERSION)


def downgrade() -> None:
    op.execute(
        "DELETE FROM pl_algorithm_version WHERE name = 'judge' AND version = '0.1'"
    )
