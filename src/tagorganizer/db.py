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

from sqlmodel import SQLModel, create_engine, select, Session, func, delete
from sqlalchemy.orm import selectinload

from .models import Tag, Item, ItemTagLink

engine = None


def set_engine(db_dir: str):
    global engine
    engine = create_engine(f"sqlite:///{db_dir}")


def create_db():
    SQLModel.metadata.create_all(engine)


def get_tag(name):
    with Session(engine) as session:
        return session.exec(select(Tag).where(Tag.name == name)).first()


def get_tag_by_id(id):
    with Session(engine) as session:
        return session.exec(select(Tag).where(Tag.id == id)).first()


def add_tag(name):
    with Session(engine) as session:
        new_tag = Tag(name=name)
        session.add(new_tag)
        session.commit()
        return new_tag.id


def delete_tag(id: int):
    with Session(engine) as session:
        tag = session.get(Tag, id)
        if tag:
            if tag.children:
                print("[WARNING] cannot delete this tag, since it has subtags")
                return
            # unclear if this is needed or can be optimized by setting
            # other flags in the model
            session.exec(delete(ItemTagLink).where(ItemTagLink.tag_id == id))
            session.delete(tag)
            session.commit()


def get_all_tags():
    with Session(engine) as session:
        results = session.exec(select(Tag))
        return results.all()


def set_parent_tag(child, parent):
    if child is None:
        print("No child given")
    if parent is None:
        print("No parent given")

    with Session(engine) as session:
        child.parent_id = parent.id
        session.add(child)
        session.commit()


def add_images(files):
    with Session(engine) as session:
        for f in files:
            tmp = Item(uri=str(f))
            session.add(tmp)
        session.commit()


def get_images(page=0):
    with Session(engine) as session:
        results = session.exec(select(Item).offset(25 * page).limit(25))
        return results.all()


def get_current_image(number):
    with Session(engine) as session:
        results = session.exec(select(Item).offset(number).limit(1))
        return results.one()


def get_number_of_items():
    with Session(engine) as session:
        statement = select(func.count(Item.id))
        return session.exec(statement).one()


def get_common_tags(items: list[Item]) -> list[Tag]:
    with Session(engine) as session:
        # Load items and their tags
        items = session.exec(
            select(Item)
            .where(Item.id.in_([item.id for item in items]))
            .options(selectinload(Item.tags))
        ).all()

        # Extract sets of tags for each item
        tag_sets = [set([t.name for t in item.tags]) for item in items]

        # Find the intersection of all tag sets
        if tag_sets:
            common_tags = set.intersection(*tag_sets)
        else:
            common_tags = set()

        return list(common_tags)


def set_tags(items: list[Item], tags: list[Tag]) -> None:
    with Session(engine) as session:
        items = session.exec(
            select(Item)
            .where(Item.id.in_([item.id for item in items]))
            .options(selectinload(Item.tags))
        ).all()

        tags = session.exec(
            select(Tag).where(Tag.id.in_([tag.id for tag in tags]))
        ).all()

        # Add each tag to each item if not already associated
        for item in items:
            for tag in tags:
                if tag not in item.tags:
                    item.tags.append(tag)

        session.commit()
