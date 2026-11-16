"""
Copyright 2024 Arun Persaud.

This file is part of TagOrganizer.

TagOrganizer is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at
your option) any later version.

TagOrganizer is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with TagOrganizer. If not, see <https://www.gnu.org/licenses/>.

"""

from functools import lru_cache
import hashlib
import io
import logging
from pathlib import Path

from qtpy.QtWidgets import QCompleter
from qtpy.QtGui import QPixmap, QTransform, QImage, QPainter
from qtpy.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool

import exifread as exif
import cv2
import xxhash

from .. import config
from ..metadata import heif_brand
from ..models import Item

logger = logging.getLogger(__name__)


def get_thumbnail_path(photos_path: Path) -> Path:
    """Where cached thumbnails live for this photo directory.

    Beside the photos, on every platform. A thumbnail is a legible copy of the
    photo, so keeping it here means it inherits whatever protection the original
    has - an encrypted photo directory does not leak readable copies into an
    unencrypted cache. This also retires the old Linux branch, which wrote into
    the shared freedesktop cache while naming files after the md5 of the bare
    path, where the specification requires the md5 of the file:// URI: those
    entries were unusable by any other viewer.
    """
    return photos_path / "thumbnails"


def thumbnail_file(md5: str, size: int, photos_path: Path) -> Path:
    """Where the cached thumbnail for this uri hash and width lives.

    The size belongs in the path. Thumbnails are requested at 150 px and again
    at the tile width once the grid is resized, and with a single path per file
    the larger decode overwrote the smaller one and was then handed back to
    every later request regardless of the size it asked for.
    """
    thumbnail_path = get_thumbnail_path(photos_path)
    return thumbnail_path / str(size) / md5[:2] / f"{md5[2:]}.png"


# A video preview is 40 frames laid out 8 across and 5 down in one PNG. One
# file per video keeps it in the cache we already have, and slicing a frame out
# at display time costs nothing.
SPRITE_COLUMNS = 8
SPRITE_ROWS = 5
SPRITE_FRAMES = SPRITE_COLUMNS * SPRITE_ROWS


def frame_positions(frame_count: int, wanted: int = SPRITE_FRAMES) -> list[int]:
    """Evenly spaced source frames to sample for a preview.

    A clip shorter than `wanted` frames yields one position per frame rather
    than repeating frames to pad the sheet: a duplicated frame reads as a
    stutter, which looks like a broken preview rather than a short video.
    """
    if frame_count <= 0:
        return []
    n = min(wanted, frame_count)
    return [int(i * frame_count / n) for i in range(n)]


def sprite_frame_rect(index: int, frame_width: int, frame_height: int):
    """Where frame `index` sits in the sheet, as (x, y, w, h)."""
    return (
        (index % SPRITE_COLUMNS) * frame_width,
        (index // SPRITE_COLUMNS) * frame_height,
        frame_width,
        frame_height,
    )


def preview_file(md5: str, size: int, photos_path: Path) -> Path:
    """Where a video's animated preview lives.

    Its own subtree under the thumbnail cache, so a sprite sheet can never be
    confused with a still and the two can be cleared independently.
    """
    return (
        get_thumbnail_path(photos_path)
        / "preview"
        / str(size)
        / md5[:2]
        / f"{md5[2:]}.png"
    )


def build_video_preview(item: Item, size: int, photos_path: Path) -> bool:
    """Extract a sprite sheet of evenly spaced frames for a video.

    Returns True only when a sheet was written. An existing sheet is left alone:
    the task that calls this runs repeatedly and re-extracting every video each
    time would be pure waste.

    Frames are reached by seeking rather than by decoding the whole file -
    measured at 0.66 s against 2.37 s for a 60 second clip.
    """
    if not item.uri_md5:
        return False

    target = preview_file(item.uri_md5, size, photos_path)
    if target.is_file():
        return False

    filepath = Path(item.uri)
    if not filepath.is_file():
        logger.warning("cannot find video %s", filepath)
        return False

    cap = cv2.VideoCapture(str(filepath))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    positions = frame_positions(total)
    if not positions:
        cap.release()
        logger.warning("%s: no readable frames for a preview", filepath)
        return False

    frames = []
    for position in positions:
        cap.set(cv2.CAP_PROP_POS_FRAMES, position)
        success, frame = cap.read()
        if not success:
            continue
        height, width = frame.shape[:2]
        scaled_height = max(1, round(size * height / width))
        small = cv2.resize(frame, (size, scaled_height))
        frames.append(
            QImage(small.data, size, scaled_height, 3 * size, QImage.Format_RGB888)
            .rgbSwapped()
            .copy()
        )
    cap.release()

    if not frames:
        logger.warning("%s: could not read any frame for a preview", filepath)
        return False

    frame_height = frames[0].height()
    sheet = QImage(
        SPRITE_COLUMNS * size, SPRITE_ROWS * frame_height, QImage.Format_RGB32
    )
    sheet.fill(0)
    painter = QPainter(sheet)
    for index, frame in enumerate(frames):
        x, y, _, _ = sprite_frame_rect(index, size, frame_height)
        painter.drawImage(x, y, frame)
    painter.end()

    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(target), "PNG")
    return True


