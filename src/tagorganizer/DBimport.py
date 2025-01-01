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

import sys
from pathlib import Path

from sqlmodel import SQLModel, Field, create_engine, Session, select

from . import db


def import_f_spot(filename: Path):
    if not filename.is_file():
        print(f"[Error] f-spot database {filename} cannot be opened... existing")
        sys.exit(2)

    print("Importing from ", filename)
    print("Assuming this is an F-Spot database.")

    class FSPOT_Tag(SQLModel, table=True):
        __tablename__ = "tags"
        id: int | None = Field(default=None, primary_key=True)
        name: str
        category_id: int | None = Field(default=None, foreign_key="tags.id")
        is_category: bool
        sort_priority: int | None = Field(default=None)
        icon: str | None = Field(default=None)

    class FSPOT_Photo(SQLModel, table=True):
        __tablename__ = "photos"
        id: int | None = Field(default=None, primary_key=True)
        time: int
        base_uri: str
        filename: str
        description: str
        roll_id: int
        default_version_id: int
        rating: int | None = Field(default=None)

    class FSPOT_PhotoTag(SQLModel, table=True):
        __tablename__ = "photo_tags"
        photo_id: int | None = Field(
            default=None, foreign_key="photos.id", primary_key=True
        )
        tag_id: int | None = Field(
            default=None, foreign_key="tags.id", primary_key=True
        )

    DATABASE_URL = f"sqlite:///{filename}"
    engine = create_engine(DATABASE_URL)

    with Session(engine) as f_spot_session:
        print("Trying to access the data...")
        photos = f_spot_session.exec(select(FSPOT_Photo).limit(20)).all()
        if not photos:
            print("Could not open the photo table")
            sys.exit(1)
        for p in photos:
            print(f"{p.base_uri}/{p.filename}")

        tags = f_spot_session.exec(select(FSPOT_Tag).limit(20)).all()
        if not tags:
            print("Could not open the tags table")
            sys.exit(1)

        photostags = f_spot_session.exec(select(FSPOT_PhotoTag).limit(20)).all()
        if not photostags:
            print("Could not open the photo-tag link table")
            sys.exit(1)
        for p in photostags:
            print(p)
        print("Access was successfull!")

        print("Importing tags...")
        tags = f_spot_session.exec(select(FSPOT_Tag)).all()
        tag_lookup = {}  # from F-spot ID to new id
        for t in tags:
            id = db.add_tag(t.name)
            tag_lookup[t.id] = id
        for t in tags:
            if t.category_id > 0:
                child_id = tag_lookup[t.id]
                parent_id = tag_lookup[t.category_id]
                db.set_parent_tag_by_id(child_id, parent_id)
        print("Importing tags...done")

        print("Importing images...")
        photos = f_spot_session.exec(select(FSPOT_Photo)).all()
        photos_lookup = {}  # from F-spot ID to new id
        for p in photos:
            filename = f"{p.base_uri}/{p.filename}"
            filename = filename.removeprefix("file://")
            file = Path(filename)
            if not file.is_file():
                print(f"Image {file} does not exist...skipping")
                continue
            id = db.add_image(filename)
            photos_lookup[p.id] = id
        print("Importing images...done")

        print("Adding links between images and tags")
        photostags = f_spot_session.exec(select(FSPOT_PhotoTag)).all()
        for p in photostags:
            tag_id = tag_lookup[p.tag_id]
            item_id = photos_lookup[p.photo_id]

            db.set_tag_photo_by_ids(item_id, tag_id)
        print("Adding links between images and tags...done")

    print("Import done")
    sys.exit(0)
