"""Finding faces and tagging the photos that have them.

A Haar cascade answers "is there a face here", not "whose face is it".
Naming people needs embeddings and a set of labelled examples to compare
against, which is a different piece of work; this tags photos that contain
faces so they can be found at all.

The detector itself is exercised against real images, but only to the extent
of "it runs and finds nothing in a blank frame" - a photograph of a face
cannot be committed to the repository, and Haar will not fire on anything
synthesisable here. Everything above the detector is tested with a stub.
"""

import numpy as np
import pytest
from sqlmodel import Session, select

from tagorganizer import db
from tagorganizer.models import Item, ItemTagLink, Tag
from tagorganizer.plugins.builtin import detect_faces as module
from tagorganizer.plugins.builtin.detect_faces import DetectFaces, count_faces
from tagorganizer.plugins.context import TaskContext
from tagorganizer.scope import Scope, resolve_scope


def write_image(path, width=200, height=200, value=128):
    import cv2

    frame = np.full((height, width, 3), value, dtype=np.uint8)
    cv2.imwrite(str(path), frame)
    return path


def run(plugin, tmp_path, scope=Scope.LIBRARY):
    messages = []
    ctx = TaskContext(scope, tmp_path, tmp_path, messages.append)
    list(plugin.run(ctx))
    return messages


def tags_on(item_id):
    with db.new_session() as session:
        rows = session.exec(
            select(Tag.name)
            .join(ItemTagLink, ItemTagLink.tag_id == Tag.id)
            .where(ItemTagLink.item_id == item_id)
        ).all()
    return sorted(rows)


class TestCountFacesAgainstRealImages:
    def test_a_blank_image_has_no_faces(self, tmp_path):
        assert count_faces(write_image(tmp_path / "blank.jpg")) == 0

    def test_noise_has_no_faces(self, tmp_path):
        """A false positive on random data would tag the whole library."""
        import cv2

        rng = np.random.default_rng(0)
        frame = rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)
        path = tmp_path / "noise.jpg"
        cv2.imwrite(str(path), frame)

        assert count_faces(path) == 0

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        assert count_faces(tmp_path / "gone.jpg") == 0

    def test_a_file_that_is_not_an_image_is_not_an_error(self, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("hello")
        assert count_faces(path) == 0

    def test_a_detector_failure_is_swallowed(self, tmp_path, monkeypatch):
        """OpenCV raises on some malformed input, and one bad file must not
        stop a task part way through a library.

        Forced, because a file cv2 merely cannot read returns None and never
        reaches the guard - it is images it half-understands that raise.
        """
        import cv2

        def explode(*args, **kwargs):
            raise cv2.error("bad input")

        monkeypatch.setattr(module.cv2, "imread", explode)
        assert count_faces(write_image(tmp_path / "a.jpg")) == 0

    def test_a_very_large_image_is_handled(self, tmp_path):
        """Detection runs on a downscaled copy, or a 40MP photo takes seconds."""
        assert count_faces(write_image(tmp_path / "big.jpg", 4000, 3000)) == 0


class TestTagging:
    @pytest.fixture
    def photo(self, temp_db, tmp_path):
        path = write_image(tmp_path / "a.jpg")
        with Session(temp_db) as session:
            item = Item(uri=str(path))
            session.add(item)
            session.commit()
            session.refresh(item)
            return item.id

    def test_a_photo_with_a_face_is_tagged(self, photo, tmp_path, monkeypatch):
        monkeypatch.setattr(module, "count_faces", lambda path: 1)
        run(DetectFaces(), tmp_path)
        assert tags_on(photo) == [DetectFaces.TAG]

    def test_a_photo_without_a_face_is_left_alone(self, photo, tmp_path, monkeypatch):
        monkeypatch.setattr(module, "count_faces", lambda path: 0)
        run(DetectFaces(), tmp_path)
        assert tags_on(photo) == []

    def test_running_twice_does_not_duplicate_the_tag(
        self, photo, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(module, "count_faces", lambda path: 2)
        run(DetectFaces(), tmp_path)
        run(DetectFaces(), tmp_path)
        assert tags_on(photo) == [DetectFaces.TAG]

    def test_it_reports_how_many_it_tagged(self, photo, tmp_path, monkeypatch):
        monkeypatch.setattr(module, "count_faces", lambda path: 1)
        messages = run(DetectFaces(), tmp_path)
        assert any("1" in m for m in messages), messages


class TestWhatItLooksAt:
    def test_videos_are_skipped(self, temp_db, tmp_path, monkeypatch):
        """Detecting on a video file would decode it as an image and fail."""
        looked = []
        monkeypatch.setattr(
            module, "count_faces", lambda path: looked.append(path) or 0
        )
        with Session(temp_db) as session:
            session.add(Item(uri=str(tmp_path / "clip.mp4")))
            session.commit()

        run(DetectFaces(), tmp_path)
        assert looked == []

    def test_only_the_selection_is_examined(self, temp_db, tmp_path, monkeypatch):
        looked = []
        monkeypatch.setattr(
            module, "count_faces", lambda path: looked.append(path) or 0
        )
        ids = []
        with Session(temp_db) as session:
            for name in ("a.jpg", "b.jpg"):
                item = Item(uri=str(write_image(tmp_path / name)))
                session.add(item)
                session.commit()
                session.refresh(item)
                ids.append(item.id)

        run(DetectFaces(), tmp_path, resolve_scope(ids[:1]))
        assert len(looked) == 1

    def test_it_stops_when_cancelled(self, temp_db, tmp_path, monkeypatch):
        looked = []
        monkeypatch.setattr(
            module, "count_faces", lambda path: looked.append(path) or 1
        )
        with Session(temp_db) as session:
            for name in ("a.jpg", "b.jpg", "c.jpg"):
                session.add(Item(uri=str(write_image(tmp_path / name))))
            session.commit()

        ctx = TaskContext(Scope.LIBRARY, tmp_path, tmp_path, lambda text: None)
        ctx.cancel()
        list(DetectFaces().run(ctx))

        assert looked == []


class TestDeclaration:
    def test_it_can_run_on_a_selection(self):
        """Detection is slow, so being able to aim it matters."""
        assert DetectFaces().accepts_selection is True

    def test_it_does_not_run_automatically(self):
        """It would make every import take minutes."""
        assert DetectFaces().auto is False

    def test_it_appears_under_tags(self):
        assert DetectFaces().category == "Tags"
