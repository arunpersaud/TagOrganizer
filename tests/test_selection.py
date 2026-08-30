"""Tests for the Selection object.

Selection is deliberately Qt-free and stores ids rather than ORM objects, so it
is testable directly.
"""

from tagorganizer.selection import Selection


class TestSelectionBasics:
    def test_starts_empty(self):
        assert len(Selection()) == 0
        assert Selection().ids() == []

    def test_add_then_contains(self):
        s = Selection()
        s.add(7)
        assert 7 in s
        assert len(s) == 1

    def test_add_is_idempotent(self):
        s = Selection()
        s.add(7)
        s.add(7)
        assert len(s) == 1

    def test_preserves_insertion_order(self):
        s = Selection()
        for i in (5, 1, 9, 3):
            s.add(i)
        assert s.ids() == [5, 1, 9, 3]

    def test_readding_does_not_reorder(self):
        """A re-added id keeps its original position."""
        s = Selection()
        s.add_many([5, 1, 9])
        s.add(5)
        assert s.ids() == [5, 1, 9]

    def test_can_be_seeded(self):
        assert Selection([3, 1, 2]).ids() == [3, 1, 2]


class TestSelectionMutation:
    def test_discard_removes(self):
        s = Selection([1, 2, 3])
        s.discard(2)
        assert s.ids() == [1, 3]

    def test_discard_of_absent_id_is_quiet(self):
        s = Selection([1])
        s.discard(99)
        assert s.ids() == [1]

    def test_toggle_returns_new_state(self):
        s = Selection()
        assert s.toggle(4) is True
        assert 4 in s
        assert s.toggle(4) is False
        assert 4 not in s

    def test_add_many_extends(self):
        s = Selection([1])
        s.add_many([2, 3])
        assert s.ids() == [1, 2, 3]

    def test_clear_empties(self):
        s = Selection([1, 2])
        s.clear()
        assert len(s) == 0
        assert s.ids() == []

    def test_iterates_in_order(self):
        assert list(Selection([4, 2, 8])) == [4, 2, 8]
