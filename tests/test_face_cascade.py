"""The bundled Haar cascade must load.

count_faces returns 0 for any exception, so a cascade that cannot be loaded
would read as "no faces" on every photo, and no other test would notice:
blank frames contain no faces either way. Loading the cascade directly is the
check that fails when OpenCV drops it.
"""

from tagorganizer.plugins.builtin import detect_faces


def test_the_bundled_cascade_loads():
    assert not detect_faces._detector().empty()