def save_thumbnail(image, md5: str, size: int, photos_path: Path) -> None:
    """Write a thumbnail to the cache.

    Accepts a QImage or a QPixmap - both provide save(). QImage is the one used
    from worker threads, since QPixmap may only be touched on the GUI thread.
    """
    thumbnail = thumbnail_file(md5, size, photos_path)
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(thumbnail), "PNG")


def cached_hashes(photos_path: Path):
    """Every cached file, as (uri hash, path).

    The hash is rebuilt from the layout - two directory characters plus the
    file stem - so both the stills tree and the preview tree are covered by
    one walk.
    """
    root = get_thumbnail_path(photos_path)
    if not root.is_dir():
        return
    for path in root.rglob("*.png"):
        prefix = path.parent.name
        if len(prefix) != 2:
            continue
        yield prefix + path.stem, path


def forget_thumbnail(uri_md5: str, photos_path: Path) -> None:
    """Drop every cached size for this uri hash.

    Called when a file moves: the hash is taken over the path, so once the file
    is somewhere else the old entries can never be hit again and would sit in
    the cache forever.
    """
    if not uri_md5:
        return
    root = get_thumbnail_path(photos_path)
    if not root.is_dir():
        return
    # Both the stills and the preview subtree: a moved video changes its uri
    # hash, so anything left behind under the old one can never be hit again.
    roots = [root]
    preview_root = root / "preview"
    if preview_root.is_dir():
        roots.append(preview_root)

    for base in roots:
        for size_dir in base.iterdir():
            if not size_dir.is_dir() or size_dir.name == "preview":
                continue
            candidate = size_dir / uri_md5[:2] / f"{uri_md5[2:]}.png"
            if candidate.is_file():
                candidate.unlink()


def load_qimage(item: Item, size: int, photos_path: Path) -> QImage | None:
    """Decode an image to QImage (safe for off-thread use).

    This function handles the actual decode work for both photos and videos,
    returning a QImage that can be constructed off-thread. EXIF rotation is
    applied to the QImage directly. Both halves of the thumbnail cache live
    here: a hit returns the cached PNG, and a fresh decode writes one. Doing
    the write here rather than at display time is what lets the preloader
    populate the cache for items no widget is showing yet.

    Args:
        item: The Item to load
        size: Target width in pixels
        photos_path: Path to photos directory

    Returns:
        QImage ready for QPixmap.fromImage() on GUI thread, or None if the
        file cannot be decoded.
    """
    filepath = Path(item.uri)

    if not filepath.is_file():
        logger.warning("cannot find file %s", filepath)
        return None

    file = str(filepath)

    # Check thumbnail cache first. A hit returns straight away without
    # re-saving: rewriting the same PNG on every page view is pure disk churn.
    if item.uri_md5:
        thumbnail = thumbnail_file(item.uri_md5, size, photos_path)
        if thumbnail.is_file():
            return QImage(str(thumbnail))

    # Decode based on file type
    if filepath.suffix.lower() in config.PHOTO_SUFFIX:
        qimage = QImage(file)
        if qimage.isNull():
            return None
        qimage = qimage.scaledToWidth(size, Qt.SmoothTransformation)
        orientation = get_orientation(file)
        qimage = rotate_qimage(qimage, orientation)
    elif filepath.suffix.lower() in config.VIDEO_SUFFIX:
        cap = cv2.VideoCapture(file)

        time = 1  # in s

        # Set the position of the frame to capture
        cap.set(cv2.CAP_PROP_POS_MSEC, time * 1000)

        success, frame = cap.read()

        if not success:
            logger.error(
                "%s: failed to capture a frame at %s s for the thumbnail",
                filepath,
                time,
            )
            cap.release()
            return None

        # Convert the frame to a QImage
        height, width, channel = frame.shape
        bytes_per_line = 3 * width
        qimage = QImage(
            frame.data, width, height, bytes_per_line, QImage.Format_RGB888
        ).rgbSwapped()

        # Release the video capture object
        cap.release()
    else:
        logger.error("%s: don't know how to create a thumbnail", filepath)
        return None

    # Write the cache entry here, on whichever thread decoded it. QImage.save
    # is safe off-thread, and doing it here is what makes preloading worth
    # anything: the preloader discards the decoded image, so if the save only
    # happened when a widget displayed the result, preloading would burn CPU
    # and cache nothing.
    if item.uri_md5:
        save_thumbnail(qimage, item.uri_md5, size, photos_path)

    return qimage


