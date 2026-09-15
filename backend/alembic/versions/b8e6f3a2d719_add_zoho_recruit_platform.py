"""add zoho_recruit platform

Revision ID: b8e6f3a2d719
Revises: d3f8a1c5e942
Create Date: 2026-09-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e6f3a2d719'
down_revision: Union[str, Sequence[str], None] = 'd3f8a1c5e942'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adds 'zoho_recruit' to the existing `platform` Postgres ENUM type
    (models.py's Platform) - same reasoning and same autocommit_block()
    requirement as every other enum-adding migration in this project
    (see f1b8e4a92c3d_add_oracle_platform.py for the fullest version of
    that explanation).
    """
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform ADD VALUE 'zoho_recruit'")


def downgrade() -> None:
    """Deliberately NOT reversible - see f1b8e4a92c3d's downgrade() docstring for why."""
    raise NotImplementedError(
        "Cannot drop an enum value in Postgres without recreating the platform type - "
        "not implemented; roll back to a backup instead if this migration must be undone."
    )
