"""The query behind the map's clustering."""

from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item
from tagorganizer.widgets.tag_bar import Filters


class TestGetLocationsForFilter:
    def test_returns_id_lat_lon_for_located_items(self, temp_db):
        with Session(temp_db) as session:
            session.add(Item(uri="/p/a.jpg", latitude=1.0, longitude=2.0))
            session.commit()

        rows = db.get_locations_for_filter(None)
        assert len(rows) == 1
        item_id, lat, lon = rows[0]
        assert isinstance(item_id, int)
        assert (lat, lon) == (1.0, 2.0)

    def test_skips_items_missing_either_coordinate(self, temp_db):
        """A half-located item cannot be placed on the map."""
        with Session(temp_db) as session:
            session.add(Item(uri="/p/both.jpg", latitude=1.0, longitude=2.0))
            session.add(Item(uri="/p/nolat.jpg", longitude=2.0))
            session.add(Item(uri="/p/nolon.jpg", latitude=1.0))
            session.add(Item(uri="/p/neither.jpg"))
            session.commit()

        assert len(db.get_locations_for_filter(None)) == 1

    def test_honours_the_filter(self, temp_db):
        with Session(temp_db) as session:
            for i in range(3):
                session.add(
                    Item(uri=f"/p/{i}.jpg", latitude=float(i), longitude=float(i))
                )
            session.commit()
            ids = [i.id for i in session.exec(db.select(Item)).all()]

        rows = db.get_locations_for_filter(Filters(item_ids=ids[:2]))
        assert {r[0] for r in rows} == set(ids[:2])
