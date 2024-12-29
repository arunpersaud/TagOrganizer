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

    children: list["Tag"] = Relationship(
        back_populates="parent", sa_relationship_kwargs={"remote_side": "[Tag.id]"}
    )
    parent: Optional["Tag"] = Relationship(back_populates="children")

    items: list["Item"] = Relationship(back_populates="tags", link_model=ItemTagLink)


class Item(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    uri: str
    uri_md5: str = Field(default="")
    data_xxhash: str = Field(default="")
    camera: str | None = Field(default=None, index=True)
    date: datetime | None = Field(default=None, index=True)

    tags: list[Tag] = Relationship(back_populates="items", link_model=ItemTagLink)
