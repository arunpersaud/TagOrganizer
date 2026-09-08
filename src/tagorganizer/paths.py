"""Comparing paths the way the filesystem holding them does.

macOS and Windows treat /p/A.JPG and /p/a.jpg as one file; Linux treats them
as two, and both are right. Neither rule can be hardcoded: the same code runs
on all three, and a library can sit on a case-sensitive volume on a Mac or a
case-insensitive mount on Linux. So the answer comes from probing the
filesystem actually holding the files.

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
import tempfile
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


@lru_cache(maxsize=32)
def is_case_insensitive(directory) -> bool:
    """Whether this directory's filesystem ignores case in filenames.

    Probed rather than inferred from the platform, and cached: a move asks
    once per item, and probing the disk each time would mean thousands of file
    creations. The cache is keyed on the directory, so two libraries on
    differently-behaving volumes still get their own answer.

    A directory that cannot be probed is reported as case-sensitive. That is
    the safe direction: treating two paths as different can leave a duplicate
    record, while wrongly treating them as the same would silently drop a file
    that really was distinct.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return False

    try:
        with tempfile.NamedTemporaryFile(
            prefix="TagOrganizerCase", dir=directory
        ) as probe:
            name = Path(probe.name).name
            return (directory / name.upper()).exists() and (
                directory / name.lower()
            ).exists()
    except OSError:
        logger.debug("could not probe case sensitivity of %s", directory)
        return False


def same_path(first: str, second: str, reference) -> bool:
    """Whether two stored paths name the same file.

    ``reference`` is a directory on the filesystem the paths belong to; its
    behaviour decides whether case matters.
    """
    if first == second:
        return True
    if is_case_insensitive(reference):
        return first.lower() == second.lower()
    return False
