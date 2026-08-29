"""Session handling and profile switching.

Every query in db.py goes through new_session(), so these cover the two
things that behaviour has to get right: releasing the previous profile's
database, and failing clearly when no profile is loaded.
"""

import pytest
from sqlmodel import SQLModel

from tagorganizer import db
from tagorganizer.models import Item


class TestProfileSwitching:
    def test_switching_profiles_releases_the_previous_database(self, tmp_path):
        """set_engine must dispose the engine it replaces.

        Without this each switch left the old engine behind with a pooled
        connection still holding its database file open, and the Profiles
        menu can switch any number of times in one session.
        """
        previous = db.engine
        engines = []
        try:
            for i in range(3):
                db.set_engine(str(tmp_path / f"profile{i}.db"))
                SQLModel.metadata.create_all(db.engine)
                with db.new_session() as session:
                    session.add(Item(uri=f"/photo{i}.jpg"))
                    session.commit()
                engines.append(db.engine)

            for engine in engines[:-1]:
                assert engine.pool.checkedin() == 0
                assert engine.pool.checkedout() == 0
        finally:
            db.engine = previous

    def test_switching_profiles_changes_what_is_queried(self, tmp_path):
        previous = db.engine
        try:
            db.set_engine(str(tmp_path / "a.db"))
            SQLModel.metadata.create_all(db.engine)
            db.add_images(["/only/in/a.jpg"])
            assert db.get_number_of_items() == 1

            db.set_engine(str(tmp_path / "b.db"))
            SQLModel.metadata.create_all(db.engine)
            assert db.get_number_of_items() == 0, "still reading the old profile"

            db.set_engine(str(tmp_path / "a.db"))
            assert db.get_number_of_items() == 1, "did not return to the first profile"
        finally:
            db.engine = previous


class TestUnconfiguredDatabase:
    def test_querying_without_a_profile_raises_clearly(self):
        previous = db.engine
        db.engine = None
        try:
            with pytest.raises(RuntimeError, match="No database configured"):
                db.get_all_tags()
        finally:
            db.engine = previous
