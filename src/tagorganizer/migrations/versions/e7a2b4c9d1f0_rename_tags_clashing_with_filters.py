"""Rename tags that share a name with a built-in filter

Revision ID: e7a2b4c9d1f0
Revises: c3d8e1f6a2b9
Create Date: 2026-11-19 13:00:00.000000

"""

import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7a2b4c9d1f0"
down_revision: Union[str, None] = "c3d8e1f6a2b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger(__name__)

# Copied rather than imported: a migration must keep doing what it did when it
# was written, whatever the app's list says later.
FILTER_NAMES = [
    "No Time",
    "No GPS",
    "Wrong dir",
    "Unnamed faces",
    "Duplicates",
    "Missing file",
]


def upgrade() -> None:
    # Choosing such a tag in the tag bar selects the filter instead, so the
    # tag could never be used again. "Duplicates" in particular is a
    # plausible tag to have made before it became a filter.
    connection = op.get_bind()
    tags = connection.execute(sa.text("SELECT id, name FROM tag")).all()
    taken = {name.casefold() for _, name in tags}
    reserved = {name.casefold() for name in FILTER_NAMES}
    for tag_id, name in tags:
        if name.strip().casefold() not in reserved:
            continue
        new_name = f"{name} (tag)"
        number = 2
        while new_name.casefold() in taken:
            new_name = f"{name} (tag {number})"
            number += 1
        taken.add(new_name.casefold())
        connection.execute(
            sa.text("UPDATE tag SET name = :name WHERE id = :id"),
            {"name": new_name, "id": tag_id},
        )
        logger.warning(
            "Renamed tag %r to %r: a built-in filter has its name", name, new_name
        )


def downgrade() -> None:
    # The old names cannot be told apart from tags genuinely called
    # "... (tag)", so they are left as they are.
    pass
