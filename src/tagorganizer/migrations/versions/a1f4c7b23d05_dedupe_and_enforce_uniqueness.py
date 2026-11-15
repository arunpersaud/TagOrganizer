"""Merge duplicate items and tags, then forbid new ones

Revision ID: a1f4c7b23d05
Revises: 33cc0c0a76e3
Create Date: 2026-09-08

A unique constraint on its own would abort the upgrade on any database that
already holds duplicates - and an aborted upgrade means the application will
not open at all, on the machine holding the photos. So this migration cleans
up first and constrains second, in one transaction: pulling the new code and
starting the app is enough, whatever state that machine's library is in.

Everything here is raw SQL against the tables as they stand at this revision.
Old migrations must never import the models, which keep changing underneath
them.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1f4c7b23d05"
down_revision: Union[str, None] = "33cc0c0a76e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Fields a duplicate row may hold that the survivor does not. The survivor is
# the oldest row, so a later import that went through more enrichment would
# otherwise take its date, place and hashes to the grave.
MERGEABLE = ("date", "latitude", "longitude", "camera", "uri_md5", "data_xxhash")


def upgrade() -> None:
    connection = op.get_bind()

    # --- items -------------------------------------------------------------
    # Map every row to the oldest row sharing its uri.
    connection.execute(
        sa.text(
            """
            CREATE TEMP TABLE _item_map AS
            SELECT i.id AS old_id,
                   (SELECT MIN(o.id) FROM item o WHERE o.uri = i.uri) AS new_id
            FROM item i
            """
        )
    )

    # Fill the survivor's gaps from its duplicates before they are deleted.
    # The column itself is the last fallback: uri_md5 and data_xxhash are NOT
    # NULL with an empty-string default, so a plain COALESCE of two empties
    # would produce NULL and fail the constraint.
    for field in MERGEABLE:
        connection.execute(
            sa.text(
                f"""
                UPDATE item SET {field} = COALESCE(
                    NULLIF({field}, ''),
                    (SELECT MAX(d.{field}) FROM item d
                      WHERE d.uri = item.uri
                        AND d.{field} IS NOT NULL AND d.{field} != ''),
                    {field}
                )
                WHERE id IN (SELECT new_id FROM _item_map)
                """
            )
        )

    # Rebuild the link tables rather than repointing rows in place: both have
    # composite primary keys, so repointing would collide wherever a tag or a
    # lineage link was held by two rows that are about to become one. DISTINCT
    # collapses exactly those collisions.
    _rebuild_links(connection, "_item_map")

    connection.execute(
        sa.text("DELETE FROM item WHERE id NOT IN (SELECT new_id FROM _item_map)")
    )

    # --- tags --------------------------------------------------------------
    # get_tag compares stripped and lowercased, so rows differing only in case
    # or surrounding space are one tag to the whole application already.
    connection.execute(
        sa.text(
            """
            CREATE TEMP TABLE _tag_map AS
            SELECT t.id AS old_id,
                   (SELECT MIN(o.id) FROM tag o
                     WHERE lower(trim(o.name)) = lower(trim(t.name))) AS new_id
            FROM tag t
            """
        )
    )

    connection.execute(
        sa.text(
            """
            CREATE TEMP TABLE _new_tag_links AS
            SELECT DISTINCT m.new_id AS tag_id, l.item_id AS item_id
            FROM itemtaglink l JOIN _tag_map m ON m.old_id = l.tag_id
            """
        )
    )
    connection.execute(sa.text("DELETE FROM itemtaglink"))
    connection.execute(
        sa.text(
            "INSERT INTO itemtaglink (item_id, tag_id) "
            "SELECT item_id, tag_id FROM _new_tag_links"
        )
    )

    # A child of a merged tag belongs to the survivor. A tag must not become
    # its own parent, which is what happens when parent and child merge.
    connection.execute(
        sa.text(
            """
            UPDATE tag SET parent_id = (
                SELECT new_id FROM _tag_map WHERE old_id = tag.parent_id
            )
            WHERE parent_id IS NOT NULL
            """
        )
    )
    connection.execute(sa.text("UPDATE tag SET parent_id = NULL WHERE parent_id = id"))
    _break_parent_cycles(connection)
    connection.execute(
        sa.text("DELETE FROM tag WHERE id NOT IN (SELECT new_id FROM _tag_map)")
    )

    connection.execute(sa.text("DROP TABLE _item_map"))
    connection.execute(sa.text("DROP TABLE _tag_map"))
    connection.execute(sa.text("DROP TABLE _new_tag_links"))

    # --- constrain ---------------------------------------------------------
    op.drop_index(op.f("ix_item_uri"), table_name="item")
    op.create_index(op.f("ix_item_uri"), "item", ["uri"], unique=True)
    op.create_index(op.f("ix_tag_name"), "tag", ["name"], unique=True)


def _rebuild_links(connection, mapping: str) -> None:
    """Point the link tables at surviving items, collapsing collisions."""
    connection.execute(
        sa.text(
            f"""
            CREATE TEMP TABLE _new_item_links AS
            SELECT DISTINCT m.new_id AS item_id, l.tag_id AS tag_id
            FROM itemtaglink l JOIN {mapping} m ON m.old_id = l.item_id
            """
        )
    )
    connection.execute(sa.text("DELETE FROM itemtaglink"))
    connection.execute(
        sa.text(
            "INSERT INTO itemtaglink (item_id, tag_id) "
            "SELECT item_id, tag_id FROM _new_item_links"
        )
    )
    connection.execute(sa.text("DROP TABLE _new_item_links"))

    connection.execute(
        sa.text(
            f"""
            CREATE TEMP TABLE _new_parent_links AS
            SELECT DISTINCT c.new_id AS child_id, p.new_id AS parent_id
            FROM itemparentlink l
            JOIN {mapping} c ON c.old_id = l.child_id
            JOIN {mapping} p ON p.old_id = l.parent_id
            WHERE c.new_id != p.new_id
            """
        )
    )
    connection.execute(sa.text("DELETE FROM itemparentlink"))
    connection.execute(
        sa.text(
            "INSERT INTO itemparentlink (child_id, parent_id) "
            "SELECT child_id, parent_id FROM _new_parent_links"
        )
    )
    connection.execute(sa.text("DROP TABLE _new_parent_links"))


def _break_parent_cycles(connection) -> None:
    """Detach one tag from each loop the remapping has closed.

    Remapping parents onto survivors can join tags into a loop without any tag
    becoming its own parent. For example, foo (under bar) and bar (under Foo)
    merge foo and Foo, leaving foo under bar and bar under foo. The lowest id in
    each loop is detached, which makes the result the same on every run.
    """
    parents = dict(connection.execute(sa.text("SELECT id, parent_id FROM tag")).all())
    finished: set[int] = set()
    for start in sorted(parents):
        if start in finished:
            continue
        path: list[int] = []
        position: dict[int, int] = {}
        current = start
        while current is not None and current not in finished:
            if current in position:
                loop = path[position[current] :]
                victim = min(loop)
                connection.execute(
                    sa.text("UPDATE tag SET parent_id = NULL WHERE id = :id"),
                    {"id": victim},
                )
                parents[victim] = None
                break
            position[current] = len(path)
            path.append(current)
            current = parents.get(current)
        finished.update(path)


def downgrade() -> None:
    """The constraints go; the merged rows cannot come back."""
    op.drop_index(op.f("ix_tag_name"), table_name="tag")
    op.drop_index(op.f("ix_item_uri"), table_name="item")
    op.create_index(op.f("ix_item_uri"), "item", ["uri"], unique=False)
