# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

## [0.2] - 2025-01-12

### Added

- Task to add geolocation to the database and a new tab to display a map
- Progressbar for background task in the statusbar
- Left and right clicking in the timeline now set a min and max time
  for the displayed images
- Task to sort files into the default directories

### Changed

- Renamed 'Database' menu to 'Tasks' menu
- Order items by dates (newest first)
- Focus on grid of images and not the tag editor
- Renamed 'Add Tag' in menu to 'Add New Tag'

### Fixes

- Timeline bug when no dates are available yet in the database
- Catch some errors when parsing dates from EXIF

## [0.1] - 2025-01-04

Initial release
