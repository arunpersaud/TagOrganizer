"""The bundled YuNet model must load, and a broken one must fail loudly.

count_faces returns 0 for a file it cannot read, so a model that cannot be
loaded would otherwise read as "no faces" on every photo, and no other test
would notice: blank frames contain no faces either way. These tests load the
model directly, and check that a missing or corrupt model raises through
count_faces rather than being swallowed.
"""

from pathlib import Path

import cv2
import pytest

from tagorganizer.plugins.builtin import detect_faces as module
from tagorganizer.plugins.builtin.detect_faces import count_faces

PORTRAIT = Path(__file__).parent / "data" / "lincoln_portrait.jpg"


@pytest.fixture
def fresh_detector():
    """The detector is cached for the whole run; a test that changes the model
    path must build its own, and must not leave one behind for the next test.
    """
    module._detector.cache_clear()
    yield
    module._detector.cache_clear()


def test_the_bundled_model_is_shipped(fresh_detector):
    assert module.MODEL_PATH.is_file()


def test_the_bundled_model_loads(fresh_detector):
    assert module._detector() is not None


def test_a_missing_model_raises(tmp_path):
    with pytest.raises(cv2.error):
        module._build_detector(tmp_path / "gone.onnx")


def test_a_corrupt_model_raises(tmp_path):
    path = tmp_path / "corrupt.onnx"
    path.write_bytes(b"this is not an onnx graph")
    with pytest.raises(cv2.error):
        module._build_detector(path)


def test_a_missing_model_is_not_reported_as_no_faces(
    fresh_detector, monkeypatch, tmp_path
):
    """The point of the whole file: the photo has a face in it, and the task
    must still stop with an error rather than tag nothing and report success.
    """
    monkeypatch.setattr(module, "MODEL_PATH", tmp_path / "gone.onnx")
    with pytest.raises(cv2.error):
        count_faces(PORTRAIT)


def test_a_corrupt_model_is_not_reported_as_no_faces(
    fresh_detector, monkeypatch, tmp_path
):
    path = tmp_path / "corrupt.onnx"
    path.write_bytes(b"this is not an onnx graph")
    monkeypatch.setattr(module, "MODEL_PATH", path)
    with pytest.raises(cv2.error):
        count_faces(PORTRAIT)
