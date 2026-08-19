"""Tag pl_judge_shadow with the algorithm it overlays, not with a version of its own.

The judge had its own `pl_algorithm_version` row, and that row existed for one
reason: to be the foreign key of `pl_judge_shadow.algorithm_version_id`. It
carried no information the table did not already hold — `prompt_version` and
`model_id` are both NOT NULL there, and they are what actually identifies a judge
run and what a replay targets.

What it did cost was a class of bug. Two uuids, same type, both plausibly "the
judge's", exactly one correct per query — and the wrong one never returns a
partial result, it returns nothing at all:

* reading `pl_indicator_daily` under the judge id finds nothing, because the
  judge writes no row there (fixed 2026-08-18 in the shadow runner, where it was
  fail-loud and killed the nightly job);
* reading `pl_judge_shadow` under the regime id finds nothing either, because
  judge rows were tagged with the judge id (fixed 2026-08-19 in the diagnostics
  endpoint, where a *legitimate* degradation — "no overlay tonight, report the
  technical call alone" — absorbed it silently, and the dashboard showed
  "Arbitrage macro : Non rendue" on a session the judge had ruled CONFIRM).

Both shipped. The second survived review because the test fixtures made the same
assumption as the code: they seeded the judge row under the regime id, so service
and test agreed with each other and both were wrong.

One id from here on. The confusion is not documented away — it is gone, because
there is no longer a second id to pick.

The `judge` version row is deliberately LEFT in `pl_algorithm_version`: nothing
references it once this migration lands, it is inert, and deleting a version row
that historical rows may still be traced through buys nothing.

Idempotent: re-running matches no row, since none is left under the judge version.

Revision ID: u3j4u5d6g7e8
Revises: t2b3a4s5c6u7
Create Date: 2026-08-19
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "u3j4u5d6g7e8"
down_revision: Union[str, Sequence[str], None] = "t2b3a4s5c6u7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RETAG = """
UPDATE pl_judge_shadow
SET algorithm_version_id = (
        SELECT id FROM pl_algorithm_version
        WHERE name = 'regime' AND version = '1.0.0'
    )
WHERE algorithm_version_id IN (
        SELECT id FROM pl_algorithm_version WHERE name = 'judge'
    )
  AND EXISTS (
        SELECT 1 FROM pl_algorithm_version WHERE name = 'regime' AND version = '1.0.0'
    )
"""

_REVERT = """
UPDATE pl_judge_shadow
SET algorithm_version_id = (
        SELECT id FROM pl_algorithm_version WHERE name = 'judge'
        ORDER BY created_at DESC LIMIT 1
    )
WHERE algorithm_version_id IN (
        SELECT id FROM pl_algorithm_version WHERE name = 'regime' AND version = '1.0.0'
    )
  AND EXISTS (SELECT 1 FROM pl_algorithm_version WHERE name = 'judge')
"""


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("pl_judge_shadow"):
        return
    # The UNIQUE is (date, contract_id, algorithm_version_id) and the judge
    # writes at most one row per session and contract, so collapsing the version
    # dimension cannot collide.
    op.execute(_RETAG)


def downgrade() -> None:
    if not _has_table("pl_judge_shadow"):
        return
    op.execute(_REVERT)
