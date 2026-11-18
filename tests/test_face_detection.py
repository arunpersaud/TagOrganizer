"""Finding faces and tagging the photos that have them.

The face detector answers "is there a face here", not "whose face is it".
Naming people needs embeddings and a set of labelled examples to compare
against, which is a different piece of work; this tags photos that contain
faces so they can be found at all.

The detector is exercised against one committed photograph of a face (see
tests/data/NOTE.md for its source and license), a blank frame and random noise.
Everything above the detector is tested with a stub.
"""

from pathlib import Path

import numpy as np
import pytest
from sqlmodel import Session, select

from tagorganizer import db
from tagorganizer.models import Item, ItemTagLink, Tag
from tagorganizer.plugins.builtin import detect_faces as module
from tagorganizer.plugins.builtin.detect_faces import DetectFaces, count_faces
from tagorganizer.plugins.context import TaskContext
from tagorganizer.scope import Scope, resolve_scope

PORTRAIT = Path(__file__).parent / "data" / "lincoln_portrait.jpg"


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
    def test_a_photograph_of_a_face_is_found(self):
        assert count_faces(PORTRAIT) >= 1

    def test_one_face_is_counted_once(self):
        """The network proposes several overlapping boxes for one face (seven
        for this portrait); suppression must merge them, or the task's
        "faces in total" counts each face many times."""
        assert count_faces(PORTRAIT) == 1

    def test_two_faces_side_by_side_are_counted_separately(self, tmp_path):
        """Merging works per face: two people in one photo are two faces,
        not one and not fourteen."""
        import cv2

        portrait = cv2.imread(str(PORTRAIT))
        path = tmp_path / "two.png"
        cv2.imwrite(str(path), np.hstack([portrait, portrait]))

        assert count_faces(path) == 2

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
        assert count_faces(write_image(tmp_path / "big.jpg", 4000, 3000)) == 0

    def test_a_large_image_is_detected_at_reduced_size(self, tmp_path, monkeypatch):
        """Detection runs on a downscaled copy, or a 40MP photo takes seconds.

        The detector is wrapped, not replaced: the spy records the size the
        detector is asked to work at and then does the real detection.
        """
        real = module._detector()
        seen = []

        class Spy:
            def setInputSize(self, size):
                seen.append(("input", size))
                real.setInputSize(size)

            def detect(self, image):
                seen.append(("image", image.shape))
                return real.detect(image)

        monkeypatch.setattr(module, "_detector", lambda: Spy())
        count_faces(write_image(tmp_path / "big.jpg", 4000, 3000))

        widths = [size[0] if kind == "input" else size[1] for kind, size in seen]
        assert widths and max(widths) <= module.MAX_WIDTH, seen

    def test_a_large_portrait_is_still_found(self, tmp_path):
        """The reduction must not lose the face: upscale the portrait to a
        large frame, so the copy the detector sees is the reduced one."""
        import cv2

        image = cv2.imread(str(PORTRAIT))
        large = cv2.resize(image, (2400, int(image.shape[0] * 2400 / image.shape[1])))
        path = tmp_path / "large_portrait.jpg"
        cv2.imwrite(str(path), large)
        assert count_faces(path) >= 1


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

    def test_a_real_portrait_is_tagged_through_the_plugin(self, temp_db, tmp_path):
        """No stub anywhere: the photograph goes through count_faces and the
        real TaskContext tagging path, the way a user's run does."""
        path = tmp_path / "portrait.jpg"
        path.write_bytes(PORTRAIT.read_bytes())
        with Session(temp_db) as session:
            item = Item(uri=str(path))
            session.add(item)
            session.commit()
            session.refresh(item)
            item_id = item.id

        run(DetectFaces(), tmp_path)
        assert tags_on(item_id) == [DetectFaces.TAG]

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
