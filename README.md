## TagOrganizer

Help organize photos and (eventually) videos.

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

- Allow tagging of images using hierachical tags
- Allow adding and deleting tags and changing the hierachy
- Allow selecting the shown images by tags (if multiple tags are
  selected, then the shown photos will have all the tags, that is we
  use a logical and between the tags)
- Allow adding new photos from a directory (currently only .jpg and .JPG are supported)
- If a tag is selected that has children in the hierachy, all those items are also shown
- Import data from old F-Spot libraries

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

### Selecting items

Items can be selected by hitten the 'space' key, in which case they
get a blue frame. The number of selected items is shown in the lower
left of the main window.

### EXIF

In single item mode, you can toggle showing EXIF information by
hitting the 'i' key.

### Tagging

In the lower right a text entry is provided. Here tags can be defined
by typing tags. Autocompletion is provided by using existing
tags. Multipile tags can be comma separted. If one hits enter then the
tags will get assigned to all selected items or, if no items were
selected, to the current item (red border).

To switch between tagging mode and navigation mode use the 'tab' key.

### Ordering and deleting tags

On the left a view of all the tags is available. Tags can be
re-ordered by drag-and-drop. Tags can also be deleted by
right-clicking on a tag. However, tags can only be deleted, if they
have no children in the hierachy.

### Selecting tags

To downselect the shown images, one can double-click on a tag in the
tag view. This will create a button with the tag name at the top of
the window. The shown images will automatically update to only show
items that have all selected tags. The 'clear' button can be used to
remove all tags. Individual tags can be removed from the selection by
clicking on the tag button that is created at the top of the window.

### Profiles

The program supports different profile. Each profile has its own
database, that is its own collection of items and tags. The user
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

This will copy the photos, tags and links between photo and tags. It
will keep the tag hierarchy intact.

## Planned features

- Support more image formats
- Support videos
- Delete items from the database
- Show timeline off all items
- Show map of where images and videos where taken and be able to select by a region on a map
- Cache thumbnails or use system thumbnail cache
- Ability to copy selected photos to a temp folder (e.g., for further editing)
- Option to move all photos into a certain data folder (say Photos/YYYY/MM/DD/<photo>)
- Merge tags (i.e., if we have a tag with a typo and want to merge it with another tag)
- Duplicate detection (on filename and on image data)
- Clean up the database
- Support background tasks that do some of the above checks or, for
  example, update the database when we add a new feature (e.g.,
  tracking data and time of the items which we currently are not
  doing)
