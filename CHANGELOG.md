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
- A test suite, run with `pytest`
- `--verbose` option for debug logging
- Tasks are plugins: the Tasks menus are built from a plugin registry, and
  a settings window lists the plugins and the paths in use
- Tasks run on a worker thread, can be cancelled, and can act on the
  current selection instead of the whole library
- A selection of photos: shift-click selects a range, and a view shows only
  the selection
- Move the selected photos into another profile's library (Edit menu)
- The map clusters photos for the area on screen, previews a cluster on
  hover, and can select the photos in an area
- Animated previews for videos on hover, built in the background
- Filter chips can be selected by clicking, removed with Delete, and grouped
  so that they match with OR
- A tag editor to rename, merge and delete tags; tags can also be removed
  from the selection through the tag tree
- Record and show which photos a photo was derived from
- Read capture dates out of file names, and dates and GPS out of videos
- HEIC photos
- Find and merge duplicate photos and tags
- Task to tag photos that contain faces as "People", using the YuNet face
  detector shipped with the package
- Task to clear thumbnails no photo uses any more
- An unexpected error is reported in the window instead of closing the app

### Changed
- Thumbnails are decoded on background threads instead of the GUI thread,
  so the window stays responsive while a page loads
- Diagnostics go through the `logging` module rather than `print`, so they
  are visible when the app is started from a desktop launcher
- Indexes on `uri` and `data_xxhash`; scanning a directory for files already
  in the database is roughly fifteen times faster
- The initial database migration now describes the real schema, and a test
  checks the migrations and the models cannot drift apart
- The timeline has a log scale, and a date range is selected by dragging
- Grid tiles show the whole photo instead of a clipped band
- Tags match case-insensitively
- Thumbnails are saved in a `thumbnails` folder beside the photos on every
  platform, one file per size, so they share the photos' protection
- Full-size photos are decoded in the background and preloaded around the
  current one, with their memory use capped
- Qt's own messages go through logging, without the libpng warnings
- Face detection uses YuNet instead of OpenCV's Haar cascade; OpenCV 5 is
  supported
- Updated to PyQt 6.12, folium 1.0, SQLAlchemy 2.1 and sqlmodel 0.0.50

### Fixed
- Behaviour of cursor keys on the last page
- Creating a new database, or a new profile, crashed on startup with
  "duplicate column name: longitude"
- Tags typed into the tag bar were not applied when several images were
  selected; only single images were tagged
- On a partly filled last page, the highlighted image was not the one that
  got tagged, deleted or opened
- Filtering by a tag left out images that carried both that tag and one of
  its subtags
- Deleting images, and the tag context menu, raised an error instead of
  opening
- The timeline drew a whole multi-year collection as a handful of day-wide
  bins
- The image cursor could move past the end of a filtered selection
- The counters in the status bar could not go back to zero
- A missing or unreadable file no longer breaks the whole page of thumbnails
- "No GPS" and "Wrong dir" could be created as ordinary tags, colliding with
  the built-in filters
- Importing from F-Spot dropped every photo's date
- Switching profiles kept the previous database file open
- Searching for a database by name could hang, and a bad config file
  closed the app
- The single view kept resizing itself
- The map stayed blank when it was drawn while its tab was hidden
- Starting for the first time, with no config, failed
- Double-clicking a grid tile did not move the current-item frame onto it
- Undated files were not all found
- After a profile switch, thumbnails from the previous profile could appear
- Quitting while thumbnails were loading could crash the app
- Tagging a very large selection failed on SQLite's variable limit
- A loop in the tag hierarchy could be created, which made filtering and
  merging tags never finish
- Dragging a nested tag in the tag tree moved a different, top-level tag
- Deleting a tag now asks first, and refuses a tag that has subtags
- Folders were matched with SQL LIKE, so `_` and `%` in a path matched
  other folders, and ignored names matched as substrings
- Paths are compared the way the filesystem holding them does, so
  case-insensitive volumes work
- One malformed EXIF block ended the whole date or location run
- Implausible dates read from videos are rejected
- F-Spot import left most escaped characters in file names, stored dates
  as UTC instead of local time, and broke paths on Windows
- A failed profile switch is rolled back, and switching while a task is
  still stopping is refused
- Clearing unused thumbnails could delete ones another profile shows
- Ungrouping filter chips lost No GPS, No Time and Wrong dir, and a new map
  area left the old area chip behind
- Views did not all redraw after the library changed
- The grid frame could go off screen when a filter shrank the result, or
  out of range on an empty view
- The selected count did not update after selecting on the map
- Keys pressed in other windows were taken by the main window
- One unreadable file stopped deleting or copying the rest
- Opening the delete dialog for a large selection froze the window
- Timeline: the last day of a selected span was left out, a click without
  dragging filtered the view down to nothing, the span marker outlived a
  redraw, and a library without dated photos warned on every redraw
- The date filter kept photos taken at exactly midnight after its end date
- Video audio kept playing after leaving the single view, and a missing
  file showed nothing
- The derived-from actions crashed on the highlighted photo
- Log messages from the app disappeared once Alembic had loaded its config

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
