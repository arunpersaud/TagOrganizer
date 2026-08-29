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

from datetime import datetime, date

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates
from matplotlib.backend_bases import MouseButton
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

        self.setStyleSheet("background-color: transparent;")

        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)

    def plot_histogram(self, dates):
        self.ax.clear()
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

        self.ax.hist(self.dates_plt, bins=bins)

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

    def on_click(self, event):
        if event.inaxes == self.ax:
            clicked_date = mdates.num2date(event.xdata).date()
            if event.button == MouseButton.LEFT:
                self.main.tag_bar.add_time_tag(clicked_date, ">")
            elif event.button == MouseButton.RIGHT:
                self.main.tag_bar.add_time_tag(clicked_date, "<")
