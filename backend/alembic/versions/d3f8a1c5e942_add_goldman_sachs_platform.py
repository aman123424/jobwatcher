"""add goldman_sachs platform

Revision ID: d3f8a1c5e942
Revises: c7e2a1f9b4d6
Create Date: 2026-09-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3f8a1c5e942'
down_revision: Union[str, Sequence[str], None] = 'c7e2a1f9b4d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adds 'goldman_sachs' to the existing `platform` Postgres ENUM type
    (models.py's Platform) - same reasoning and same autocommit_block()
    requirement as f1b8e4a92c3d_add_oracle_platform.py (see that
    migration's own docstring for why `ALTER TYPE ... ADD VALUE` can't
    run inside a normal transaction).
    """
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform ADD VALUE 'goldman_sachs'")


def downgrade() -> None:
    """Deliberately NOT reversible - see f1b8e4a92c3d's downgrade() docstring for why."""
    raise NotImplementedError(
        "Cannot drop an enum value in Postgres without recreating the platform type - "
        "not implemented; roll back to a backup instead if this migration must be undone."
    )
