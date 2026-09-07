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

import re
from datetime import datetime

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
