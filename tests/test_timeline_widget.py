"""Behavioural tests for the timeline widget.

Timeline is a matplotlib FigureCanvas, so it needs a QApplication; guarded the
same way as the other Qt-touching test modules. The pure histogram-binning
helpers are tested separately in tests/test_widgets.py without Qt.
"""

import os
from datetime import date, datetime, timedelta


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _RecordingTagBar:
    def __init__(self):
        self.ranges = []
        self.clears = 0

    def set_time_range(self, start, end):
        self.ranges.append((start, end))

    def clear_time_range(self):
        self.clears += 1


class _DummyMain:
    """Timeline only stores `main`; it does not call into it while plotting."""

    def __init__(self):
        self.tag_bar = _RecordingTagBar()


def _timeline():
    from tagorganizer.widgets.timeline import Timeline

    return Timeline(_DummyMain())


class _FakeEvent:
    """Enough of a matplotlib mouse event for on_click."""

    def __init__(self, ax, button, xdata=None):
        self.inaxes = ax
        self.button = button
        self.xdata = xdata


class TestLogScale:
    def test_histogram_uses_a_log_y_axis(self, qapp):
        """One busy month must not flatten every quiet month to invisibility.

        On a linear axis a month holding 2000 photos leaves a month holding 20
        indistinguishable from empty, which makes the timeline useless for
        finding the sparse parts of a library.
        """
        timeline = _timeline()
        base = datetime(2024, 1, 1)
        dates = [base + timedelta(days=i) for i in range(40)]
        timeline.plot_histogram(dates)

        assert timeline.ax.get_yscale() == "log"

    def test_the_span_does_not_depend_on_the_order_of_the_dates(
        self, qapp, monkeypatch
    ):
        """The Duplicates filter orders copies together, not strictly by date."""
        from tagorganizer.widgets import timeline as timeline_module

        spans = []
        real = timeline_module.get_histogram_locator_and_bins

        def recording(start, end):
            spans.append((start, end))
            return real(start, end)

        monkeypatch.setattr(
            timeline_module, "get_histogram_locator_and_bins", recording
        )
        timeline = _timeline()
        early, middle, late = (
            datetime(2019, 1, 1),
            datetime(2021, 1, 1),
            datetime(2025, 1, 1),
        )

        timeline.plot_histogram([middle, early, late])

        assert spans == [(early, late)]

    def test_empty_history_does_not_raise(self, qapp):
        """A profile with no dated photos still has to draw something."""
        timeline = _timeline()
        timeline.plot_histogram([])

    def test_an_empty_library_does_not_bin_or_log_scale_anything(self, qapp):
        """No dated photos means no histogram.

        Log-scaling an empty histogram is what makes matplotlib warn that the data
        has no positive values, so the bars are not drawn at all in that case.
        """
        timeline = _timeline()
        calls = []
        timeline.ax.hist = lambda *args, **kwargs: calls.append((args, kwargs))

        timeline.plot_histogram([])

        assert calls == []

    def test_sparse_and_busy_bins_both_survive_binning(self, qapp):
        """Binning must not merge a rare month into its busy neighbour.

        Note this guards the binning, not the log axis: patch heights are the
        raw counts either way, so this assertion passes on a linear scale too.
        The scale itself is covered by test_histogram_uses_a_log_y_axis.
        """
        timeline = _timeline()
        base = datetime(2024, 1, 1)
        busy = [base + timedelta(days=1)] * 2000
        sparse = [base + timedelta(days=300)] * 3
        timeline.plot_histogram(sorted(busy + sparse, reverse=True))

        heights = [p.get_height() for p in timeline.ax.patches]
        assert max(heights) == 2000
        assert 3 in heights


class TestDragToSelect:
    def test_a_span_selector_is_installed(self, qapp):
        """Dragging is the primary gesture, so the selector must exist."""
        timeline = _timeline()
        assert timeline.span_selector is not None

    def test_dragging_sets_both_bounds_in_one_call(self, qapp):
        """One gesture, one filter change, one redraw.

        The range is handed to the tag bar as a pair rather than as two separate
        bounds, so the view is refreshed once rather than twice.
        """
        import matplotlib.dates as mdates

        timeline = _timeline()
        lo = mdates.date2num(datetime(2024, 1, 1))
        hi = mdates.date2num(datetime(2024, 6, 30, 12))

        timeline.on_span_select(lo, hi)

        assert len(timeline.main.tag_bar.ranges) == 1
        start, end = timeline.main.tag_bar.ranges[0]
        assert start == date(2024, 1, 1)
        # The tag bar's upper bound is "before", so the span's last day is
        # included by passing the day after it.
        assert end == date(2024, 7, 1)

    def test_the_last_day_of_the_span_is_included(self, qapp):
        """A span ending on 30 June must still show photos taken on 30 June.

        Ending at midnight of the 30th, as the drag used to, dropped every photo
        taken during that day.
        """
        import matplotlib.dates as mdates

        timeline = _timeline()
        hi = mdates.date2num(datetime(2024, 6, 30, 23, 59))

        timeline.on_span_select(mdates.date2num(datetime(2024, 6, 1)), hi)

        _, end = timeline.main.tag_bar.ranges[0]
        assert end > date(2024, 6, 30)

    def test_a_zero_width_click_selects_nothing(self, qapp):
        """A click without a drag arrives as a span of no width.

        Applying it would filter the view down to nothing, which the user never
        asked for.
        """
        import matplotlib.dates as mdates

        timeline = _timeline()
        at = mdates.date2num(datetime(2024, 3, 3))

        timeline.on_span_select(at, at)

        assert timeline.main.tag_bar.ranges == []

    def test_a_redraw_clears_the_span_selector(self, qapp):
        """Redrawing removes the artists the selector drew with.

        Its selection state has to go with them, or it keeps a range the plot no
        longer shows.
        """
        timeline = _timeline()
        timeline.plot_histogram([datetime(2024, 1, 1), datetime(2024, 2, 1)])
        timeline.span_selector.set_visible(True)

        timeline.plot_histogram([datetime(2024, 1, 1), datetime(2024, 2, 1)])

        assert not timeline.span_selector.get_visible()

    def test_right_click_clears_the_range(self, qapp):
        from matplotlib.backend_bases import MouseButton

        timeline = _timeline()
        timeline.on_click(_FakeEvent(timeline.ax, MouseButton.RIGHT, xdata=0.0))

        assert timeline.main.tag_bar.clears == 1

    def test_left_click_no_longer_sets_a_bound_on_its_own(self, qapp):
        """Dragging replaced click-to-set; a stray click must not filter."""
        from matplotlib.backend_bases import MouseButton

        timeline = _timeline()
        timeline.on_click(_FakeEvent(timeline.ax, MouseButton.LEFT, xdata=0.0))

        assert timeline.main.tag_bar.ranges == []
        assert timeline.main.tag_bar.clears == 0

    def test_clicks_outside_the_axes_are_ignored(self, qapp):
        from matplotlib.backend_bases import MouseButton

        timeline = _timeline()
        timeline.on_click(_FakeEvent(None, MouseButton.RIGHT, xdata=0.0))

        assert timeline.main.tag_bar.clears == 0
