"""add tailoring_reports table

Revision ID: ee1188a9c750
Revises: 3763a75c64ca
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ee1188a9c750'
down_revision: Union[str, Sequence[str], None] = '3763a75c64ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Adds `tailoring_reports` - same (user_id, job_id) composite-PK
    shape as `job_scores` (see models.py's TailoringReport docstring
    for the full "why"), holding the JSON suggestions list fitmodel's
    POST /tailor returns.
    """
    op.create_table(
        "tailoring_reports",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("suggestions", postgresql.JSONB(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tailoring_reports")
