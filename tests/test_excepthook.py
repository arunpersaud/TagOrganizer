"""The uncaught-exception hook.

PyQt6 aborts the process when an exception escapes a slot unless a
sys.excepthook is installed. These tests call the real hook factory, and run
the real main() to check that it installs one.
"""

import sys

import pytest


def _raise(error):
    try:
        raise error
    except Exception:
        return sys.exc_info()


class TestReporting:
    def test_the_reporter_receives_the_summary_and_traceback(self):
        from tagorganizer.main import make_excepthook

        seen = []
        hook = make_excepthook(lambda summary, details: seen.append((summary, details)))

        hook(*_raise(ValueError("tag has no parent")))

        summary, details = seen[0]
        assert summary == "ValueError: tag has no parent"
        assert "Traceback" in details
        assert "tag has no parent" in details

    def test_a_failing_reporter_does_not_raise(self):
        """Otherwise one abort becomes a second, quieter one."""
        from tagorganizer.main import make_excepthook

        def broken(summary, details):
            raise RuntimeError("no window left")

        hook = make_excepthook(broken)
        hook(*_raise(ValueError("original")))

    def test_keyboard_interrupt_keeps_the_default_handling(self, monkeypatch):
        from tagorganizer.main import make_excepthook

        calls = []
        monkeypatch.setattr(sys, "__excepthook__", lambda *args: calls.append(args[0]))
        seen = []
        hook = make_excepthook(lambda summary, details: seen.append(summary))

        # Built by hand: raising a KeyboardInterrupt inside a test ends pytest.
        hook(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert calls == [KeyboardInterrupt]
        assert seen == []


class TestWiring:
    def test_main_installs_a_hook_that_reports_to_the_window(
        self, monkeypatch, tmp_path
    ):
        """Runs the real main(), with the application and window replaced by
        recorders, and then calls the hook it installed. A main() that installs
        nothing leaves the default hook, which reports nowhere.
        """
        import tagorganizer.main as main_module

        config_file = tmp_path / "config.ini"
        config_file.write_text("[DEFAULT]\nprofile = default\n")
        windows = []

        class FakeWindow:
            def __init__(self, app, config_file=None, profile=None):
                self.reports = []
                windows.append(self)

            def report_unhandled(self, summary, details):
                self.reports.append(summary)

            def show(self):
                pass

        class FakeApp:
            def __init__(self, argv):
                pass

            def exec_(self):
                return 0

        monkeypatch.setattr(main_module, "MainWindow", FakeWindow)
        monkeypatch.setattr(main_module, "QApplication", FakeApp)
        monkeypatch.setattr(
            main_module, "configure_logging", lambda verbose=False: None
        )
        monkeypatch.setattr(sys, "argv", ["TagOrganizer", "--config", str(config_file)])
        monkeypatch.setattr(sys, "excepthook", sys.excepthook)

        with pytest.raises(SystemExit):
            main_module.main()

        sys.excepthook(*_raise(ValueError("boom")))
        assert windows[0].reports == ["ValueError: boom"]
