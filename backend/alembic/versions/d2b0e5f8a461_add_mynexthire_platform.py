"""add mynexthire platform

Revision ID: d2b0e5f8a461
Revises: c1a9d4e7f350
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2b0e5f8a461'
down_revision: Union[str, Sequence[str], None] = 'c1a9d4e7f350'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adds 'mynexthire' to the existing `platform` Postgres ENUM type
    (models.py's Platform) - same reasoning and same autocommit_block()
    requirement as every other enum-adding migration in this project
    (see f1b8e4a92c3d_add_oracle_platform.py for the fullest version of
    that explanation).
    """
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform ADD VALUE 'mynexthire'")


def downgrade() -> None:
    """Deliberately NOT reversible - see f1b8e4a92c3d's downgrade() docstring for why."""
    raise NotImplementedError(
        "Cannot drop an enum value in Postgres without recreating the platform type - "
        "not implemented; roll back to a backup instead if this migration must be undone."
    )
