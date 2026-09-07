"""Build synthetic media files for tests.

Real videos cannot live in the repository, and generating them would mean
depending on ffmpeg, which this project deliberately avoids. The MP4 container
is simple enough to write by hand, and doing so makes the tests explicit about
exactly which bytes carry the metadata being read back.
"""

import struct
from datetime import datetime, timezone
from pathlib import Path

# MP4 timestamps count seconds from 1904-01-01 UTC, not the Unix epoch.
EPOCH_1904 = datetime(1904, 1, 1, tzinfo=timezone.utc)


def _box(kind: bytes, payload: bytes) -> bytes:
    """An ISO-BMFF box: a big-endian length covering the whole box, then a
    four-character kind, then the payload."""
    return struct.pack(">I", len(payload) + 8) + kind + payload


def _mvhd(when: datetime) -> bytes:
    """The movie header, which carries the creation time."""
    seconds = int((when.replace(tzinfo=timezone.utc) - EPOCH_1904).total_seconds())
    payload = struct.pack(">I", 0)  # version 0 + flags
    payload += struct.pack(">II", seconds, seconds)  # creation, modification
    payload += struct.pack(">II", 1000, 5000)  # timescale, duration
    payload += struct.pack(">i", 0x00010000)  # rate 1.0
    payload += struct.pack(">h", 0x0100)  # volume 1.0
    payload += b"\x00" * 10  # reserved
    payload += b"\x00" * 36  # matrix
    payload += b"\x00" * 24  # predefined
    payload += struct.pack(">I", 2)  # next track id
    return _box(b"mvhd", payload)


def _xyz(latitude: float, longitude: float) -> bytes:
    """The ©xyz box: an ISO 6709 string such as +40.7128-074.0060/.

    Two bytes of text length and two of language code precede the string.
    """
    text = f"{latitude:+08.4f}{longitude:+09.4f}/".encode()
    return _box(b"\xa9xyz", struct.pack(">HH", len(text), 0x15) + text)


def write_mp4(path, when: datetime | None = None, gps=None) -> Path:
    """A minimal but genuinely parseable MP4.

    ``when`` writes a creation time, ``gps`` a (latitude, longitude) pair.
    Omit either to build a file that lacks it.
    """
    path = Path(path)
    moov = _mvhd(when) if when is not None else b""
    if gps is not None:
        moov += _box(b"udta", _xyz(*gps))
    data = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2mp41")
    data += _box(b"moov", moov)
    path.write_bytes(data)
    return path
