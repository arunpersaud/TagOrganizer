"""Plugins yield on a steady cadence, not only when they have work to flush.

The runner stops a plugin only at a yield, and the cancel button is the only
way out of a long run. A plugin that skips its yields while a stretch of
items adds nothing to its batch cannot be stopped until that stretch ends.
These tests drive stretches of items that change nothing and check that the
plugin still yields at least every ten items.
"""

import itertools
from datetime import datetime

import pytest

from tagorganizer.models import Item
from tagorganizer.plugins.builtin.fix_no_date_files import FixNoDateFiles
from tagorganizer.plugins.builtin.list_files_not_in_db import ListFilesNotInDb
from tagorganizer.plugins.builtin.list_files_outside_dirs import ListFilesOutsideDirs
from tagorganizer.plugins.builtin.move_files import MoveFiles
from tagorganizer.plugins.builtin.update_hashes import UpdateHashes
from tagorganizer.plugins.builtin.update_locations import UpdateLocations
from tagorganizer.plugins.builtin.update_timestamps import UpdateTimestamps
from tagorganizer.plugins.context import TaskContext
from tagorganizer.scope import Scope

COUNT = 30
MAX_GAP = 10


def _yields(plugin, ctx):
    return [current for _, current in plugin.run(ctx)]


def _assert_steady(yields):
    assert yields, "the plugin never yielded"
    points = [0, *yields]
    gaps = [b - a for a, b in itertools.pairwise(points)]
    assert max(gaps) <= MAX_GAP, f"went {max(gaps)} items without a yield"


@pytest.fixture
def ctx(tmp_path):
    photos = tmp_path / "photos"
    videos = tmp_path / "videos"
    photos.mkdir()
    videos.mkdir()
    return TaskContext(Scope.LIBRARY, photos, videos, lambda text: None)


def _add_items(uris, **fields):
    from tagorganizer import db

    with db.new_session() as session:
        for uri in uris:
            session.add(Item(uri=uri, **fields))
        session.commit()


class TestSteadyYields:
    def test_update_hashes_over_files_that_are_gone(self, temp_db, ctx, tmp_path):
        _add_items([str(tmp_path / f"gone{i}.jpg") for i in range(COUNT)])
        _assert_steady(_yields(UpdateHashes(), ctx))

    def test_update_locations_over_files_that_are_gone(self, temp_db, ctx, tmp_path):
        _add_items([str(tmp_path / f"gone{i}.jpg") for i in range(COUNT)])
        _assert_steady(_yields(UpdateLocations(), ctx))

    def test_update_timestamps_over_files_that_are_gone(self, temp_db, ctx, tmp_path):
        _add_items([str(tmp_path / f"gone{i}.jpg") for i in range(COUNT)])
        _assert_steady(_yields(UpdateTimestamps(), ctx))

    def test_list_files_not_in_db_over_files_it_skips(self, temp_db, ctx):
        """Ignored files take the path that used to skip the yield."""
        for i in range(COUNT):
            (ctx.photos / f"{i}.DS_Store").write_text("x")
        _assert_steady(_yields(ListFilesNotInDb(), ctx))

    def test_list_files_outside_dirs_over_missing_files(self, temp_db, ctx, tmp_path):
        _add_items([str(tmp_path / "elsewhere" / f"gone{i}.jpg") for i in range(COUNT)])
        _assert_steady(_yields(ListFilesOutsideDirs(), ctx))

    def test_fix_no_date_files_over_missing_files(self, temp_db, ctx):
        no_date = ctx.photos / "no-date"
        _add_items(
            [str(no_date / f"gone{i}.jpg") for i in range(COUNT)],
            date=datetime(2020, 1, 1),
        )
        _assert_steady(_yields(FixNoDateFiles(), ctx))

    def test_move_files_over_missing_files(self, temp_db, ctx, tmp_path):
        _add_items([str(tmp_path / "elsewhere" / f"gone{i}.jpg") for i in range(COUNT)])
        _assert_steady(_yields(MoveFiles(), ctx))
