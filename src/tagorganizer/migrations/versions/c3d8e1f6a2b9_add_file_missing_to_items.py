"""Add file_missing to items

Revision ID: c3d8e1f6a2b9
Revises: 5b2e9d41c7a8
Create Date: 2026-11-19 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d8e1f6a2b9"
down_revision: Union[str, None] = "5b2e9d41c7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable with no default: nobody has looked for these files yet, and
    # False would claim somebody had and found them.
    with op.batch_alter_table("item", schema=None) as batch_op:
        batch_op.add_column(sa.Column("file_missing", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("item", schema=None) as batch_op:
        batch_op.drop_column("file_missing")