@lru_cache(1_000)
def load_pixmap(item: Item, size: int, photos_path: Path) -> QPixmap | None:
    """Load a thumbnail as a QPixmap (GUI thread only).

    This wraps load_qimage() and adds the QPixmap construction, which must
    happen on the GUI thread. Prefer the asynchronous ThumbnailLoader for
    anything on a hot path - this one decodes inline and will block.

    Args:
        item: The Item to load
        size: Target width in pixels
        photos_path: Path to photos directory

    Returns:
        QPixmap ready to display, or None if the file cannot be loaded.
    """
    qimage = load_qimage(item, size, photos_path)
    if qimage is None:
        return None

    # load_qimage has already written the cache entry if there was one to write.
    return QPixmap.fromImage(qimage)


@lru_cache(100)
def load_full_pixmap(file):
    pixmap = QPixmap(file)
    orientation = get_orientation(file)
    pixmap = rotate_pixmap(pixmap, orientation)

    return pixmap


@lru_cache(1_000)
def load_exif(file):
    file = Path(file)
    if not file.is_file():
        return {}

    brand = heif_brand(file)
    if brand is not None and brand != b"heic":
        # exifread dispatches on the exact bytes b"ftypheic" and returns
        # nothing for every other HEIF brand, though the reader behind that
        # check handles them all. Presenting the file under the brand it does
        # recognise is the smallest honest fix; the alternative is
        # reimplementing its container walk.
        data = bytearray(file.read_bytes())
        data[8:12] = b"heic"
        return exif.process_file(io.BytesIO(bytes(data)))

    with file.open("rb") as f:
        return exif.process_file(f)


def get_orientation(file):
    tags = load_exif(file)
    orientation_tag = "Image Orientation"
    if orientation_tag in tags:
        orientation = tags[orientation_tag].values[0]
    else:
        orientation = 1  # Default to normal orientation if tag is not found
    return orientation


def rotate_qimage(qimage: QImage, orientation: int) -> QImage:
    """Rotate a QImage based on EXIF orientation (safe for off-thread).

    Args:
        qimage: The QImage to rotate
        orientation: EXIF orientation value (1-8)

    Returns:
        Rotated QImage
    """
    transform = QTransform()
    if orientation == 3:
        transform.rotate(180)
    elif orientation == 6:
        transform.rotate(90)
    elif orientation == 8:
        transform.rotate(-90)
    return qimage.transformed(transform, Qt.SmoothTransformation)


def rotate_pixmap(pixmap: QPixmap, orientation: int) -> QPixmap:
    """Rotate a QPixmap based on EXIF orientation (GUI thread only).

    Args:
        pixmap: The QPixmap to rotate
        orientation: EXIF orientation value (1-8)

    Returns:
        Rotated QPixmap
    """
    transform = QTransform()
    if orientation == 3:
        transform.rotate(180)
    elif orientation == 6:
        transform.rotate(90)
    elif orientation == 8:
        transform.rotate(-90)
    return pixmap.transformed(transform, Qt.SmoothTransformation)


class CommaCompleter(QCompleter):
    def __init__(self, model, parent=None):
        super().__init__(model, parent)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def splitPath(self, path: str) -> list[str]:
        return [path.split(",")[-1].strip()]


def calculate_md5(input_string: str) -> str:
    md5_hash = hashlib.md5()
    md5_hash.update(input_string.encode("utf-8"))
    md5_hex = md5_hash.hexdigest()

    return md5_hex


def calculate_xxhash(file_path: Path) -> str:
    hasher = xxhash.xxh128()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(4096), b""):
            hasher.update(chunk)

    xxhash_hex = hasher.hexdigest()

    return xxhash_hex


class _ResultReady:
    """Container for result to pass back to GUI thread."""

    def __init__(self, key, qimage: QImage):
        self.key = key
        self.qimage = qimage


class ThumbnailResultEmitter(QObject):
    """Emits thumbnail_ready signal from worker thread results.

    This is a helper to safely emit signals from worker threads by
    using Qt's signal-slot mechanism, which handles thread switching.
    """

    thumbnail_ready = Signal(object, QImage)  # (item id, size) key, image
    _result_ready = Signal(object)  # Signal to receive result from worker thread

    def __init__(self):
        super().__init__()
        # Connect internal signal to emit the actual result
        self._result_ready.connect(self._emit_result)

    def _emit_result(self, result: _ResultReady) -> None:
        """Receive result from worker thread and emit signal on GUI thread."""
        self.thumbnail_ready.emit(result.key, result.qimage)

    def handle_result(self, key, qimage: QImage) -> None:
        """Called from worker thread to deliver result via signal.

        A file Qt cannot decode comes back as None, and the signal is typed
        QImage: emitting None aborts the process rather than raising. That is
        reachable for any format the local Qt build lacks - HEIC on a machine
        without qtimageformats, for instance.

        A null QImage is sent instead of nothing at all. The tile already
        knows how to render a failed decode - it shows the file name - and
        dropping the result silently left it saying "generating preview..."
        forever about a file that will never decode.
        """
        if qimage is None:
            logger.debug("no thumbnail could be decoded for %s", key)
            qimage = QImage()
        self._result_ready.emit(_ResultReady(key, qimage))


