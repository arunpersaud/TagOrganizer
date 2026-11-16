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

from datetime import datetime, date, timedelta

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates
from matplotlib.backend_bases import MouseButton
from matplotlib.widgets import SpanSelector
import numpy as np

from qtpy.QtWidgets import QSizePolicy


def get_histogram_locator_and_bins(start, end):
    """
    Determine the appropriate matplotlib date locator and bin count for a date range.

    Args:
        start: Start date (datetime or date object)
        end: End date (datetime or date object)

    Returns:
        tuple: (locator_class, bin_count)
    """
    # Convert date objects to datetime if needed
    if isinstance(start, date) and not isinstance(start, datetime):
        start = datetime.combine(start, datetime.min.time())
    if isinstance(end, date) and not isinstance(end, datetime):
        end = datetime.combine(end, datetime.min.time())

    # Calculate total span in days
    total_days = (end - start).days

    if total_days <= 0:
        total_days = 1

    # Choose locator and bins based on span
    if total_days <= 30:
        locator = mdates.DayLocator()
        bins = max(1, total_days)
    elif total_days <= 365 * 5:
        locator = mdates.MonthLocator()
        bins = max(1, total_days // 30)
    else:
        locator = mdates.YearLocator()
        bins = max(1, total_days // 365)

    # Cap bins to avoid absurdly large values
    bins = min(bins, 365)

    return locator, bins


class Timeline(FigureCanvas):
    def __init__(self, main):
        self.figure = Figure(figsize=(10, 1))
        self.ax = self.figure.add_subplot(111)

        super().__init__(self.figure)

        self.main = main

        self.ax.xaxis_date()

        self.figure.patch.set_facecolor("none")
        self.ax.set_facecolor("none")

        self.mpl_connect("button_press_event", self.on_click)

        # Dragging across the timeline is the primary way to pick a date range.
        # Restricted to the left button so right-click stays free for clearing,
        # and useblit is off because this canvas is redrawn wholesale on every
        # filter change, which invalidates a blit cache.
        self.span_selector = SpanSelector(
            self.ax,
            self.on_span_select,
            direction="horizontal",
            useblit=False,
            button=MouseButton.LEFT,
            props={"alpha": 0.3, "facecolor": "tab:blue"},
            interactive=True,
            drag_from_anywhere=True,
        )

        self.setStyleSheet("background-color: transparent;")

        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)

    def plot_histogram(self, dates):
        self.ax.clear()
        # ax.clear() takes the selector's artists with it, so its selection state
        # has to be dropped too rather than left pointing at a rectangle that is
        # no longer drawn.
        self.span_selector.clear()
        self.ax.xaxis_date()
        self.dates_plt = np.array([mdates.date2num(d) for d in dates])

        start = dates[-1] if dates else datetime(2000, 1, 1)
        end = dates[0] if dates else datetime.now()

        # Get locator and bins based on date range
        locator, bins = get_histogram_locator_and_bins(start, end)
        self.ax.xaxis.set_major_locator(locator)

        # Set formatter based on span
        total_days = (end - start).days if dates else 0
        if total_days <= 365:
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        elif total_days <= 365 * 5:
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        else:
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

        # Log scale on the counts: a month holding a couple of thousand photos
        # otherwise flattens every quieter month to an invisible sliver, which
        # makes the timeline useless for finding the sparse parts of a library.
        self.ax.hist(self.dates_plt, bins=bins, log=True)

        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)
        self.ax.spines["left"].set_visible(False)
        self.ax.yaxis.set_ticks([])

        if len(self.dates_plt):
            self.ax.set_xticks([self.dates_plt.min(), self.dates_plt.max()])
            self.ax.set_xticklabels(
                [start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")]
            )

        self.figure.tight_layout()
        self.draw()

    def on_span_select(self, xmin, xmax):
        """Apply a dragged span as a date range.

        Both bounds go over in one call so the view is redrawn once. The tag bar
        orders them, so dragging right-to-left means the same span.

        A click without a drag arrives as a span of no width. That is not a range
        the user asked for, and applying it would empty the view, so it is
        ignored.

        The span includes its last day. The tag bar's upper bound reads as
        "before", so the day after the span is what it needs; passing the span's
        own final date would stop at midnight and drop everything taken that day.
        """
        if xmax <= xmin:
            return
        start = mdates.num2date(xmin).date()
        end = mdates.num2date(xmax).date() + timedelta(days=1)
        self.main.tag_bar.set_time_range(start, end)

    def on_click(self, event):
        """Right-click clears the time filter.

        Left-click no longer sets a bound on its own: dragging replaced that, and
        leaving both gestures on the same button meant a slightly-moved click
        silently applied a filter the user never asked for.
        """
        if event.inaxes != self.ax:
            return
        if event.button == MouseButton.RIGHT:
            self.main.tag_bar.clear_time_range()
