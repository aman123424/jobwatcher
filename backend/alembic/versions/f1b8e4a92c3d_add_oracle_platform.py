"""add oracle platform

Revision ID: f1b8e4a92c3d
Revises: a4f0c9d2e816
Create Date: 2026-09-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1b8e4a92c3d'
down_revision: Union[str, Sequence[str], None] = 'a4f0c9d2e816'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adds 'oracle' to the existing `platform` Postgres ENUM type
    (models.py's Platform) - same reasoning and same autocommit_block()
    requirement as 3763a75c64ca_add_talentbrew_platform.py (see that
    migration's own docstring for why `ALTER TYPE ... ADD VALUE` can't
    run inside a normal transaction).
    """
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform ADD VALUE 'oracle'")


def downgrade() -> None:
    """Deliberately NOT reversible - see 3763a75c64ca's downgrade() docstring for why."""
    raise NotImplementedError(
        "Cannot drop an enum value in Postgres without recreating the platform type - "
        "not implemented; roll back to a backup instead if this migration must be undone."
    )
