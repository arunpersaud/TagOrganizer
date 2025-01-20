## TagOrganizer

Help organize photos and videos.

The program is currently still in very early development stages, but
can already be used for organizing images.

## Installing/Testing

You can use [uv](https://docs.astral.sh/uv/) to run the latest version

    uvx --from git+https://github.com/arunpersaud/TagOrganizer.git -p python3.13 TagOrganizer

Note that this will create files on your computer. Mainly an ini file and an empty database.

Alternatively you can also clone this repository and then use `uv` to
run directly from the repository (your working directory needs to be inside the git repo):

    uv run TagOrganizer

## Contributions

Contributions in any form are welcome (e.g., code, issues, documentation, ideas).
The best way is to use the [github issues](https://github.com/arunpersaud/TagOrganizer/issues).

If you plan to contribute code, please run

    pre-commit install

after downloading the repo and before you make commits.

## Features

- Tagging of images using hierachical tags (single photos or multiple)
- Adding and deleting tags and changing the hierachy
- Selecting the displayed images by tags (if multiple tags are
  selected, then the displayed photos will have all the tags, that is
  we use a logical 'and' between the tags), select by an area on the
  map, select by a min/max date
- If a tag is selected that has children in the hierachy, all those items are also shown
- Photos/Videos can be added by selecting a directory. All files in
  that directory will be added (including subdirectories)
- Delete selected photos from the database and/or filesystem
- Extract date and geolocation from EXIF data
- Option to show EXIF data and filename in single photo view (keys 'i', 'f')
- Create a copy of selected photo in a certain directory
- Import data from old F-Spot libraries
- Support photo formats: jpg/jpeg, bmp, gif, png, pbm, pgm, tiff/tif, webp
- Supported video formats: avi, mp4, mkv, mov, wmv, flv, webm

## User interface

The user interface is written in Qt with the goal of making tagging easy.

The current item (an image or in the future also a video) is shown
with a red border. One can navigate the images by using the cursor
keys (left, right, up, down).

### Navigation

The program currently always shows 25 images, if more are available
then the next page will be shown when up/down or left/right reaches
the end of current page. One can also go directly to the next/previous
page by using 'shift-up' or 'shift-down'.

Note: After startup, the program is in 'navigation' mode. That is the
focus is on the grid widget. To switch between 'tagging' and
'navigation', hit the 'tab' key.

### Selecting items

Items can be selected by hitten the 'space' key, in which case they
get a blue frame. The number of selected items is shown in the lower
left of the main window.

### EXIF

In single item mode, you can toggle showing EXIF information by
hitting the 'i' key.

### Filename

In single item mode, you can show the filename of the item by hitting
the 'f' key.

### Tagging

In the lower right a text entry is provided. Here tags can be defined
by typing tags. Autocompletion is provided by using existing
tags. Multipile tags can be comma separted. If one hits enter then the
tags will get assigned to all selected items or, if no items were
selected, to the current item (red border).

### Ordering and deleting tags

On the left a view of all the tags is available. Tags can be
re-ordered by drag-and-drop. Tags can also be deleted by
right-clicking on a tag. However, tags can only be deleted, if they
have no children in the hierachy.

### Selecting tags

To downselect the displayed images, one can double-click on a tag in the
tag view. This will create a button with the tag name at the top of
the window. The shown images will automatically update to only show
items that have all selected tags. The 'clear' button can be used to
remove all tags. Individual tags can be removed from the selection by
clicking on the tag button that is created at the top of the window.

### Selecting a time range

By left clicking on the timeline one can select a minimum time for the
displayed images. If one left-clicks again the time setting gets updates.

Right clicking on the time range does the same, but for a maximum time.

Both will create a button that will show up where the other selected
tags show up. They will have labels like "< 2025-01-01". To remove the
time constraint, click on the button.

### Selecting an area on the mapView

Zoom the map to the area you want to use and hit the 'Select area'
button.  The contraint can be lifted by clicking on the button that is
created in the tag bar.

### Deleting items

The menu (or ctrl+d) provides a way to remove items from the database
and/or the filesystem.

If not items are selected (blue frames), the current item (red frame)
will be used.

Before deletion, a popup window will show smaller thumbnails of all
items. Hovering over those thumbnails will show the filename. In this
dialog the user can select if the files should also be deleted or if
the item only should be removed from the database.

### Profiles

The program supports different profile. Each profile has its own
database, that is its own collection of items and tags. The user can
switch between different profiles using the menu and also create new
profiles.

Profiles are stored in an Ini-file and the program also supports
switching ini-files. This can be useful, if some photos are stored on
an external hard drive or other drives that are not mounted all the
times.

Profiles can be used to easily separate different photo collections,
for example, for work and private photos or a collection of photos of
documents.

### Importing old F-Spot databases

A simple import for old databases exist for data from F-Spot (an old
Gnome Photo manager). To import data you can pick an ini file (or use
the default) and a profile (or use the default) and then point
TagOrganizer to the F-Spot database:

    uv run TagOrganizer --config ~/some_dir/config.ini --profile=docs --import-from-f-spot=~/dir/to/fspot/photos.db

This will add the photos, tags and links between photo and tags. It
will keep the tag hierarchy intact.

## Planned features

- Merge tags (i.e., if we have a tag with a typo and want to merge it
  with another tag, can be done manually already by selecting one tag,
  adding the other and then deleting the first tag)
- Duplicate detection (on filename and on image data)
- Clean up the database
- Print name of files that are in the configured directories for
  photos and videos, but not in the database
