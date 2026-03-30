"""merge heads

Revision ID: 984453591f4a
Revises: 04f9e9fb7c44, 6d4eef12be0c
Create Date: 2026-03-27 15:59:06.198055

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "984453591f4a"
down_revision: Union[str, Sequence[str], None] = ("04f9e9fb7c44", "6d4eef12be0c")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
