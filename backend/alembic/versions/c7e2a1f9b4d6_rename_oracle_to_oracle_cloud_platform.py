"""rename oracle platform value to oracle_cloud

Revision ID: c7e2a1f9b4d6
Revises: f1b8e4a92c3d
Create Date: 2026-09-12 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e2a1f9b4d6'
down_revision: Union[str, Sequence[str], None] = 'f1b8e4a92c3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    'oracle' (added by f1b8e4a92c3d, moments earlier in the same
    feature) renamed to 'oracle_cloud' - Aman's own correction: this is
    Oracle FUSION CLOUD Recruiting specifically, not a generic "Oracle"
    platform, and the bare name reads as ambiguous/wrong. `ALTER TYPE
    ... RENAME VALUE` (not ADD + manually UPDATE existing rows) is the
    right tool here - it's an in-place rename of the enum label itself,
    so any existing `companies` row already using 'oracle' (there was
    exactly one at the time this was written - a live-tested Honeywell
    entry, see companies.py) is updated automatically, with no separate
    data-migration UPDATE statement needed. Same autocommit_block()
    requirement as every other enum-altering migration in this project
    (see f1b8e4a92c3d's own docstring for why).
    """
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform RENAME VALUE 'oracle' TO 'oracle_cloud'")


def downgrade() -> None:
    """
    Unlike f1b8e4a92c3d's ADD VALUE (genuinely irreversible without
    recreating the whole enum type), a RENAME VALUE is trivially
    reversible - just rename it back. No data-migration concern either,
    same reasoning as upgrade() above.
    """
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform RENAME VALUE 'oracle_cloud' TO 'oracle'")
