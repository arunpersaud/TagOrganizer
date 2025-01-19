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
from pathlib import Path
import sys
import os

from . import db
from .migrations import upgrade_db

# Define the application name and author
APP_NAME = "TagOrganizer"
APP_AUTHOR = "TagOrganizer"

# Define the path to the config file
config_dir = Path(platformdirs.user_config_dir(APP_NAME, APP_AUTHOR))
default_config_file_path = config_dir / "config.ini"

PHOTO_SUFFIX = [".jpg", ".jpeg"]
VIDEO_SUFFIX = [".avi", ".mp4"]
ALL_SUFFIX = PHOTO_SUFFIX + VIDEO_SUFFIX


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
        self.config = configparser.ConfigParser()
        if not self.config_file.exists():
            self.create_default_config()
        self.config.read(self.config_file)

        if self.profile not in self.config:
            print(f"[ERROR] {self.profile} not found in {self.config_file}")
            sys.exit(3)

        self.db = self.config[self.profile]["database"]
        self.photos = (
            Path(self.config[self.profile]["photo_path"]).expanduser().resolve()
        )
        self.videos = (
            Path(self.config[self.profile]["video_path"]).expanduser().resolve()
        )

        db.set_engine(self.db)
        os.environ["TAGORGANIZER_DB_URL"] = f"sqlite:///{self.db}"

        # ensure we are using the latest version
        db.create_db()
        # run alembic
        upgrade_db()

    def find_new_database_name(self, dir, profile=None):
        """Find an unused database name."""

        if profile is None:
            profile = self.profile

        name = f"media-{profile}.db"
        test = dir / name
        if not test.exists():
            return name

        i = 0
        while True:
            name = f"media-{profile}-{i:05d}.db"
            test = dir / name
            if not test.exists():
                return name
            if i > 99_999:
                return None

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
        if name in self.config:
            print("[ERROR] Name already exist in config... not adding it")
            return

        db_name = self.find_new_database_name(database_path, name)
        if db_name is None:
            print(f"[ERROR] Cannot find a valid database name in {database_path}")
            sys.exit()

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

    def set_config_file(self, config_file: Path):
        self.config_file = config_file
        self.profile = "default"
        self.read_config()

    def set_current_profile(self, profile_name):
        self.profile = profile_name
        self.read_config()
