"""Layout and import regression tests for the Single view.

Unlike the rest of the suite these need a real widget tree: a layout ratchet
cannot be observed without one. They run under the offscreen Qt platform and
skip when Qt cannot start.
"""

import ast
import os
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SINGLE_ITEM = (
    Path(__file__).parent.parent / "src" / "tagorganizer" / "widgets" / "single_item.py"
)


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
    assert (
        len(set(min_hint_widths)) == 1
    ), f"window minimumSizeHint().width() ratcheted: {min_hint_widths}"


def test_vlc_is_not_imported_at_module_scope():
    """A missing libvlc must not stop the application from starting.

    python-vlc resolves the shared library during import and raises when it is
    absent, so a module-scope import makes VLC a hard requirement for viewing
    photos.
    """
    tree = ast.parse(SINGLE_ITEM.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            assert (
                "vlc" not in names
            ), "vlc must be imported lazily, not at module scope"


def test_set_video_does_not_seek_before_playing():
    """Opening a video must start it at the beginning, not a tenth of the way in."""
    tree = ast.parse(SINGLE_ITEM.read_text())
    set_video = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "set_video":
            set_video = node
            break
    assert set_video is not None, "set_video not found"

    for node in ast.walk(set_video):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert (
                node.func.attr != "set_position"
            ), "set_video must not seek before playback starts"
