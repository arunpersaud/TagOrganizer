"""Choosing what a task acts on."""

from tagorganizer.scope import Scope, resolve_scope


class TestResolveScope:
    def test_an_empty_selection_means_the_whole_library(self):
        assert resolve_scope([]) == Scope.LIBRARY

    def test_a_selection_becomes_a_scope_over_those_items(self):
        assert list(resolve_scope([3, 1, 2]).item_ids) == [3, 1, 2]

    def test_the_library_scope_is_not_a_selection(self):
        assert Scope.LIBRARY.is_selection is False

    def test_a_selection_scope_says_so(self):
        assert resolve_scope([1]).is_selection is True

    def test_a_scope_cannot_be_changed_after_it_is_made(self):
        """The scope is decided when the task is queued.

        A task may run for minutes while the user carries on clicking, so a
        scope that could drift would act on photos the user never chose.
        """
        scope = resolve_scope([1, 2])
        try:
            scope.item_ids = (3,)
        except Exception:
            return
        raise AssertionError("the scope was mutable")


class TestDescribe:
    """The status message names the scope, so the single menu entry is
    never ambiguous about what it just acted on."""

    def test_the_library_describes_itself(self):
        assert Scope.LIBRARY.describe() == "the whole library"

    def test_a_selection_gives_its_size(self):
        assert resolve_scope([1, 2, 3]).describe() == "3 selected items"

    def test_one_item_is_singular(self):
        assert resolve_scope([1]).describe() == "1 selected item"

    def test_an_import_names_its_photos_as_imported(self):
        """After adding a folder nothing is selected; "selected" would mislead."""
        assert Scope((4, 5), kind="imported").describe() == "2 imported items"
