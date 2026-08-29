"""initial

Revision ID: c3c22277f560
Revises:
Create Date: 2024-12-29 07:57:02.443398

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlmodel.sql.sqltypes import AutoString


# revision identifiers, used by Alembic.
revision: str = "c3c22277f560"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create tag table first (no foreign key dependencies)
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", AutoString(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["tag.id"], name="fk_tag_parent_id_tag"),
        sa.PrimaryKeyConstraint("id", name="pk_tag"),
    )

    # Create item table
    op.create_table(
        "item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uri", AutoString(), nullable=False),
        sa.Column("uri_md5", AutoString(), nullable=False),
        sa.Column("data_xxhash", AutoString(), nullable=False),
        sa.Column("camera", AutoString(), nullable=True),
        sa.Column("date", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_item"),
    )
    op.create_index("ix_item_camera", "item", ["camera"], unique=False)
    op.create_index("ix_item_date", "item", ["date"], unique=False)

    # Create itemtaglink table
    op.create_table(
        "itemtaglink",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"], ["item.id"], name="fk_itemtaglink_item_id_item"
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tag.id"], name="fk_itemtaglink_tag_id_tag"
        ),
        sa.PrimaryKeyConstraint("item_id", "tag_id", name="pk_itemtaglink"),
    )

    # ### end Alembic commands ###


def downgrade() -> None:
    # Drop in reverse order of creation
    op.drop_table("itemtaglink")
    op.drop_index("ix_item_date", table_name="item")
    op.drop_index("ix_item_camera", table_name="item")
    op.drop_table("item")
    op.drop_table("tag")

    # ### end Alembic commands ###
