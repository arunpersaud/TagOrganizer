"""Reading dates and places out of files.

Everything here is a pure reader: hand it a path, get back a value or None.
Nothing touches the database, so the plugins stay thin and this stays testable
against files the tests build byte by byte.

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

import logging
import re
from datetime import datetime
from pathlib import Path

# Silence hachoir before its parsers are imported: it prints a [warn] line for
# every parser it tries and rejects, and a task running over a whole library
# would bury the console. This project logs rather than prints, deliberately.
import hachoir.core.config as _hachoir_config

_hachoir_config.quiet = True

from hachoir.metadata import extractMetadata  # noqa: E402
from hachoir.parser import createParser  # noqa: E402

logger = logging.getLogger(__name__)

# Cameras, phones and messaging apps write the date into the name in a handful
# of shapes. Ordered most specific first, so a name that carries a time is not
# matched by the date-only pattern and silently rounded to midnight.
_FILENAME_PATTERNS = [
    re.compile(
        r"(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})[_\-T]"
        r"(?P<h>\d{2})(?P<m>\d{2})(?P<s>\d{2})"
    ),
    re.compile(
        r"(?P<Y>\d{4})-(?P<M>\d{2})-(?P<D>\d{2})[ _T](?:at )?"
        r"(?P<h>\d{2})[.\-:](?P<m>\d{2})[.\-:](?P<s>\d{2})"
    ),
    re.compile(r"(?P<Y>\d{4})-(?P<M>\d{2})-(?P<D>\d{2})"),
    re.compile(r"(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})"),
]

# Digital photography does not predate this, and a date in the future is a
# misparse rather than a photograph.
_EARLIEST_YEAR = 1900


def date_from_filename(name: str) -> datetime | None:
    """The capture date encoded in a filename, if one plausibly is.

    Deliberately conservative. This is the last resort in the date chain and
    the only step that is a guess: a wrong date silently misfiles a photo and
    scatters the timeline, and nothing records which dates were guessed. When
    the digits do not form a plausible date, return None and let the item stay
    undated - it lands in no-date/, where a later run can still rescue it.
    """
    for pattern in _FILENAME_PATTERNS:
        for match in pattern.finditer(name):
            parts = match.groupdict()
            try:
                found = datetime(
                    int(parts["Y"]),
                    int(parts["M"]),
                    int(parts["D"]),
                    int(parts.get("h") or 0),
                    int(parts.get("m") or 0),
                    int(parts.get("s") or 0),
                )
            except ValueError:
                # Digits in the right shape but not a real date or time, such
                # as month 33. Keep looking rather than giving up on the name.
                continue
            if _EARLIEST_YEAR <= found.year <= datetime.now().year + 1:
                return found
    return None


def video_date(path) -> datetime | None:
    """The creation time recorded in a video container.

    Covers mp4, mov, avi, mkv, wmv and flv through hachoir. Returns None for
    anything it cannot read: an unreadable file is not an error here, just an
    item that keeps whatever date it already had.
    """
    path = Path(path)
    if not path.is_file():
        return None
    try:
        parser = createParser(str(path))
        if parser is None:
            return None
        with parser:
            metadata = extractMetadata(parser)
        if metadata is None or not metadata.has("creation_date"):
            return None
        found = metadata.get("creation_date")
    except Exception:
        # hachoir raises a wide variety of things on malformed input, and none
        # of it should stop a task part way through a library.
        logger.debug("no container date for %s", path, exc_info=True)
        return None
    return found if isinstance(found, datetime) else None


def _box_header(handle, offset: int, end: int):
    """The kind and extent of the box starting at ``offset``, or None.

    Returns ``(kind, body_start, box_end)``. Three size encodings exist in the
    ISO-BMFF family: a 32-bit length, size 1 meaning a 64-bit length follows
    (boxes over 4 GB, which is where a phone video's moov can end up when mdat
    comes first), and size 0 meaning the box runs to the end of its container.
    Anything that would reach past ``end`` is refused rather than trusted.
    """
    if end - offset < 8:
        return None
    handle.seek(offset)
    header = handle.read(8)
    if len(header) < 8:
        return None
    size = int.from_bytes(header[:4], "big")
    kind = header[4:8]
    header_len = 8
    if size == 1:
        largesize = handle.read(8)
        if len(largesize) < 8:
            return None
        size = int.from_bytes(largesize, "big")
        header_len = 16
        if size < header_len:
            return None
    elif size == 0:
        size = end - offset
    elif size < 8:
        return None
    box_end = offset + size
    if box_end > end:
        return None
    return kind, offset + header_len, box_end


def _find_box(handle, start: int, end: int, path: list[bytes]):
    """Locate a nested box by path, e.g. [b"moov", b"udta"].

    Returns the ``(body_start, body_end)`` of the last box named, or None. The
    file is walked with seeks, skipping every box it does not need, so a large
    mdat in front of moov is never read. Each step moves forward by at least a
    header's length, so the walk cannot loop.
    """
    want, rest = path[0], path[1:]
    offset = start
    while offset < end:
        box = _box_header(handle, offset, end)
        if box is None:
            return None
        kind, body_start, box_end = box
        if kind == want:
            if not rest:
                return body_start, box_end
            return _find_box(handle, body_start, box_end, rest)
        offset = box_end
    return None


# A ©xyz location string is a few dozen bytes. Anything much larger under that
# name is not one, and reading it whole would be the very memory cost the
# streaming walk exists to avoid.
_MAX_XYZ_BYTES = 64 * 1024


# ISO 6709, as written into the ©xyz box: +40.7128-074.0060/. The sign is
# mandatory, which is what lets the two numbers be told apart without knowing
# how many digits each uses.
_ISO6709 = re.compile(rb"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


def video_gps(path) -> tuple[float, float] | None:
    """Latitude and longitude from a video's ©xyz box.

    Only the ISO-BMFF family (mp4, mov, m4v, 3gp) records GPS at all, and
    hachoir does not surface it, so the box is read directly.
    """
    path = Path(path)
    if not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            file_size = handle.tell()
            span = _find_box(handle, 0, file_size, [b"moov", b"udta", b"\xa9xyz"])
            if span is None:
                return None
            body_start, body_end = span
            if body_end - body_start > _MAX_XYZ_BYTES:
                return None
            handle.seek(body_start)
            payload = handle.read(body_end - body_start)
    except OSError:
        return None

    # Two bytes of text length and two of language code precede the string.
    # No test fails if the slice is dropped - those four bytes happen never to
    # look like coordinates - but skipping them is what the format says, and
    # the regex should not be relied on to reject a header it was never meant
    # to see.
    match = _ISO6709.search(payload[4:])
    if match is None:
        return None
    try:
        return float(match.group(1)), float(match.group(2))
    except ValueError:
        return None


# The HEIF family as written by phones and cameras. exifread recognises only
# the first of these and returns nothing for the rest, even though its HEIC
# reader handles them all.
HEIF_BRANDS = frozenset(
    [
        b"heic",
        b"heix",
        b"hevc",
        b"hevx",
        b"heim",
        b"heis",
        b"hevm",
        b"hevs",
        b"mif1",
        b"msf1",
    ]
)


def heif_brand(path) -> bytes | None:
    """The HEIF brand of this file, or None if it is not a HEIF image.

    MP4 videos share the ftyp box, so the brand is what separates a HEIC photo
    from a video.
    """
    path = Path(path)
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
    except OSError:
        return None
    if len(header) < 12 or header[4:8] != b"ftyp":
        return None
    brand = header[8:12]
    return brand if brand in HEIF_BRANDS else None
