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
from platformdirs import user_data_dir, user_config_dir
from pathlib import Path

# Define the application name and author
APP_NAME = "TagOrganizer"
APP_AUTHOR = "TagOrganizer"

# Get the user data directory for the application
data_dir = Path(user_data_dir(APP_NAME, APP_AUTHOR))
config_dir = Path(user_config_dir(APP_NAME, APP_AUTHOR))

# Ensure the data directory exists
data_dir.mkdir(parents=True, exist_ok=True)
config_dir.mkdir(parents=True, exist_ok=True)

# Define the path to the config file
config_file_path = config_dir / "config.ini"

# Define the default database name
default_db_name = "media.db"


def get_or_create_db_path():
    # Create a ConfigParser object
    config = configparser.ConfigParser()

    if config_file_path.exists():
        # Read the existing config file
        config.read(config_file_path)
        db_path = config["database"]["url"]
    else:
        # Create a new config file with the default database path
        db_path = data_dir / default_db_name
        config["database"] = {"url": f"sqlite:///{db_path}"}
        with config_file_path.open("w") as config_file:
            config.write(config_file)

    return db_path
