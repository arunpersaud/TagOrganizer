# Repository Guidelines

## Project Overview
TagOrganizer is a desktop application for organizing photos and videos, written in Python with PyQt6 (accessed through `qtpy`). It lets you tag media with hierarchical tags and filter by tag, date, geolocation, an explicit selection, or a drawn area on a map. Metadata lives in a SQLite database managed with `SQLModel`, with schema changes tracked by `Alembic`. Each profile has its own database, so one installation can hold several independent collections.

## Project Structure & Module Organization
All runtime code resides in `src/tagorganizer`. `main.py` wires the Qt application and holds `MainWindow`; supporting modules handle configuration (`config.py`), persistence (`db.py`, `models.py`), background maintenance tasks (`tasks.py`), the current selection (`selection.py`), map clustering and lasso geometry (`map_cluster.py`), and moving items between profile databases (`dbmove.py`). Reusable UI components live in `src/tagorganizer/widgets/`. Database migrations are tracked in `src/tagorganizer/migrations/`, and built artifacts produced by packaging flows land in `dist/`. Place new automated checks under `tests/`; mirror the package layout so future contributors can discover coverage quickly.

## Build, Test, and Development Commands
Use `uv sync` to install locked dependencies from `uv.lock`. Launch the desktop client with `uv run TagOrganizer` (add `--help` to inspect CLI switches such as `--import-from-f-spot`). To start against a particular configuration and profile:

```bash
uv run TagOrganizer --config <path_to_config_file> --profile <profile_name>
```

The entry point is the `main` function in `src/tagorganizer/main.py`. Run the full test suite with `uv run python -m pytest`. Execute formatting and linting before committing via `uv run pre-commit run --all-files`; run `pre-commit install` once per clone. When debugging migrations, `uv run alembic upgrade head` keeps local databases aligned.

## Coding Style & Naming Conventions
Target Python 3.13 and keep imports sorted logically. Follow 4-space indentation, snake_case for modules, functions, and variables, and PascalCase for Qt widget subclasses and ORM models. Type hints are encouraged for new modules, especially around database and task utilities. Ruff enforces both linting and formatting; the pre-commit configuration already runs `ruff --fix` and `ruff format`.

Comments explain *why*, in prose, above the code they describe. Several decisions in this codebase look wrong until you know the reason — the map script is injected at `</html>` rather than `</body>`, `FramedLabel.mousePressEvent` deliberately does not call `super()`, and the cross-database move deletes by id and never by uri. Those comments are load-bearing; do not strip them. A comment that merely restates the code is a defect.

## Testing Guidelines
Pytest is the framework. Add tests in files named `test_<feature>.py`, using fixtures to isolate database state and temporary media directories. Target subsets with `-k` (e.g. `uv run python -m pytest -k timeline`). When modifying migrations or data tasks, include regression tests that cover migration scripts against a temporary SQLite database.

Two conventions matter more than they look:

**Keep Qt out of the suite where you can.** Logic is extracted into Qt-free functions and tested directly; that remains the first choice. When a widget or the real window must be exercised, use the single session-scoped `qapp` fixture in `tests/conftest.py` (offscreen platform) — never construct another `QApplication`. Prefer behavioural assertions over `ast` or source-string checks: a string check passes with the string in a comment, and an `ast` check passes on wiring that binds the wrong object.

**A test must be able to fail.** Before trusting a new test, break the code it covers and confirm it goes red. This repository has repeatedly produced tests that passed against unfixed code — a wrong widget hierarchy, a square source image whose scaled size matched the cached size, a config object built by hand instead of through `__init__`, a test that exercised a local copy of the function under test rather than the real one, a rollback test that stayed green with the rollback deleted because the connection pool rolls back on garbage collection, and a `stop()` test that never called `stop()`. Never test a reimplementation of production logic; call the real function and inject failures from outside it.

Anything that crosses into JavaScript or a live web view cannot be exercised here. State that gap plainly rather than writing a test that appears to cover it.

