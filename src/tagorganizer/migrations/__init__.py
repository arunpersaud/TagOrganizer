"""DB migrations"""

from pathlib import Path

from alembic.config import Config
from alembic import command


ROOT_PATH = Path(__file__).parent.parent
ALEMBIC_CFG = Config(ROOT_PATH / "alembic.ini")


def current_db(verbose=False):
    command.current(ALEMBIC_CFG, verbose=verbose)


def upgrade_db(revision="head"):
    print("DB: upgrade/ensure latest schema")
    command.upgrade(ALEMBIC_CFG, revision)


def downgrade_db(revision):
    command.downgrade(ALEMBIC_CFG, revision)
