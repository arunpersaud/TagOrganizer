"""Missing files: library entries whose file is no longer on disk.

"Find Missing Files" checks each file and records the answer; the "Missing
file" chip lists the ones it found, for the user to remove from the library
with the ordinary delete. Nothing is removed automatically.
"""

from pathlib import Path

import pytest
from sqlmodel import Session

from tagorganizer import db
from tagorganizer.models import Item
from tagorganizer.plugins.builtin.find_missing_files import FindMissingFiles
from tagorganizer.plugins.context import TaskContext
from tagorganizer.scope import Scope, resolve_scope
from tagorganizer.widgets.tag_bar import Condition, Filters


@pytest.fixture
def library(temp_db, tmp_path):
    """here.jpg exists; gone.jpg does not."""
    (tmp_path / "here.jpg").write_bytes(b"x")
    ids = {}
    with Session(temp_db) as session:
        for name in ("here", "gone"):
            item = Item(uri=str(tmp_path / f"{name}.jpg"))
            session.add(item)
            session.commit()
            session.refresh(item)
            ids[name] = item.id
    return ids


def run(scope, tmp_path, messages=None):
    ctx = TaskContext(
        scope,
        Path(tmp_path),
        Path(tmp_path),
        messages.append if messages is not None else (lambda text: None),
    )
    return list(FindMissingFiles().run(ctx))


def flags(ids):
    return {item.id: item.file_missing for item in db.get_items_by_ids(list(ids))}


class TestTheTask:
    def test_it_records_which_files_are_gone(self, library, tmp_path):
        run(Scope.LIBRARY, tmp_path)
        assert flags(library.values()) == {
            library["here"]: False,
            library["gone"]: True,
        }

    def test_a_file_put_back_is_cleared_on_the_next_run(self, library, tmp_path):
        run(Scope.LIBRARY, tmp_path)
        (tmp_path / "gone.jpg").write_bytes(b"back")

        run(Scope.LIBRARY, tmp_path)

        assert flags([library["gone"]]) == {library["gone"]: False}

    def test_a_selection_leaves_the_others_unchecked(self, library, tmp_path):
        run(resolve_scope([library["gone"]]), tmp_path)
        assert flags(library.values()) == {library["here"]: None, library["gone"]: True}

    def test_it_reports_the_count_and_warns_about_unplugged_drives(
        self, library, tmp_path
    ):
        messages = []
        run(Scope.LIBRARY, tmp_path, messages)
        text = "\n".join(messages)
        assert "missing: 1 of 2" in text
        assert "Missing file" in text
        assert "mounted" in text

    def test_a_cancelled_run_reports_how_far_it_got(self, library, tmp_path):
        messages = []
        ctx = TaskContext(
            Scope.LIBRARY, Path(tmp_path), Path(tmp_path), messages.append
        )
        steps = FindMissingFiles().run(ctx)
        next(steps)
        ctx.cancel()
        list(steps)
        assert "missing: 0 of 1 checked (cancelled)" in messages

    def test_it_yields_progress(self, library, tmp_path):
        assert run(Scope.LIBRARY, tmp_path)

    def test_declaration(self):
        plugin = FindMissingFiles()
        assert plugin.category == "Maintenance"
        assert plugin.accepts_selection is True
        assert plugin.auto is False


class TestTheFilter:
    @pytest.fixture
    def checked(self, library, tmp_path):
        run(Scope.LIBRARY, tmp_path)
        return library

    def test_the_chip_lists_only_missing_files(self, checked):
        found = db.get_images(0, Filters(missing_file=True))
        assert [item.id for item in found] == [checked["gone"]]

    def test_unchecked_items_are_not_listed(self, library):
        assert db.get_images(0, Filters(missing_file=True)) == []

    def test_it_ors_with_another_condition(self, checked):
        filters = Filters(
            groups=[[Condition("missing_file", True), Condition("no_time", True)]]
        )
        assert len(db.get_images(0, filters)) == 2
