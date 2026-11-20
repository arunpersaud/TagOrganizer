"""
Copyright 2024 Arun Persaud.

This file is part of TagOrganizer.

TagOrganizer is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at
your option) any later version.

TagOrganizer is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with TagOrganizer. If not, see <https://www.gnu.org/licenses/>.

"""

from sqlmodel import SQLModel, Field, Relationship
from pydantic import NaiveDatetime

from typing import Optional

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = SQLModel.metadata
metadata.naming_convention = NAMING_CONVENTION


class ItemTagLink(SQLModel, table=True):
    item_id: int | None = Field(default=None, foreign_key="item.id", primary_key=True)
    tag_id: int | None = Field(default=None, foreign_key="tag.id", primary_key=True)


class ItemParentLink(SQLModel, table=True):
    """Records that one item was derived from another.

    A panorama has several parents, an edit has one, and a derived photo can
    itself be the source of another - so this is a link table rather than a
    column. Both ends are item ids; the pair is the primary key, which makes
    recording the same parent twice a no-op rather than a duplicate row.
    """

    child_id: int | None = Field(default=None, foreign_key="item.id", primary_key=True)
    parent_id: int | None = Field(default=None, foreign_key="item.id", primary_key=True)


class Tag(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    parent_id: int | None = Field(default=None, foreign_key="tag.id")

    parent: Optional["Tag"] = Relationship(
        sa_relationship_kwargs={"remote_side": "Tag.id"}
    )
    children: list["Tag"] = Relationship(
        back_populates="parent", sa_relationship_kwargs={"remote_side": "Tag.parent_id"}
    )

    items: list["Item"] = Relationship(back_populates="tags", link_model=ItemTagLink)


class Item(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    uri: str = Field(index=True, unique=True)
    uri_md5: str = Field(default="")
    data_xxhash: str = Field(default="", index=True)
    camera: str | None = Field(default=None, index=True)
    # Naive local time, which is what metadata.py produces. sqlmodel rejects
    # naive values in a plain datetime column, so the type has to say naive.
    date: NaiveDatetime | None = Field(default=None, index=True)

    # location
    longitude: float | None = Field(default=None, index=True)
    latitude: float | None = Field(default=None, index=True)

    # Faces found by the face task. None means not checked yet, which is every
    # video and every photo the task has not run over; 0 means checked, none.
    face_count: int | None = Field(default=None)
    # Set by the Find Missing Files task. None means never checked.
    file_missing: bool | None = Field(default=None)

    tags: list[Tag] = Relationship(back_populates="items", link_model=ItemTagLink)

    def __hash__(self):
        # Unsaved items have no id yet, so fall back to identity. __eq__ below
        # matches that, keeping the "a == b implies hash(a) == hash(b)"
        # invariant intact for sets, dicts and lru_cache.
        if self.id is None:
            return id(self)
        return hash((type(self).__name__, self.id))

    def __eq__(self, other):
        if not isinstance(other, Item):
            return NotImplemented
        if self.id is None or other.id is None:
            # Two unsaved items are only equal if they are the same object;
            # comparing None to None would otherwise call every unsaved item
            # equal to every other one.
            return self is other
        return self.id == other.id
