"""Drag-and-drop rules for the tag tree, called on the real functions.

The tree is a hierarchy of ids; these tests build it as plain dicts, which is
the shape db.get_all_tags() is turned into before the rules see it.
"""

from tagorganizer.tag_moves import descendants, refuse_move

# France (1) -> Paris (2) -> Louvre (3); Animals (4) -> Cats (5); Lone (6)
TREE = {1: None, 2: 1, 3: 2, 4: None, 5: 4, 6: None}


class TestDescendants:
    def test_every_level_below_is_found(self):
        assert descendants(TREE, 1) == {2, 3}

    def test_a_leaf_has_none(self):
        assert descendants(TREE, 3) == set()

    def test_a_loop_in_stored_data_terminates(self):
        looped = {1: 2, 2: 1}
        assert descendants(looped, 1) == {1, 2}


class TestRefusals:
    def test_moving_under_a_sibling_branch_is_allowed(self):
        assert refuse_move([3], 4, False, TREE) is None

    def test_moving_to_the_top_level_is_allowed(self):
        assert refuse_move([2], None, False, TREE) is None

    def test_a_nested_tag_dropped_under_another_branch_is_allowed(self):
        """The case that re-parented the wrong tag before: Paris under Animals."""
        assert refuse_move([2], 4, False, TREE) is None

    def test_a_tag_cannot_go_under_itself(self):
        assert refuse_move([4], 4, False, TREE) is not None

    def test_a_tag_cannot_go_under_its_own_descendant(self):
        """Would make France its own ancestor and loop the filter."""
        assert refuse_move([1], 3, False, TREE) is not None

    def test_a_reserved_button_cannot_be_dragged(self):
        assert refuse_move([None], 4, False, TREE) is not None

    def test_a_reserved_button_cannot_be_a_parent(self):
        assert refuse_move([2], None, True, TREE) is not None

    def test_one_bad_tag_refuses_the_whole_multi_select(self):
        """Half a move would leave the user unsure what went where."""
        assert refuse_move([6, 1], 2, False, TREE) is not None

    def test_an_empty_drag_is_refused(self):
        assert refuse_move([], 4, False, TREE) is not None
