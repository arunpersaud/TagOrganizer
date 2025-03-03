# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

### Added
- Support for videos using vlc-python (for playback) and cv2 (for thumbnails)
- Saving thumbnails for faster startup
- Start using message tab to display status information, etc.
- Added support for more image/video formats (depending on QPixmap, vlc, cv2)
- Task to print files that are in the default dirs, but not in the db
  (to make cleanup easier)
- Show number of filtered, selected, and total images

### Fixed
- Behaviour of cursor keys on the last page

## [0.3] - 2025-01-18

### Added
- New automatically created tags that will show images without
  timestamps, GPS or items that are not in the configured directories
- Delete selected (or current) file(s), either from database or also
  from the file system
- Ability to copy selected items to a folder
- The 'F'-key will now show the file location in single item view
- Select photos by area shown in the map window

### Fixed
- Scaling of thumbnails in grid view, so that we always can see the
  whole window

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

### Fixed

- Timeline bug when no dates are available yet in the database
- Catch some errors when parsing dates from EXIF

## [0.1] - 2025-01-04

Initial release
