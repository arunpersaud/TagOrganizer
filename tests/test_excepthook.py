"""The uncaught-exception hook.

PyQt6 aborts the process when an exception escapes a slot unless a
sys.excepthook is installed. These tests call the real hook factory; the
wiring in main() is checked by reading its source, as the other widget
wiring tests do.
"""

import ast
import sys
from pathlib import Path


MAIN = Path(__file__).parent.parent / "src" / "tagorganizer" / "main.py"


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
    def test_main_installs_the_hook(self):
        tree = ast.parse(MAIN.read_text())
        main = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        installs = [
            node
            for node in ast.walk(main)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Attribute)
                and t.attr == "excepthook"
                and isinstance(t.value, ast.Name)
                and t.value.id == "sys"
                for t in node.targets
            )
        ]
        assert installs, "main() must set sys.excepthook"
