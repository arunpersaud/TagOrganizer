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
from datetime import datetime

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


class Tag(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
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
    uri: str
    uri_md5: str = Field(default="")
    data_xxhash: str = Field(default="")
    camera: str | None = Field(default=None, index=True)
    date: datetime | None = Field(default=None, index=True)

    # location
    longitude: float | None = Field(default=None, index=True)
    latitude: float | None = Field(default=None, index=True)

    tags: list[Tag] = Relationship(back_populates="items", link_model=ItemTagLink)

    def __hash__(self):
        return self.id

    def __eq__(self, other):
        if isinstance(other, Item):
            return self.id == other.id
        return False
