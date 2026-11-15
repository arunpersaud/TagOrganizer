"""The grid's position rules, called directly.

Clamping used to be inline in MainWindow.update_items. It is a plain function
now, so these tests call the real code.
"""

from tagorganizer.main import clamp_grid_position


class TestClampGridPosition:
    def test_a_frame_past_a_shrunken_result_moves_to_its_last_item(self):
        # Page 10 of 12 per page, with the frame on its first tile, then a
        # filter leaves 5 photos.
        assert clamp_grid_position(120, 5, 12) == (4, 0)

    def test_a_frame_that_still_fits_is_untouched(self):
        assert clamp_grid_position(14, 40, 12) == (14, 1)

    def test_an_empty_result_puts_everything_at_zero(self):
        assert clamp_grid_position(7, 0, 12) == (0, 0)

    def test_a_negative_frame_is_brought_back_on_screen(self):
        assert clamp_grid_position(-1, 10, 12) == (0, 0)
