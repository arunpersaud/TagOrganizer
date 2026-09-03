"""Finding plugins on disk.

A plugin is Python the user chose to install, so there is no sandbox here.
Isolation means *error* isolation: a plugin that explodes on import, or is
malformed, is recorded with its traceback and reported, and the application
carries on without it. Silently missing plugins would be undiagnosable.

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

import importlib.util
import inspect
import logging
import traceback
from dataclasses import dataclass
from pathlib import Path

from . import Plugin, Registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrokenPlugin:
    """A plugin file that could not be loaded, and why."""

    path: Path
    error: str
    traceback: str


def plugin_paths() -> list[Path]:
    """Where plugins are looked for: shipped first, then the user's.

    Both go through platformdirs, so the user directory is the right one for
    the platform rather than a hardcoded path. The settings window shows this
    list, which is the only way to answer "where do I put my plugin?".
    """
    from ..config import config_dir

    shipped = Path(__file__).parent / "builtin"
    user = config_dir / "plugins"
    return [shipped, user]


def _load_module(path: Path):
    """Import one file as a throwaway module.

    Named after the file so two plugins cannot collide in sys.modules, and not
    inserted into sys.modules at all - a plugin is loaded once at startup and
    does not need to be importable by name.
    """
    spec = importlib.util.spec_from_file_location(
        f"tagorganizer_plugin_{path.stem}", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_plugins(directories) -> tuple[Registry, list[BrokenPlugin]]:
    """Load every plugin in these directories, in the order given."""
    registry = Registry()
    broken: list[BrokenPlugin] = []

    for directory in directories:
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                module = _load_module(path)
            except Exception as error:
                logger.exception("plugin %s failed to import", path)
                broken.append(BrokenPlugin(path, str(error), traceback.format_exc()))
                continue

            for _, obj in inspect.getmembers(module, inspect.isclass):
                if not issubclass(obj, Plugin) or obj is Plugin:
                    continue
                if obj.__module__ != module.__name__:
                    # Imported into the file rather than defined in it, so it
                    # belongs to whichever file did define it.
                    continue
                try:
                    registry.add(obj())
                except Exception as error:
                    logger.exception("plugin %s in %s is malformed", obj, path)
                    broken.append(
                        BrokenPlugin(path, str(error), traceback.format_exc())
                    )
    return registry, broken
