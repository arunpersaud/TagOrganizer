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

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine as sa_create_engine, text
from sqlmodel import Session, select

from . import db
from .models import Item, ItemTagLink

logger = logging.getLogger(__name__)


def import_f_spot(filename: Path):
    if not filename.is_file():
        logger.error(
            "[Error] f-spot database %s cannot be opened... existing", filename
        )
        sys.exit(2)

    logger.info("Importing from %s", filename)
    logger.info("Assuming this is an F-Spot database.")

    DATABASE_URL = f"sqlite:///{filename}"
    # Use raw SQLAlchemy engine to avoid registering F-Spot tables in SQLModel.metadata
    fspot_engine = sa_create_engine(DATABASE_URL)

    with fspot_engine.connect() as connection:
        logger.info("Trying to access the data...")

        # Check photos table exists and is readable
        try:
            result = connection.execute(
                text("SELECT id, time, base_uri, filename FROM photos LIMIT 20")
            )
            photos_check = result.fetchall()
            if not photos_check:
                logger.error("Could not open the photo table")
                sys.exit(1)
        except Exception:
            logger.error("Could not open the photo table")
            sys.exit(1)

        # Check tags table exists and is readable
        try:
            result = connection.execute(
                text("SELECT id, name, category_id FROM tags LIMIT 20")
            )
            tags_check = result.fetchall()
            if not tags_check:
                logger.error("Could not open the tags table")
                sys.exit(1)
        except Exception:
            logger.error("Could not open the tags table")
            sys.exit(1)

        # Check photo_tags table exists and is readable
        try:
            result = connection.execute(
                text("SELECT photo_id, tag_id FROM photo_tags LIMIT 20")
            )
            photostags_check = result.fetchall()
            if not photostags_check:
                logger.error("Could not open the photo-tag link table")
                sys.exit(1)
        except Exception:
            logger.error("Could not open the photo-tag link table")
            sys.exit(1)

        logger.info("Access was successfull!")

    # Import tags
    logger.info("Importing tags...")
    with fspot_engine.connect() as connection:
        result = connection.execute(text("SELECT id, name, category_id FROM tags"))
        tags = result.fetchall()

    tag_lookup = {}  # from F-spot ID to new id
    for tag_row in tags:
        fspot_id, name, category_id = tag_row
        new_id = db.add_tag(name)
        tag_lookup[fspot_id] = new_id

    # Set parent relationships
    for tag_row in tags:
        fspot_id, name, category_id = tag_row
        if category_id and category_id > 0:
            child_id = tag_lookup[fspot_id]
            parent_id = tag_lookup[category_id]
            db.set_parent_tag_by_id(child_id, parent_id)

    logger.info("Importing tags...done")

    # Import images with optimized transaction handling
    logger.info("Importing images...")
    with fspot_engine.connect() as connection:
        result = connection.execute(
            text("SELECT id, time, base_uri, filename FROM photos")
        )
        photos = result.fetchall()

    photos_lookup = {}  # from F-spot ID to new id

    # Use a single session for all photo inserts to reduce transactions
    with Session(db.engine) as session:
        for photo_row in photos:
            fspot_id, time, base_uri, filename_col = photo_row

            filename = f"{base_uri}/{filename_col}"
            filename = filename.removeprefix("file://")

            # fix special characters that f-spot escaped
            filename = filename.replace("%20", " ")
            filename = filename.replace("%26", "&")

            file = Path(filename)
            if not file.is_file():
                logger.warning("Image %s does not exist...skipping", file)
                continue

            # Check if already in db
            existing = session.exec(select(Item).where(Item.uri == filename)).first()
            if existing:
                logger.warning("Item with uri '%s' already exists in DB", filename)
                photos_lookup[fspot_id] = existing.id
                continue

            # Create item with date from F-Spot timestamp
            item = Item(uri=str(filename))
            if time and time > 0:
                try:
                    # Convert Unix timestamp to UTC datetime (naive)
                    item.date = datetime.fromtimestamp(time, tz=timezone.utc).replace(
                        tzinfo=None
                    )
                except (ValueError, OSError):
                    # Handle invalid timestamps - leave date as None
                    item.date = None

            session.add(item)
            session.flush()  # Get the id without committing
            photos_lookup[fspot_id] = item.id

        session.commit()

    logger.info("Importing images...done")

    # Add links between images and tags with optimized transaction handling
    logger.info("Adding links between images and tags")
    with fspot_engine.connect() as connection:
        result = connection.execute(text("SELECT photo_id, tag_id FROM photo_tags"))
        photostags = result.fetchall()

    # Use a single session for all link inserts to reduce transactions
    with Session(db.engine) as session:
        for photo_tag_row in photostags:
            photo_id, tag_id = photo_tag_row

            tag_id_new = tag_lookup.get(tag_id)
            item_id = photos_lookup.get(photo_id)

            if (tag_id_new is None) or (item_id is None):
                logger.warning("[Warning] missing ids... skipping one tag<->item pair")
                continue

            # Check if link already exists
            existing = session.exec(
                select(ItemTagLink).where(
                    ItemTagLink.item_id == item_id,
                    ItemTagLink.tag_id == tag_id_new,
                )
            ).first()
            if existing:
                continue

            link = ItemTagLink(item_id=item_id, tag_id=tag_id_new)
            session.add(link)

        session.commit()

    logger.info("Adding links between images and tags...done")

    logger.info("Import done")
    sys.exit(0)