class ThumbnailLoadRunnable(QRunnable):
    """Worker thread task to decode a thumbnail image.

    Decodes the thumbnail on a worker thread and emits the result via
    the provided emitter. Prevents GUI thread blocking during decode.
    """

    def __init__(
        self,
        key,
        item: Item,
        size: int,
        photos_path: Path,
        emitter: ThumbnailResultEmitter,
    ):
        """Initialize the runnable.

        Args:
            key: (item id, size) this decode answers for
            item: Item to load thumbnail for
            size: Target thumbnail width
            photos_path: Path to photos directory
            emitter: ThumbnailResultEmitter to deliver result
        """
        super().__init__()
        self.key = key
        self.item = item
        self.size = size
        self.photos_path = photos_path
        self.emitter = emitter

    def run(self):
        """Decode the thumbnail (runs on worker thread)."""
        try:
            qimage = load_qimage(self.item, self.size, self.photos_path)
        except Exception:
            # A decode failure must never take down a pool thread, and the
            # loader still has to hear about it or the key leaks and that
            # thumbnail can never be requested again.
            logger.exception("failed to decode thumbnail for %s", self.item.uri)
            qimage = None
        # Emit signal via the emitter (Qt handles thread switching)
        self.emitter.handle_result(self.key, qimage)


class ThumbnailLoader(QObject):
    """Thread pool for decoding thumbnails off the GUI thread.

    Maintains a QThreadPool and emits signals when thumbnails are ready.
    Allows widgets to request thumbnail decoding without blocking the GUI.

    Results are addressed by (generation, item id, size) rather than by
    requesting widget. That is what lets the preloader and a visible tile share
    one decode: a tile takes any result matching the item it is showing, whoever
    asked for it, and ignores results for the item it used to show. Addressing by
    widget would mean a tile whose item was already queued by the preloader never
    heard back, because the result carried somebody else's id.

    Item ids are only unique within one profile's database, so the generation
    changes whenever the profile does. Results from an earlier generation are
    dropped on arrival.

    Signals:
        thumbnail_ready(key: tuple, qimage: QImage)
    """

    thumbnail_ready = Signal(object, QImage)

    def __init__(self, max_threads: int = 3):
        """Initialize the thumbnail loader.

        Args:
            max_threads: Maximum number of concurrent decode threads
        """
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max_threads)
        # Create emitter to deliver results back to GUI thread
        self.emitter = ThumbnailResultEmitter()
        self.emitter.thumbnail_ready.connect(self._on_ready)
        self._generation = 0
        # Decodes already queued or running, keyed by (generation, item id, size).
        # The preloader offers the same items again on every tick, and a page it
        # already asked for is still in the queue - without this the pool
        # accumulates duplicate work faster than three threads can drain it.
        self._inflight = set()

    @property
    def generation(self) -> int:
        return self._generation

    def new_generation(self) -> None:
        """Forget everything requested for the profile that was open before.

        Decodes already running still finish, but their results are dropped when
        they arrive, and nothing made before this point blocks a new request.
        """
        self._generation += 1
        self._inflight.clear()

    def _on_ready(self, key, qimage) -> None:
        if key[0] != self._generation:
            # Decoded for a profile that is no longer open. Its item ids may
            # name different photos now, so it must not reach any tile.
            return
        self._inflight.discard(key)
        self.thumbnail_ready.emit(key, qimage)

    def key_for(self, item: Item, size: int):
        """The key a result for this item and size will carry."""
        return (self._generation, item.id, size)

    def load(self, item: Item, size: int, photos_path: Path) -> None:
        """Request a thumbnail to be decoded.

        Requests for an item and size already queued are dropped: the result
        that is already coming will be delivered to everyone waiting on it.
        """
        key = self.key_for(item, size)
        if key in self._inflight:
            return
        self._inflight.add(key)

        runnable = ThumbnailLoadRunnable(key, item, size, photos_path, self.emitter)
        self.pool.start(runnable)

    def pending(self) -> int:
        """How many decodes are queued or running (used by tests)."""
        return len(self._inflight)


# Global thumbnail loader instance
_thumbnail_loader = None


def get_thumbnail_loader() -> ThumbnailLoader:
    """Get or create the global thumbnail loader instance."""
    global _thumbnail_loader
    if _thumbnail_loader is None:
        _thumbnail_loader = ThumbnailLoader()
    return _thumbnail_loader
