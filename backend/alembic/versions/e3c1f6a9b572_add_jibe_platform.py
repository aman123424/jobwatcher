"""add jibe platform

Revision ID: e3c1f6a9b572
Revises: d2b0e5f8a461
Create Date: 2026-09-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3c1f6a9b572'
down_revision: Union[str, Sequence[str], None] = 'd2b0e5f8a461'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Adds 'jibe' to the `platform` ENUM - see f1b8e4a92c3d_add_oracle_platform.py for why autocommit_block() is required."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform ADD VALUE 'jibe'")


def downgrade() -> None:
    """Deliberately NOT reversible - see f1b8e4a92c3d's downgrade() docstring for why."""
    raise NotImplementedError(
        "Cannot drop an enum value in Postgres without recreating the platform type - "
        "not implemented; roll back to a backup instead if this migration must be undone."
    )
