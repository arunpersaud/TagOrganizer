"""Tag the photos that contain faces.

This finds *that* a face is present, not *whose* it is. A Haar cascade knows
what a face looks like in general; telling one person from another needs an
embedding per face and a set of labelled examples to compare against, which is
a different piece of work. Tagging photos that contain people still makes them
findable, which is most of the value.

Uses the cascades bundled with OpenCV, which is already a dependency, so this
needs nothing installed.

Copyright 2024 Arun Persaud.

This file is part of TagOrganizer, distributed under the GNU General Public
License v3 or later. See the LICENSE file for details.
"""

import logging
from functools import lru_cache
from pathlib import Path

import cv2

from tagorganizer import config
from tagorganizer.plugins import Plugin

logger = logging.getLogger(__name__)

# Detection runs on a downscaled copy. A cascade slides a window over the whole
# image, so cost grows with area: a 40 megapixel photo takes seconds and finds
# nothing a 900 pixel wide copy would miss.
MAX_WIDTH = 900

# Tuned to prefer missing a face over inventing one. A false positive tags a
# photo that has no one in it, and the user has no way to tell which tags were
# guessed - the same reasoning as the filename dates.
#
# No test pins these values: demonstrating a false positive needs real
# photographs, which cannot live in the repository, and neither blank frames
# nor random noise fire the cascade at any setting. Lowering MIN_NEIGHBOURS
# will not turn any test red, so treat it as a deliberate choice rather than
# an arbitrary one.
SCALE_FACTOR = 1.1
MIN_NEIGHBOURS = 6


@lru_cache(maxsize=1)
def _detector():
    """The cascade, loaded once - it is about a megabyte of XML."""
    path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    return cv2.CascadeClassifier(str(path))


def count_faces(path) -> int:
    """How many faces are visible in this image.

    Returns 0 for anything that cannot be read: a task running over a whole
    library must not stop because one file is a text file with a .jpg name.
    """
    path = Path(path)
    if not path.is_file():
        return 0

    try:
        image = cv2.imread(str(path))
        if image is None:
            return 0

        height, width = image.shape[:2]
        if width > MAX_WIDTH:
            scale = MAX_WIDTH / width
            image = cv2.resize(image, (MAX_WIDTH, int(height * scale)))

        grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Equalising first makes detection far less sensitive to exposure,
        # which matters for a library shot across many lighting conditions.
        grey = cv2.equalizeHist(grey)

        faces = _detector().detectMultiScale(
            grey, scaleFactor=SCALE_FACTOR, minNeighbors=MIN_NEIGHBOURS
        )
    except Exception:
        logger.debug("could not look for faces in %s", path, exc_info=True)
        return 0

    return len(faces)


class DetectFaces(Plugin):
    name = "Detect Faces and Tag"
    description = "Tag photos that contain a face. Slow; aim it at a selection."
    category = "Tags"
    # Detection is slow, so being able to aim it at a selection matters.
    accepts_selection = True
    # Never automatic: it would make every import take minutes.
    auto = False

    #: Change this in your own copy of the plugin to tag something else.
    TAG = "People"

    def run(self, ctx):
        photos = [
            item
            for item in ctx.items()
            if Path(item.uri).suffix.lower() in config.PHOTO_SUFFIX
        ]
        total = len(photos)
        done = 0
        tagged = 0
        found = 0

        for item in photos:
            if ctx.cancelled:
                break
            faces = count_faces(item.uri)
            if faces:
                ctx.add_tag(item, self.TAG)
                tagged += 1
                found += faces
            done += 1
            if done % 10 == 0:
                yield total, done

        ctx.message(f"photos examined: {total}")
        ctx.message(f"tagged {tagged} of them, {found} faces in total")
        yield total, done
