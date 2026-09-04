"""Shared logic for the two plugins that move files into the library.

Underscore-prefixed so discovery skips it: it defines no plugin of its own.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

import logging
import shutil
from pathlib import Path

from tagorganizer import config
from tagorganizer.widgets.helper import (
    calculate_md5,
    calculate_xxhash,
    forget_thumbnail,
)

logger = logging.getLogger(__name__)


def destination_for(item, photo_dir: Path, video_dir: Path) -> Path | None:
    """Where this item belongs, or None if its type is not one we handle.

    Photos and videos go to different trees, then by capture date, so a
    library stays browsable on disk as well as in the app. Undated items go to
    'no-date', which FixNoDateFiles later empties once dates are known.
    """
    filepath = Path(item.uri)
    ext = filepath.suffix.lower()

    if ext in config.PHOTO_SUFFIX:
        root = Path(photo_dir)
    elif ext in config.VIDEO_SUFFIX:
        root = Path(video_dir)
    else:
        return None

    if item.date:
        target = (
            root
            / f"{item.date.year:04d}"
            / f"{item.date.month:02d}"
            / f"{item.date.day:02d}"
            / filepath.name
        )
    else:
        target = root / "no-date" / filepath.name

    # Normalise the extension case, so 'a.JPG' and 'a.jpg' cannot both exist.
    return target.with_suffix(ext)


def move_item(item, target: Path, ctx) -> bool:
    """Move one file and repoint its item. True if it moved.

    Never overwrites: two photos taken the same day can share a filename, and
    losing one silently would be unrecoverable.
    """
    source = Path(item.uri)

    if target.exists():
        ctx.message(f"File already exists in the correct directory: {target}")
        return False

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        old_md5 = item.uri_md5
        shutil.move(source, target)
        # The thumbnail cache is keyed on the uri hash, which changes with the
        # path, so the old entries could never be hit again.
        forget_thumbnail(old_md5, ctx.photos)
        item.uri = str(target)
        item.uri_md5 = calculate_md5(item.uri)
        item.data_xxhash = calculate_xxhash(target)
    except Exception as error:
        logger.exception("Failed to move %s to %s", source, target)
        ctx.message(f"Failed to move {source} to {target}: {error}")
        return False

    ctx.message(f"Moved {source} to {target}")
    return True
