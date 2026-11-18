"""Count the faces in photos, for the Unnamed faces filter.

The task records how many faces each photo has and tags nothing. The filter
then shows photos with a face and no tag under People, so naming someone takes
a photo off the list by itself; a "People" tag added here would only go stale.

This finds *that* a face is present, not *whose* it is. A detector knows what a
face looks like in general; telling one person from another needs an embedding
per face and a set of labelled examples to compare against, which is a
different piece of work. Knowing which photos have a face still turns naming
people into a list to work through, which is most of the value.

Detection uses YuNet, a small neural network run through OpenCV's
cv2.FaceDetectorYN. The model is shipped in the package under data/, with its
source and license in data/YUNET-NOTICE.md, so nothing is downloaded at run
time. It replaces the Haar cascade this module used before: OpenCV 5 removed
the cascade files and the cv2.CascadeClassifier path to them, while
FaceDetectorYN is present in both the 4.x and 5.x releases.

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

MODEL_PATH = Path(__file__).parents[2] / "data" / "face_detection_yunet_2026may.onnx"

# Detection runs on a downscaled copy. Cost grows with pixel count, and a
# 40 megapixel photo takes seconds per file. YuNet's README says it finds faces
# of roughly 10 to 300 pixels, which a 900 pixel wide frame keeps for most
# photos.
MAX_WIDTH = 900

# A YuNet score is the network's confidence in a box, from 0 to 1. A false
# positive tags a photo that has no one in it, and the user has no way to tell
# which tags were guessed, the same reasoning as the filename dates, so the bar
# is kept high. YuNet's own demo uses 0.9; 0.8 keeps faces the network is fairly
# sure of, such as the one in the test photo (about 0.92), and drops weaker
# guesses. This is a judgment, not a measured optimum.
SCORE_THRESHOLD = 0.8
# Overlapping boxes above this intersection-over-union collapse into one face.
NMS_THRESHOLD = 0.3
# The most candidate boxes the network may propose before suppression.
TOP_K = 5000


@lru_cache(maxsize=1)
def _detector():
    """The detector, built once. The model is about 230 KB, and reading it on
    every photo would cost more than the detection itself.

    A missing or corrupt model raises here, and that is deliberately not caught
    by count_faces: caught there, every photo in a library would read as
    "no faces" and the task would report success.
    """
    return _build_detector(MODEL_PATH)


def _build_detector(model_path):
    # The input size given here is only a placeholder: YuNet's anchor layout
    # depends on the image size, so count_faces sets the real size per image.
    return cv2.FaceDetectorYN.create(
        str(model_path),
        "",
        (MAX_WIDTH, MAX_WIDTH),
        SCORE_THRESHOLD,
        NMS_THRESHOLD,
        TOP_K,
    )


def count_faces(path) -> int | None:
    """How many faces are visible in this image, or None if it can't be read.

    None rather than 0, because 0 is stored as "checked, no faces" and takes
    the photo off the Unnamed faces list; a file on an unplugged drive has not
    been checked. Nothing is raised either: a task running over a whole library
    must not stop because one file is a text file with a .jpg name. A detector
    that cannot be built is not "unreadable", and raises.
    """
    path = Path(path)
    if not path.is_file():
        return None

    detector = _detector()

    try:
        image = cv2.imread(str(path))
        if image is None:
            return None

        height, width = image.shape[:2]
        if width > MAX_WIDTH:
            scale = MAX_WIDTH / width
            height, width = int(height * scale), MAX_WIDTH
            image = cv2.resize(image, (width, height))

        # One worker thread runs every task, so the shared detector is never
        # used from two threads at once; setInputSize changes its state.
        detector.setInputSize((width, height))
        _, faces = detector.detect(image)
    except Exception:
        logger.debug("could not look for faces in %s", path, exc_info=True)
        return None

    return 0 if faces is None else len(faces)


class DetectFaces(Plugin):
    name = "Detect Faces"
    description = (
        "Count the faces in photos, for the Unnamed faces filter. "
        "Slow; aim it at a selection."
    )
    category = "Tags"
    # Detection is slow, so being able to aim it at a selection matters.
    accepts_selection = True
    # Never automatic: it would make every import take minutes.
    auto = False

    def run(self, ctx):
        photos = [
            item
            for item in ctx.items()
            if Path(item.uri).suffix.lower() in config.PHOTO_SUFFIX
        ]
        total = len(photos)
        done = 0
        with_faces = 0
        found = 0
        unreadable = 0
        # Saved in batches, and before stopping: a long run that is cancelled
        # keeps what it has already found.
        unsaved = []

        for item in photos:
            if ctx.cancelled:
                break
            faces = count_faces(item.uri)
            if faces is None:
                # Left as it was: an earlier count is still the best answer,
                # and an unchecked photo stays unchecked.
                unreadable += 1
            else:
                item.face_count = faces
                unsaved.append(item)
                if faces:
                    with_faces += 1
                    found += faces
            done += 1
            if done % 10 == 0:
                ctx.save_face_counts(unsaved)
                unsaved = []
                yield total, done

        ctx.save_face_counts(unsaved)
        ctx.message(f"photos examined: {total}")
        ctx.message(f"faces in {with_faces} of them, {found} faces in total")
        if unreadable:
            ctx.message(f"could not read {unreadable} of them")
        yield total, done
