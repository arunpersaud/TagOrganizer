"""Comparing paths the way the filesystem does.

macOS and Windows treat /p/A.JPG and /p/a.jpg as one file; Linux treats them
as two. Neither rule can be hardcoded: the same code runs on all three, and a
library can even sit on a case-sensitive volume on a Mac. So the behaviour
follows a probe of the filesystem actually holding the files.
"""

from tagorganizer.paths import same_path, is_case_insensitive


class TestTheProbeAgreesWithReality:
    """The probe cannot assert a fixed answer - it depends where tests run -
    but it must agree with what the filesystem actually does."""

    def test_it_matches_what_the_filesystem_does(self, tmp_path):
        (tmp_path / "Probe.txt").write_text("x")
        actually_insensitive = (tmp_path / "probe.txt").exists()

        assert is_case_insensitive(tmp_path) is actually_insensitive

    def test_a_missing_directory_is_assumed_case_sensitive(self, tmp_path):
        """The safe assumption: treating two paths as different never merges
        records that should have stayed apart."""
        assert is_case_insensitive(tmp_path / "nowhere") is False

    def test_the_answer_is_cached_per_directory(self, tmp_path):
        """The move asks once per item; probing the disk each time would mean
        thousands of file creations.

        Asserted on the cache actually being hit, not on the two answers
        agreeing - they would agree either way.
        """
        is_case_insensitive.cache_clear()
        is_case_insensitive(tmp_path)
        misses_after_first = is_case_insensitive.cache_info().misses

        is_case_insensitive(tmp_path)

        assert is_case_insensitive.cache_info().misses == misses_after_first
        assert is_case_insensitive.cache_info().hits >= 1

    def test_two_directories_get_their_own_answer(self, tmp_path):
        """Two libraries can sit on volumes that behave differently."""
        first = tmp_path / "one"
        second = tmp_path / "two"
        first.mkdir()
        second.mkdir()
        is_case_insensitive.cache_clear()

        is_case_insensitive(first)
        is_case_insensitive(second)

        assert is_case_insensitive.cache_info().misses == 2


class TestSamePath:
    def test_identical_paths_match_everywhere(self, tmp_path):
        assert same_path("/p/a.jpg", "/p/a.jpg", tmp_path) is True

    def test_different_paths_never_match(self, tmp_path):
        assert same_path("/p/a.jpg", "/p/b.jpg", tmp_path) is False

    def test_case_differences_follow_the_filesystem(self, tmp_path):
        (tmp_path / "Probe.txt").write_text("x")
        insensitive = (tmp_path / "probe.txt").exists()

        assert same_path("/p/A.JPG", "/p/a.jpg", tmp_path) is insensitive


class TestForcedBehaviour:
    """Both branches must be exercised wherever the tests happen to run."""

    def test_folding_when_the_filesystem_ignores_case(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tagorganizer.paths.is_case_insensitive", lambda path: True)
        assert same_path("/p/A.JPG", "/p/a.jpg", tmp_path) is True

    def test_not_folding_when_the_filesystem_respects_case(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tagorganizer.paths.is_case_insensitive", lambda path: False
        )
        assert same_path("/p/A.JPG", "/p/a.jpg", tmp_path) is False
