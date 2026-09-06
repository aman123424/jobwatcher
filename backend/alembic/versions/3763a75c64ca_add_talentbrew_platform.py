"""add talentbrew platform

Revision ID: 3763a75c64ca
Revises: 55130745e37a
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3763a75c64ca'
down_revision: Union[str, Sequence[str], None] = '55130745e37a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adds 'talentbrew' to the existing `platform` Postgres ENUM type
    (models.py's Platform) - same reasoning and same autocommit_block()
    requirement as a43bc5460e9b_add_rejected_job_status.py (see that
    migration's own docstring for why `ALTER TYPE ... ADD VALUE` can't
    run inside a normal transaction).
    """
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform ADD VALUE 'talentbrew'")


def downgrade() -> None:
    """Deliberately NOT reversible - see a43bc5460e9b's downgrade() docstring for why."""
    raise NotImplementedError(
        "Cannot drop an enum value in Postgres without recreating the platform type - "
        "not implemented; roll back to a backup instead if this migration must be undone."
    )
