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

import configparser
import platformdirs
import logging
from pathlib import Path
import os

from . import db
from .migrations import upgrade_db, stamp_db

# Define the application name and author
APP_NAME = "TagOrganizer"
APP_AUTHOR = "TagOrganizer"

logger = logging.getLogger(__name__)

# Define the path to the config file
config_dir = Path(platformdirs.user_config_dir(APP_NAME, APP_AUTHOR))
default_config_file_path = config_dir / "config.ini"

PHOTO_SUFFIX = [
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".png",
    ".pbm",
    ".pgm",
    ".tiff",
    ".tif",
    ".webp",
]
VIDEO_SUFFIX = [".avi", ".mp4", ".mkv", ".mov", ".wmv", ".flv", ".webm"]
ALL_SUFFIX = PHOTO_SUFFIX + VIDEO_SUFFIX


class ProfileNotFoundError(Exception):
    """The requested profile is not defined in this config file.

    Raised rather than exiting: read_config runs while the GUI is up, and a
    profile the user mistyped must not take the application down with it.
    """

    def __init__(self, profile: str, config_file):
        super().__init__(f"profile {profile!r} not found in {config_file}")
        self.profile = profile
        self.config_file = Path(config_file)


def next_database_name(profile: str, exists, limit: int = 100_000) -> str | None:
    """First unused database file name for this profile.

    `exists` answers whether a candidate is taken, which keeps the search itself
    off the filesystem and testable.
    """
    name = f"media-{profile}.db"
    if not exists(name):
        return name

    for i in range(limit):
        name = f"media-{profile}-{i:05d}.db"
        if not exists(name):
            return name
    return None


class ConfigManager:
    def __init__(self):
        self.config = None

        self.profile = "default"
        self.config_file = default_config_file_path

        # locations needed in app
        self.db = None
        self.photos = None
        self.videos = None

        self.read_config()

    def read_config(self):
        if not self.config_file.exists():
            # First run: there is no existing configuration to protect, and
            # create_default_config writes through self.config, so it has to
            # exist. The no-mutation-on-failure guarantee below is about
            # switching to a bad config file while the application is running,
            # and that path always has a file already.
            if self.config is None:
                self.config = configparser.ConfigParser()
            self.create_default_config()

        config = configparser.ConfigParser()
        config.read(self.config_file)

        if self.profile not in config:
            raise ProfileNotFoundError(self.profile, self.config_file)

        # Profile is valid; now safe to mutate state.
        self.config = config
        self.db = self.config[self.profile]["database"]
        self.photos = (
            Path(self.config[self.profile]["photo_path"]).expanduser().resolve()
        )
        self.videos = (
            Path(self.config[self.profile]["video_path"]).expanduser().resolve()
        )

        db.set_engine(self.db)
        os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{self.db}"

        # Check if database file already exists
        db_path = Path(self.db)
        db_is_new = not db_path.exists()

        # Building the schema and stamping it are only ever correct together:
        # create_all writes the *current* models, so the migrations that would
        # have built them must be marked done rather than run.
        if db_is_new:
            db.create_db()
            stamp_db("head")
        else:
            # An existing database belongs to the migrations. Calling
            # create_all here would create any table a pending migration is
            # about to add, and that migration would then fail on the table it
            # found already there - leaving the application unable to open a
            # library it opened fine yesterday.
            upgrade_db()

    def find_new_database_name(self, dir, profile=None):
        """Find an unused database name in `dir`."""
        if profile is None:
            profile = self.profile
        return next_database_name(profile, lambda name: (dir / name).exists())

    def create_default_config(self):
        # Get the user data directory for the application
        data_dir = Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))

        # Ensure the data directory exists
        data_dir.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)

        photo_dir = platformdirs.user_pictures_dir()
        video_dir = platformdirs.user_videos_dir()

        self.create_new_profile("default", data_dir, photo_dir, video_dir)

    def create_new_profile(
        self, name: str, database_path: Path, photo_dir: str, video_dir: str
    ):
        name = name.strip()
        if not name:
            logger.error("refusing to create a profile with an empty name")
            return
        if name == configparser.DEFAULTSECT:
            # configparser treats the literal [DEFAULT] section as the fallback
            # for every other section, so a profile by that exact name would leak
            # its keys into all others. Section names are case-sensitive, so
            # "default" is fine; only the literal "DEFAULT" is forbidden.
            logger.error("'DEFAULT' is reserved; pick another profile name")
            return
        if name in self.config:
            logger.error("profile %r already exists in the config; not adding it", name)
            return

        database_path = Path(database_path)
        database_path.mkdir(parents=True, exist_ok=True)

        db_name = self.find_new_database_name(database_path, name)
        if db_name is None:
            logger.error("cannot find an unused database name in %s", database_path)
            return

        db_path = database_path / db_name

        self.config[name] = {
            "database": str(db_path),
            "photo_path": photo_dir,
            "video_path": video_dir,
        }
        with self.config_file.open("w") as configfile:
            self.config.write(configfile)

    def get_profiles(self):
        return self.config.sections()

    def get_profile_database(self, name: str) -> Path:
        """Return the configured database path for a profile.

        Raises ProfileNotFoundError if the profile is not defined.
        """
        if name not in self.config:
            raise ProfileNotFoundError(name, self.config_file)
        return Path(self.config[name]["database"])

    def set_config_file(self, config_file: Path):
        self.config_file = config_file
        self.profile = "default"
        self.read_config()

    def set_current_profile(self, profile_name):
        self.profile = profile_name
        self.read_config()
