"""Running migrations must not silence the application's own loggers.

Alembic's env.py calls logging.config.fileConfig, which by default disables
every logger that already exists. That call runs at startup and again whenever
a move prepares a target database, so an unguarded run would quietly switch
off all tagorganizer.* logging.
"""

import logging

from tagorganizer import migrations


def test_migrations_leave_existing_app_loggers_enabled(tmp_path, monkeypatch):
    logger = logging.getLogger("tagorganizer.test_probe_logger")
    logger.disabled = False

    path = tmp_path / "library.db"
    monkeypatch.setenv("TAGORGANIZER_DB_URL", f"sqlite:///{path}")
    migrations.upgrade_db()

    assert logger.disabled is False