## Commit & Pull Request Guidelines
Recent history favors concise, descriptive commit subjects such as `Fix cursor behavior for last page`. Write imperative, <72-character summaries followed by focused bodies when context is needed. For pull requests, provide a problem statement, implementation notes, and manual test results. UI-facing changes should include before/after screenshots or short clips, and all PRs must link the relevant issue tracker entry when available.

## Environment & Configuration Tips
The application stores per-profile databases and INI files in user-specific paths managed by `platformdirs`. Thumbnails are cached beside the photos, under `<photo_dir>/thumbnails/<size>/`, so they inherit whatever protection the originals have. Document any new settings in `config.py` docstrings and note required migrations. `db.engine` is a module-level global belonging to the currently loaded profile; code that touches another profile's database must use its own engine and leave that global alone.

## Plugins and tasks

Every task the app performs is a plugin. `src/tagorganizer/plugins/__init__.py`
defines the `Plugin` base class and the `Registry`; `discovery.py` loads plugins
from the shipped `builtin/` directory and from `<config_dir>/plugins/*.py`;
`context.py` defines `TaskContext`, which is the entire public API.

- **Plugins never import `db`.** Everything goes through `TaskContext`. If a
  plugin needs something the context lacks, add it to the context rather than
  reaching past it.
- **Shipped plugins use absolute imports** (`from tagorganizer.plugins import
  Plugin`), because discovery loads every plugin as a standalone module with no
  parent package. A relative import fails at load time.
- **The Tasks menus are generated** from `Registry.by_category()`. Do not add a
  task to the static `menu` dict in `main.py`.
- **Scope**: a plugin with `accepts_selection = True` runs on the current
  selection when there is one and the whole library otherwise; the status
  message names which. `accepts_selection = False` always gets the library.
- **`auto = True`** also runs the plugin after an import. Registry order
  matters: hashing must precede video previews, because a preview is cached
  under the item's md5.

Task work runs on one dedicated worker thread (`TaskRunner` in `tasks.py`), not
on the GUI thread. Progress and messages come back as signals. This is why
`db.set_engine` passes `check_same_thread=False` — safe only because there is
exactly one worker.

## Things that have bitten us

- **Menu and wiring breakage used to be invisible to the suite.** Smoke-testing
  the real window in a scratch script caught a startup crash and an unwired map
  pipeline; `tests/test_main_window.py` now builds real windows (see below).
- **`ConfigManager` opens the real library** unless you pass `config_file=`.
  Never build one in a scratch script without it.

## Later additions

- **`metadata.py`** holds the pure readers: `date_from_filename`, `video_date`
  (hachoir), `video_gps` (our own ISO-BMFF box walk — hachoir surfaces no GPS),
  and `heif_brand`. hachoir must be silenced with `cfg.quiet = True` *before*
  its parsers are imported.
- **`scope.py`** decides what a task acts on. A plugin with
  `accepts_selection = True` gets the selection when there is one.
- **`paths.py`** compares paths the way the filesystem does, probed and cached.
  Never infer case sensitivity from `sys.platform`.
- **Schema changes are Alembic migrations**, applied at startup. A migration
  that adds a constraint must clean up first, in the same transaction — an
  aborted upgrade means the app will not open at all. See
  `a1f4c7b23d05`, which merges duplicates before adding uniqueness.
- **Settings** live in `[DEFAULT]` when global: `get_profiles()` returns every
  section, so a new section would appear as a phantom profile.

## Testing gotchas that cost real time

- **`QApplication([])` aborts anything using QtWebEngine** — "the program name
  is not passed to QCoreApplication". Pass a program name. `conftest.py` owns
  the single session-scoped `qapp`; do not add another.
- **`tests/test_main_window.py` builds real windows.** Add to it when touching
  startup, menus or wiring — three bugs reached `main` because nothing did.
- **Never assert an exact count or set of shipped plugins.** Use `>=` or a
  superset check, or every new plugin breaks unrelated tests.
- **Wait for the thing you assert**, not for the worker to be idle: signals are
  queued, so idle does not mean delivered. Hold a worker open with
  `threading.Event`, never a long loop.
- **`tests/synthetic_media.py`** builds real MP4s byte by byte; there is no
  ffmpeg and no committed video.
