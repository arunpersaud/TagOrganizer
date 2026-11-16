"""
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

from functools import wraps
import time

from qtpy.QtWidgets import QWidget, QGridLayout
from qtpy.QtCore import QTimer

from .framed_label import FramedLabel
from .helper import load_full_pixmap, get_thumbnail_loader
from .. import db


class ImageGridWidget(QWidget):
    def __init__(self, main):
        super().__init__()
        self.columns = 5
        self.rows = 5
        self.N = self.columns * self.rows
        self.highlight = 0
        self.page = 0

        self.main = main
        self.layout = QGridLayout()
        self.setLayout(self.layout)

        # we need to keep a reference to the widgets in the grid, otherwise
        # itemAtPosition will return a QLabel and not a FramedLabel
        self.widgets = []

        self.preloader = QTimer()
        self.preloader.timeout.connect(self.preload_items)
        self.preloader.start(100)
        # (page, highlight) the preloader last worked on, and whether that
        # pass finished rather than stopping on its time budget.
        self._last_preload_position = None
        self._preload_complete = False

    @staticmethod
    def _get_widget_index(highlight, N, widget_count):
        """Calculate the widget index for a given highlight position.

        Args:
            highlight: The global highlight position
            N: The page size (columns * rows)
            widget_count: The number of widgets currently displayed

        Returns:
            The index of the widget on the current page (0-based)
        """
        if widget_count == 0:
            return 0
        n = highlight % N
        return min(n, widget_count - 1)

    @staticmethod
    def clamp_highlight(position, count):
        """Keep a global highlight on a view that holds `count` items.

        An empty view has nothing to point at, so the frame stays at zero rather
        than moving to -1, which the cursor keys would otherwise do.
        """
        if count <= 0:
            return 0
        return max(0, min(position, count - 1))

    @staticmethod
    def highlight_for(page, N, index):
        """The global highlight position of tile `index` on `page`.

        The inverse of _get_widget_index, which recovers the tile from the
        global position with highlight % N.
        """
        return page * N + index

    @staticmethod
    def range_bounds(anchor, clicked):
        """The (start, count) span between two global positions, inclusive.

        Order-independent, so shift-clicking above the anchor selects the same
        span as shift-clicking below it.
        """
        start = min(anchor, clicked)
        return start, abs(clicked - anchor) + 1

    @staticmethod
    def change_highlight(func):
        @wraps(func)
        def wrapper(self, *args):
            if self.widgets:
                n = ImageGridWidget._get_widget_index(
                    self.highlight, self.N, len(self.widgets)
                )
                self.widgets[n].set_highlight(False)
            func(self, *args)
            if self.widgets:
                n = ImageGridWidget._get_widget_index(
                    self.highlight, self.N, len(self.widgets)
                )
                self.widgets[n].set_highlight(True)
            # update single item if in view
            if self.main.tabs.currentWidget() == self.main.single_item:
                self.main.show_current_item()

        return wrapper

    @change_highlight
    def show_images(self, items):
        row = 0
        col = 0

        self.clear()

        # One query for the whole page: the lineage dot needs an answer for
        # every visible tile, and asking per tile would be a round trip each.
        lineage = db.get_parent_summary([item.id for item in items])

        for item in items:
            label = FramedLabel(item, self.main.config.photos)
            label.set_parent_names(lineage.get(item.id, []))
            if item.id in self.main.selection:
                label.selected = True
            self.widgets.append(label)
            label.doubleClicked.connect(self.focus_widget)
            label.shiftClicked.connect(self.extend_selection_to)
            self.layout.addWidget(label, row, col)
            col += 1
            if col >= self.columns:
                col = 0
                row += 1

    def clear(self):
        # Take the items out of the layout as well as scheduling the widgets
        # for deletion. deleteLater only queues the delete, so a layout that
        # still holds the old items reports stale widgets at those positions
        # until the event loop gets a turn - and show_images adds the new row
        # of tiles before that happens.
        while (item := self.layout.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.widgets = []

    def clear_selection(self):
        # Walk the widgets we built rather than probing layout positions:
        # itemAtPosition can hand back something that is not a FramedLabel, and
        # reading .selected off it raises.
        for widget in self.widgets:
            if widget.selected:
                widget.toggle_selected()

    def current_item(self):
        if self.widgets:
            current = self._get_widget_index(self.highlight, self.N, len(self.widgets))
            return self.widgets[current]

    def toggle_selection(self):
        if self.widgets:
            widget = self.current_item()
            widget.toggle_selected()

            self.main.selection.toggle(widget.item.id)
            self.main.update_numbers(selected=len(self.main.selection))
            self.main.display_common_tags()

            return

    def extend_selection_to(self, widget):
        """Add every item between the anchor and this tile to the selection.

        The anchor is the current red frame. The span is fetched from the
        database rather than read off the screen, which is what lets a range
        cross pages - the items in between have never been rendered.
        """
        try:
            index = self.widgets.index(widget)
        except ValueError:
            return

        clicked = self.highlight_for(self.page, self.N, index)
        start, count = self.range_bounds(self.highlight, clicked)

        filters = self.main.tag_bar.get_filters()
        span = db.get_image_range(start, count, filters)
        self.main.selection.add_many(item.id for item in span)

        # The clicked tile becomes the next anchor, so successive shift-clicks
        # extend from where the user last acted.
        self._move_highlight_to(clicked)
        self.main.update_numbers(selected=len(self.main.selection))
        self.main.update_items()

    @change_highlight
    def _move_highlight_to(self, position):
        self.highlight = position

    def focus_widget(self, widget):
        """Move the red frame to a tile the user double-clicked.

        Routed through the decorated setter so the old frame is cleared and the
        single view follows along, exactly as the cursor keys do.
        """
        try:
            index = self.widgets.index(widget)
        except ValueError:
            return
        self._move_highlight_to(self.highlight_for(self.page, self.N, index))
        self.main.display_common_tags()

    @change_highlight
    def move_left(self):
        self.highlight = max(self.highlight - 1, 0)

    @change_highlight
    def move_right(self):
        N = self.main.numbers[0]

        self.highlight = ImageGridWidget.clamp_highlight(self.highlight + 1, N)

    @change_highlight
    def move_up(self):
        self.highlight = max(self.highlight - self.columns, 0)

    @change_highlight
    def shift_move_up(self):
        self.highlight = max(self.highlight - self.N, 0)

    @change_highlight
    def move_down(self):
        N = self.main.numbers[0]

        self.highlight = ImageGridWidget.clamp_highlight(
            self.highlight + self.columns, N
        )

    @change_highlight
    def shift_move_down(self):
        N = self.main.numbers[0]

        self.highlight = ImageGridWidget.clamp_highlight(self.highlight + self.N, N)

    def preload_items(self):
        # Skip if grid tab is not visible
        if self.main.tabs.currentWidget() != self:
            return

        filters = self.main.tag_bar.get_filters()

        # What a pass works on depends on the profile and the filters as well as
        # the page and the highlight. Leaving them out meant a pass that had
        # finished for one collection was skipped for another at the same
        # position, and that collection's neighbours never got warmed.
        position = (self.page, self.highlight, self.main.config.profile, filters)

        # Skip only when the previous pass for this position ran to
        # completion. A pass that stopped on the time budget still has work
        # left, so it has to be resumed on the next tick rather than skipped.
        if position == self._last_preload_position and self._preload_complete:
            return

        if position != self._last_preload_position:
            self._last_preload_position = position
            self._preload_complete = False

        start = time.time()
        budget = 0.01  # 10 ms budget (mostly DB queries now, decode is async)

        filters = self.main.tag_bar.get_filters()
        N = db.get_number_of_items(filters)
        loader = get_thumbnail_loader()

        # thumbnails +- 2 pages, handed to the pool rather than decoded here.
        # The worker writes the disk cache entry, so this is worth doing even
        # though nothing displays the result: the tile that eventually shows
        # this item finds the thumbnail already on disk. The loader drops
        # requests it is already working on, so re-offering the same pages on
        # every tick costs nothing.
        for i in range(self.page - 2, self.page + 3):
            if i < 0:
                continue
            if i > N // self.N:
                continue
            items = db.get_images(i, filters)
            for item in items:
                # Submit to thread pool but don't block waiting for result
                loader.load(item, 150, self.main.config.photos)
                if time.time() - start > budget:
                    return

        # full files +- 5 from current image. One ranged query, not eleven
        # single-row ones: each of those opens its own session and sorts the
        # whole table, which costs more than this method's entire budget.
        for item in db.get_image_range(self.highlight - 5, 11, filters):
            load_full_pixmap(str(item.uri))
            if time.time() - start > budget:
                return

        self._preload_complete = True
