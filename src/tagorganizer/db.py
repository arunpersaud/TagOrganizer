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

from pathlib import Path

from sqlmodel import SQLModel, create_engine, select, Session, func, delete
from sqlalchemy.orm import selectinload
import sqlalchemy as sa
from sqlalchemy import or_

from .models import Tag, Item, ItemTagLink
from .widgets.tag_bar import Filters

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
        existing_tag = session.exec(select(Tag).where(Tag.name == name)).first()
        if existing_tag:
            print(f"Tag with name '{name}' already exists with ID: {existing_tag.id}")
            return existing_tag.id

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


def delete_item(id: int):
    with Session(engine) as session:
        item = session.get(Item, id)
        if item:
            session.exec(delete(ItemTagLink).where(ItemTagLink.item_id == id))
            session.delete(item)
            session.commit()


def get_all_tags():
    with Session(engine) as session:
        results = session.exec(select(Tag))
        return results.all()


def set_parent_tag(child: Tag, parent: Tag):
    if child is None:
        print("No child given")
    if parent is None:
        print("No parent given")

    with Session(engine) as session:
        child.parent_id = parent.id
        session.add(child)
        session.commit()


def set_parent_tag_by_id(child_id: int, parent_id: int):
    with Session(engine) as session:
        child = session.get(Tag, child_id)
        parent = session.get(Tag, parent_id)
        if (not child) or (not parent):
            print(
                f"Could set parent_tag by id child_id {child_id} parent_id {parent_id}"
            )
            return
        child.parent_id = parent.id
        session.add(child)
        session.commit()


def add_images(files):
    with Session(engine) as session:
        for f in files:
            existing_item = session.exec(select(Item).where(Item.uri == str(f))).first()
            if existing_item:
                print(f"Item with uri '{f}' already exists with ID: {existing_item.id}")
                continue
            tmp = Item(uri=str(f))
            session.add(tmp)
        session.commit()


def add_image(filename):
    with Session(engine) as session:
        existing_item = session.exec(select(Item).where(Item.uri == filename)).first()
        if existing_item:
            print(
                f"Item with uri '{filename}' already exists with ID: {existing_item.id}"
            )
            return existing_item.id
        tmp = Item(uri=str(filename))
        session.add(tmp)
        session.commit()
        return tmp.id


def get_items_without_date() -> list[Item]:
    with Session(engine) as session:
        statement = select(Item).where(Item.date == sa.null())
        results = session.exec(statement)
        return results.all()


def get_items_without_location() -> list[Item]:
    with Session(engine) as session:
        statement = select(Item).where(Item.longitude == sa.null())
        results = session.exec(statement)
        return results.all()


def get_all_items_with_location():
    with Session(engine) as session:
        statement = select(Item).where(Item.longitude != sa.null())
        results = session.exec(statement)
        return results.all()


def get_all_items_not_in_dir(directories: list[Path], suffix: list[str]):
    with Session(engine) as session:
        tmp = []
        for e in suffix:
            tmp.append(e.lower())
            tmp.append(e.upper())

        query = select(Item)

        for directory in directories:
            query = query.where(~Item.uri.startswith(str(directory)))

        conditions = [Item.uri.endswith(ext) for ext in suffix]
        query = query.where(or_(*conditions))

        items = session.exec(query).all()
        return items


def update_items_in_db(items: list[Item]) -> None:
    with Session(engine) as session:
        for i in items:
            session.add(i)
        session.commit()


def get_all_tag_ids(tag_names: list[str]) -> list[int]:
    """Fetch all tag IDs including children for given tag names."""
    with Session(engine) as session:
        tag_ids = set()
        tags = session.exec(select(Tag).where(Tag.name.in_(tag_names))).all()

        def fetch_child_tags(tag):
            tag_ids.add(tag.id)
            if tag.children is None:
                return
            for child in tag.children:
                fetch_child_tags(child)

        for tag in tags:
            fetch_child_tags(tag)

        return list(tag_ids)


def filter_query(query, filter: Filters):
    # Filter by date range
    if filter.start_date:
        query = query.where(Item.date >= filter.start_date)
    if filter.end_date:
        query = query.where(Item.date <= filter.end_date)

    # Filter by geographical bounding box
    if filter.min_longitude is not None:
        query = query.where(Item.longitude >= filter.min_longitude)
    if filter.max_longitude is not None:
        query = query.where(Item.longitude <= filter.max_longitude)
    if filter.min_latitude is not None:
        query = query.where(Item.latitude >= filter.min_latitude)
    if filter.max_latitude is not None:
        query = query.where(Item.latitude <= filter.max_latitude)

    # Filter by tags
    if filter.tags:
        tag_ids = get_all_tag_ids(filter.tags)
        subquery = (
            select(ItemTagLink.item_id)
            .join(Tag, Tag.id == ItemTagLink.tag_id)
            .filter(Tag.id.in_(tag_ids))
            .group_by(ItemTagLink.item_id)
            .having(func.count(ItemTagLink.tag_id) == len(filter.tags))
            .subquery()
        )
        query = query.where(Item.id.in_(select(subquery.c.item_id)))

    if filter.no_time:
        query = query.where(Item.date == sa.null())
    if filter.no_gps:
        query = query.where(Item.latitude == sa.null())

    if filter.wrong_dir and filter.directories:
        for directory in filter.directories:
            query = query.where(~Item.uri.startswith(str(directory)))

    return query


def get_images(page: int = 0, filters: Filters | None = None) -> list[Item]:
    with Session(engine) as session:
        query = select(Item)
        if filters:
            query = filter_query(query, filters)

        # Sort by date in descending order
        query = query.order_by(Item.date.desc())

        # Pagination
        query = query.offset(25 * page).limit(25)

        items = session.exec(query).all()
        return items


def get_number_of_items(filters: Filters):
    with Session(engine) as session:
        query = select(func.count(Item.id))
        query = filter_query(query, filters)
        return session.exec(query).one()


def get_times_and_location_from_images(filters: Filters = None) -> list:
    with Session(engine) as session:
        query = select(Item.date, Item.longitude, Item.latitude)

        if filters:
            query = filter_query(query, filters)

        # Sort by date in descending order
        query = query.order_by(Item.date.desc())

        items = session.exec(query).all()

        dates = []
        coords = []
        for d, lon, lat in items:
            if d is not None:
                dates.append(d)
            if (lat is not None) and (lon is not None):
                coords.append((lat, lon))

        return dates, coords


def get_current_image(number, filters: Filters | None = None):
    with Session(engine) as session:
        query = select(Item)
        if filters:
            query = filter_query(query, filters)

        results = session.exec(query.offset(number).limit(1))
        return results.first()


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


def set_tag_photo_by_ids(item_id, tag_id):
    with Session(engine) as session:
        existing_item = session.exec(
            select(ItemTagLink).where(
                ItemTagLink.item_id == item_id, ItemTagLink.tag_id == tag_id
            )
        ).first()
        if existing_item:
            return

        tmp = ItemTagLink(item_id=item_id, tag_id=tag_id)
        session.add(tmp)
        session.commit()
