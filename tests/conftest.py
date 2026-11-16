"""Shared pytest fixtures.

The application keeps its engine in a module-level global (``db.engine``), so
every fixture here is responsible for pointing that global at a throwaway
database and restoring it afterwards. ``qapp`` is the one QApplication the whole
suite shares. Only a test that asks for it creates one, so the pure-logic layer
stays testable without Qt.
"""

import os
import pathlib
from datetime import datetime

import pytest
from sqlmodel import Session, SQLModel

from tagorganizer import db
from tagorganizer.models import Item, ItemTagLink, Tag

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """The one QApplication the whole suite shares.

    Qt allows a single instance per process, and the program name matters:
    QApplication([]) leaves Chromium without argv[0], so constructing the map
    widget aborts. Sharing one instance also stops the answer depending on
    which test module happened to run first.
    """
    widgets = pytest.importorskip("qtpy.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication(
        ["tagorganizer-tests"]
    )


@pytest.fixture
def temp_db(tmp_path):
    """Point ``db.engine`` at an empty database with the current schema."""
    previous = db.engine
    db.set_engine(str(tmp_path / "media-test.db"))
    SQLModel.metadata.create_all(db.engine)
    try:
        yield db.engine
    finally:
        db.engine.dispose()
        db.engine = previous


@pytest.fixture
def db_path(tmp_path):
    """A path for a database that does not exist yet.

    For tests that need to exercise database *creation* rather than use an
    already-created one.
    """
    previous = db.engine
    try:
        yield tmp_path / "media-new.db"
    finally:
        if db.engine is not None and db.engine is not previous:
            db.engine.dispose()
        db.engine = previous


@pytest.fixture
def seeded_db(temp_db):
    """Four dated items and a parent/child tag pair, with known tag links.

    Dates ascend with the index, so ordering by ``date`` descending puts
    ``/p/3.jpg`` first. Tag links are arranged to cover the hierarchical filter
    cases: parent only, child only, both, and untagged.

    Returns a dict with ``items`` (ordered by index), ``parent`` and ``child``.
    """
    with Session(temp_db) as session:
        items = [
            Item(uri=f"/p/{i}.jpg", date=datetime(2020, 1, 1 + i)) for i in range(4)
        ]
        for item in items:
            session.add(item)

        parent = Tag(name="Travel")
        session.add(parent)
        session.commit()
        session.refresh(parent)

        child = Tag(name="Japan", parent_id=parent.id)
        session.add(child)
        session.commit()
        session.refresh(child)

        for item in items:
            session.refresh(item)

        session.add(ItemTagLink(item_id=items[0].id, tag_id=parent.id))
        session.add(ItemTagLink(item_id=items[1].id, tag_id=child.id))
        session.add(ItemTagLink(item_id=items[2].id, tag_id=parent.id))
        session.add(ItemTagLink(item_id=items[2].id, tag_id=child.id))
        session.commit()

        return {
            "items": [Item(id=item.id, uri=item.uri, date=item.date) for item in items],
            "parent": Tag(id=parent.id, name=parent.name),
            "child": Tag(id=child.id, name=child.name, parent_id=child.parent_id),
        }


def alembic_head() -> str:
    """The head revision of the migration chain, read from the scripts.

    Asserting against this rather than a hard-coded revision string means these
    tests keep testing what they mean - "the database is stamped at the latest
    migration" - instead of breaking every time a migration is added.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from tagorganizer import migrations

    root = pathlib.Path(migrations.__file__).parent
    config = Config(str(root.parent / "alembic.ini"))
    config.set_main_option("script_location", str(root))
    return ScriptDirectory.from_config(config).get_current_head()
