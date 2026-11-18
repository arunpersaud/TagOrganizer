"""Add face_count to items

Revision ID: 5b2e9d41c7a8
Revises: a1f4c7b23d05
Create Date: 2026-11-17 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5b2e9d41c7a8"
down_revision: Union[str, None] = "a1f4c7b23d05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable with no default: photos already in the library have not been
    # checked, and 0 would claim they were checked and had no faces.
    with op.batch_alter_table("item", schema=None) as batch_op:
        batch_op.add_column(sa.Column("face_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("item", schema=None) as batch_op:
        batch_op.drop_column("face_count")
