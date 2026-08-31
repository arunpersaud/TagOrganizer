"""The background task that fills in video previews.

The generator is driven directly with a stand-in `main`, so no Qt event loop is
needed. TaskManager itself builds QWidgets for the progress bar, hence the
offscreen guard.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    widgets = pytest.importorskip("qtpy.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


class _Messages:
    def __init__(self):
        self.lines = []

    def add(self, text):
        self.lines.append(text)


class _Config:
    def __init__(self, photos):
        self.photos = Path(photos)
        self.videos = Path(photos)


class _Main:
    def __init__(self, photos):
        self.messages = _Messages()
        self.config = _Config(photos)


def _manager(tmp_path):
    from tagorganizer.tasks import TaskManager

    return TaskManager(_Main(tmp_path))


class TestTaskOrdering:
    def test_hashes_are_computed_before_previews(self, qapp, tmp_path):
        """Previews are keyed on uri_md5, which is empty until hashing runs.

        A preview built first would be written under an empty key and never
        found again, so the task would appear to succeed while nothing ever
        animates.
        """
        manager = _manager(tmp_path)
        manager.build_video_previews()

        assert len(manager.generators) == 2
        names = [gen.__name__ for gen in manager.generators]
        assert names[0] == "task_update_hashes"
        assert names[1] == "task_build_video_previews"


class TestPreviewGenerator:
    def test_yields_total_and_current_for_the_progress_bar(
        self, qapp, tmp_path, temp_db
    ):
        from sqlmodel import Session

        from tagorganizer import db
        from tagorganizer.models import Item

        with Session(db.engine) as session:
            for i in range(3):
                session.add(Item(uri=f"/v/{i}.mp4", uri_md5=f"{i:032x}"))
            session.commit()

        manager = _manager(tmp_path)
        progress = list(manager.task_build_video_previews())

        assert progress, "the generator must yield progress at least once"
        assert all(len(step) == 2 for step in progress)
        total = progress[0][0]
        assert total == 3

    def test_ignores_photos(self, qapp, tmp_path, temp_db):
        """Stills already cover photos; only videos get a sprite sheet."""
        from sqlmodel import Session

        from tagorganizer import db
        from tagorganizer.models import Item

        with Session(db.engine) as session:
            session.add(Item(uri="/p/a.jpg", uri_md5="a" * 32))
            session.add(Item(uri="/p/b.png", uri_md5="b" * 32))
            session.commit()

        manager = _manager(tmp_path)
        progress = list(manager.task_build_video_previews())

        assert progress[0][0] == 0

    def test_skips_videos_that_already_have_a_sheet(self, qapp, tmp_path, temp_db):
        """Re-running the task must not re-extract everything."""
        from sqlmodel import Session

        from tagorganizer import db
        from tagorganizer.models import Item
        from tagorganizer.widgets.helper import preview_file

        md5 = "c" * 32
        with Session(db.engine) as session:
            session.add(Item(uri="/v/done.mp4", uri_md5=md5))
            session.commit()

        existing = preview_file(md5, 150, tmp_path)
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"already here")

        manager = _manager(tmp_path)
        list(manager.task_build_video_previews())

        assert existing.read_bytes() == b"already here"
        assert any("skipped" in line.lower() for line in manager.main.messages.lines)


class TestWiring:
    """Structural guards for the two entry points, in the codebase's ast style."""

    def _main_source(self):
        import ast
        from pathlib import Path as P

        return ast.parse(
            (P(__file__).parent.parent / "src" / "tagorganizer" / "main.py").read_text()
        )

    def _function(self, tree, name):
        import ast

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    def test_add_directory_builds_previews_afterwards(self):
        """An imported batch of videos should animate without being asked."""
        import ast

        node = self._function(self._main_source(), "add_directory")
        assert node is not None
        called = {
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "build_video_previews" in called

    def test_the_task_is_in_the_tasks_menu(self):
        from pathlib import Path as P

        source = (
            P(__file__).parent.parent / "src" / "tagorganizer" / "main.py"
        ).read_text()
        assert "Build Video Previews" in source
