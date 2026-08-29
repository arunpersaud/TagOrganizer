"""DB migrations"""

import logging
from pathlib import Path

from alembic.config import Config
from alembic import command


ROOT_PATH = Path(__file__).parent.parent
ALEMBIC_CFG = Config(ROOT_PATH / "alembic.ini")

logger = logging.getLogger(__name__)


def current_db(verbose=False):
    command.current(ALEMBIC_CFG, verbose=verbose)


def upgrade_db(revision="head"):
    logger.info("upgrading database to %s", revision)
    command.upgrade(ALEMBIC_CFG, revision)


def downgrade_db(revision):
    command.downgrade(ALEMBIC_CFG, revision)


def stamp_db(revision="head"):
    """Stamp the database at a revision without running migrations.

    Used for newly created databases that already have the full schema
    created via SQLModel.metadata.create_all().
    """
    logger.info("stamping new database at %s", revision)
    command.stamp(ALEMBIC_CFG, revision)
