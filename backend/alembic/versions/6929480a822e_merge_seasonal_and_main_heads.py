"""merge seasonal and main heads

Revision ID: 6929480a822e
Revises: 6fc0b37d63f0, feb172a31671
Create Date: 2026-04-01 00:00:12.529073

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "6929480a822e"
down_revision: Union[str, Sequence[str], None] = ("6fc0b37d63f0", "feb172a31671")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
