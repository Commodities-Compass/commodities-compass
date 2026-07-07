"""add pl_session_release — publication gate for the dashboard's atomic flip

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-07-07

Why
---
The dashboard's "latest session" flip was driven purely by
``MAX(display_date) WHERE display_date <= today()`` — so a session's data only
became the default view when the UTC calendar reached its ``display_date`` (the
morning after). Two problems:
  * users could see a **half-filled** session during the ~19:00–19:35 UTC window
    while Phase B was still writing rows;
  * night users could not read the freshly-computed next-session data the same
    evening even though every row (and the NotebookLM audio) was already ready.

This table is the explicit **publication marker**: a session is exposed to the
dashboard only once a row exists here. A dedicated ``cc-publish-session`` job
stamps it after verifying data completeness (indicator + press + meteo) and, in
the normal path, that the NotebookLM audio is present — so the flip is atomic
(all sections + audio at once) and can happen the same evening.

Kept as a **dedicated table** rather than a column on ``pl_contract_data_daily``
so the raw market row stays immutable (North Star: raw data is append-only;
publication is a presentation concern, not pipeline computation).

Idempotent: guarded by an inspector check so re-application on GCP is a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a9b8c7d6e5f4"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("pl_session_release"):
        return

    op.create_table(
        "pl_session_release",
        # = the session date T (data_date) being released. One row per session.
        sa.Column("session_date", sa.DATE(), primary_key=True),
        # When the publish job stamped the release (UTC).
        sa.Column(
            "published_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # True when the NotebookLM audio was present at publish time. False on
        # the morning-fallback path (data complete but audio not yet uploaded)
        # — the session is still exposed; the audio plays once uploaded (the
        # audio endpoint fetches Drive independently).
        sa.Column(
            "has_audio",
            sa.BOOLEAN(),
            server_default=sa.false(),
            nullable=False,
        ),
        # Provenance: which actor stamped the release.
        sa.Column(
            "source",
            sa.VARCHAR(40),
            server_default="publish-session",
            nullable=False,
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("pl_session_release"):
        op.drop_table("pl_session_release")
