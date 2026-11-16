"""Layout and import regression tests for the Single view.

Unlike the rest of the suite these need a real widget tree: a layout ratchet
cannot be observed without one. They run under the offscreen Qt platform and
skip when Qt cannot start.
"""

import os
import subprocess
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_photo_item_does_not_grow_when_reshown(qapp):
    """Navigating in the Single view must not resize the window.

    Every cursor key press re-runs set_photo, so any size feedback shows up as
    a window that creeps larger with each press. The real widget hierarchy
    (QTabWidget between layout and photo) is required to observe the ratchet.
    """
    from qtpy.QtCore import Qt
    from qtpy.QtGui import QPixmap
    from qtpy.QtWidgets import QHBoxLayout, QMainWindow, QTabWidget, QWidget

    from tagorganizer.widgets.single_item import SingleItem

    # Mock the main object that SingleItem needs for messaging
    class MockMessages:
        def add(self, msg):
            pass

    class MockMain:
        def __init__(self):
            self.messages = MockMessages()

    window = QMainWindow()
    central = QWidget()
    window.setCentralWidget(central)
    layout = QHBoxLayout(central)
    tabs = QTabWidget()
    layout.addWidget(tabs)

    main = MockMain()
    single_item = SingleItem(main)
    tabs.addTab(single_item, "Single")

    photo = single_item.photo
    window.resize(900, 600)
    window.show()
    qapp.processEvents()

    source = QPixmap(4000, 3000)
    source.fill(Qt.darkGreen)
    tags = {f"EXIF Tag{i}": f"value-{i}-abcdefghijklmnop" for i in range(30)}

    sizes = []
    min_hint_widths = []
    for _ in range(10):
        photo.setPixmap(
            source.scaled(photo.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        photo.show_exif(tags)
        qapp.processEvents()
        sizes.append((window.width(), window.height()))
        min_hint_widths.append(window.minimumSizeHint().width())

    assert len(set(sizes)) == 1, f"window size drifted across redraws: {sizes}"
    assert len(set(min_hint_widths)) == 1, (
        f"window minimumSizeHint().width() ratcheted: {min_hint_widths}"
    )


def test_the_application_starts_without_libvlc():
    """A missing libvlc must not stop the application from starting.

    python-vlc resolves the shared library during import and raises when it is
    absent, so a module-scope import makes VLC a hard requirement for viewing
    photos. A subprocess is used so the import is really the first one: with
    ``vlc`` set to None in sys.modules, any import of it raises.
    """
    code = (
        "import sys\n"
        "sys.modules['vlc'] = None\n"
        "import tagorganizer.widgets.single_item\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


class _FakePlayer:
    """Stands in for a libvlc media player, recording every call made on it."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args):
            self.calls.append(name)
            return 0

        return record


def test_set_video_does_not_seek_before_playing(qapp, monkeypatch):
    """Opening a video must start it at the beginning, not a tenth of the way in."""
    import vlc

    from tagorganizer.models import Item
    from tagorganizer.widgets.single_item import VideoItem

    player = _FakePlayer()

    class FakeInstance:
        def media_player_new(self):
            return player

        def media_new(self, uri):
            return f"media:{uri}"

    monkeypatch.setattr(vlc, "Instance", FakeInstance)
    video = VideoItem()

    video.set_video(Item(id=1, uri="/videos/clip.mp4"))

    assert "set_media" in player.calls
    assert "set_position" not in player.calls
    assert "set_time" not in player.calls


class _FakeVideo:
    """Records what the single view asks of its player."""

    def __init__(self):
        self.stops = 0
        self.shown = None

    def stopVideo(self):
        self.stops += 1

    def setVisible(self, visible):
        self.shown = visible


def _single_view(qapp):
    from types import SimpleNamespace

    from tagorganizer.widgets.single_item import SingleItem

    messages = []
    main = SimpleNamespace(messages=SimpleNamespace(add=messages.append))
    return SingleItem(main), messages


def _png(path):
    from qtpy.QtGui import QImage

    image = QImage(40, 30, QImage.Format_RGB32)
    image.fill(0x804020)
    assert image.save(str(path), "PNG")
    return str(path)


def test_switching_to_a_photo_stops_a_video_that_was_playing(qapp, tmp_path):
    """Audio from the previous video must not carry on over a photo."""
    from tagorganizer.models import Item

    view, _ = _single_view(qapp)
    video = _FakeVideo()
    view.video = video
    view.set_item(Item(id=1, uri=_png(tmp_path / "still.png")))

    assert video.stops == 1
    assert video.shown is False


def test_leaving_the_single_view_stops_the_video(qapp):
    """Hiding the tab must silence the player, which is otherwise still running."""
    view, _ = _single_view(qapp)
    video = _FakeVideo()
    view.video = video
    view.show()
    qapp.processEvents()

    view.hide()

    assert video.stops == 1


def test_a_missing_file_replaces_the_previous_photo(qapp, tmp_path):
    """Keeping the old photo on screen shows the wrong picture under a missing name."""
    from qtpy.QtWidgets import QLabel

    from tagorganizer.models import Item

    view, messages = _single_view(qapp)
    view.set_item(Item(id=1, uri=_png(tmp_path / "kept.png")))
    assert not QLabel.pixmap(view.photo.item).isNull()

    gone = str(tmp_path / "gone.png")
    view.set_item(Item(id=2, uri=gone))

    assert (
        QLabel.pixmap(view.photo.item) is None
        or QLabel.pixmap(view.photo.item).isNull()
    )
    assert "gone.png" in view.photo.item.text()
    assert messages and "does not exist" in messages[-1]


def test_a_photo_that_will_not_decode_says_so_rather_than_raising(qapp, tmp_path):
    from qtpy.QtWidgets import QLabel

    from tagorganizer.models import Item

    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    view, _ = _single_view(qapp)

    view.set_item(Item(id=3, uri=str(broken)))

    assert (
        QLabel.pixmap(view.photo.item) is None
        or QLabel.pixmap(view.photo.item).isNull()
    )
    assert "cannot display" in view.photo.item.text()
