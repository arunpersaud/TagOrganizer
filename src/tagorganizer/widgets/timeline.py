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

from dateutil.relativedelta import relativedelta
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates
import numpy as np

from ..models import Item


class Timeline(FigureCanvas):
    def __init__(self, parent=None):
        fig = Figure(figsize=(10, 1))
        self.ax = fig.add_subplot(111)
        super().__init__(fig)
        self.setParent(parent)
        self.ax.xaxis_date()
        self.dates = []

        self.figure.patch.set_facecolor("none")
        self.ax.set_facecolor("none")

        self.mpl_connect("button_press_event", self.on_click)

        self.setMinimumHeight(100)
        self.setStyleSheet("background-color: transparent;")

    def plot_histogram(self, items: list[Item]):
        self.ax.clear()
        self.ax.xaxis_date()
        self.dates = [i.date for i in items if i.date is not None]
        self.dates_plt = np.array([mdates.date2num(d) for d in self.dates])

        start = min(self.dates)
        end = max(self.dates)
        delta = relativedelta(end, start)
        if delta.days <= 30:
            self.ax.xaxis.set_major_locator(mdates.DayLocator())
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            bins = delta.days
        elif delta.days <= 365:
            self.ax.xaxis.set_major_locator(mdates.WeekLocator())
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            bins = delta.days
        elif delta <= 365 * 5:
            self.ax.xaxis.set_major_locator(mdates.MonthLocator())
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            bins = delta.months
        else:
            self.ax.xaxis.set_major_locator(mdates.YearLocator())
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
            bins = delta.years

        if not bins:
            bins = 1

        self.ax.hist(self.dates_plt, bins=bins)

        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)
        self.ax.spines["left"].set_visible(False)
        self.ax.yaxis.set_ticks([])

        self.ax.set_xticks([self.dates_plt.min(), self.dates_plt.max()])
        self.ax.set_xticklabels([start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")])

        self.figure.tight_layout()
        self.draw()

    def on_click(self, event):
        # For future use if we want to downselect in time
        if event.inaxes == self.ax:
            clicked_date = mdates.num2date(event.xdata).date()
            print(f"Clicked on date: {clicked_date}")
