"""Running migrations must not silence the application's own loggers.

Alembic's env.py calls logging.config.fileConfig, which by default disables
every logger that already exists. That call runs at startup and again whenever
a move prepares a target database, so an unguarded run would quietly switch
off all tagorganizer.* logging.
"""

import logging
import os

from tagorganizer import migrations


def test_migrations_leave_existing_app_loggers_enabled(tmp_path):
    logger = logging.getLogger("tagorganizer.test_probe_logger")
    logger.disabled = False

    path = tmp_path / "library.db"
    os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{path}"
    try:
        migrations.upgrade_db()
    finally:
        os.environ.pop("TAGORGANIZER_DB_URL", None)

    assert logger.disabled is False
