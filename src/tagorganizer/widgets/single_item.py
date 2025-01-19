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

from pathlib import Path
import sys

from qtpy.QtWidgets import (
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QScrollArea,
    QStackedLayout,
    QHBoxLayout,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QSlider,
)
from qtpy.QtCore import Qt, QTimer

import vlc

from .helper import load_exif, load_full_pixmap
from .. import config


class VideoItem(QWidget):
    def __init__(self):
        super().__init__()

        self.instance = vlc.Instance()

        # Create a VLC media player
        self.media_player = self.instance.media_player_new()

        # Create the video widget and media player
        self.video_widget = QWidget(self)

        # Create a container widget for the video and buttons
        self.container = QVBoxLayout()
        self.container.addWidget(self.video_widget)

        # Create the control buttons
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.forward_button = QPushButton("Forward")
        self.backward_button = QPushButton("Backward")
        self.stop_button = QPushButton("Stop", self)

        self.play_button.clicked.connect(self.playVideo)
        self.pause_button.clicked.connect(self.pauseVideo)
        self.forward_button.clicked.connect(self.forwardVideo)
        self.backward_button.clicked.connect(self.backwardVideo)
        self.stop_button.clicked.connect(self.stopVideo)

        # Create a slider for seeking through the video
        self.position_slider = QSlider(Qt.Horizontal, self)
        self.position_slider.setToolTip("Position")
        self.position_slider.setMaximum(1000)
        self.position_slider.sliderMoved.connect(self.set_position)

        # Create a slider for volume control
        self.volume_slider = QSlider(Qt.Horizontal, self)
        self.volume_slider.setToolTip("Volume")
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(self.media_player.audio_get_volume())
        self.volume_slider.valueChanged.connect(self.set_volume)

        # Create a label for the current position
        self.position_label = QLabel("00:00", self)

        position_layout = QHBoxLayout()
        position_layout.addWidget(self.position_label)
        position_layout.addWidget(self.position_slider)

        # Create a layout for the volume slider
        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("Volume", self))
        volume_layout.addWidget(self.volume_slider)

        # Create a layout for the control buttons
        control_layout = QHBoxLayout()
        control_layout.addWidget(self.play_button)
        control_layout.addWidget(self.pause_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.forward_button)
        control_layout.addWidget(self.backward_button)

        # Add the controls widget to the stacked layout
        self.container.addLayout(control_layout)
        self.container.addLayout(position_layout)
        self.container.addLayout(volume_layout)

        # Set the main layout for the widget
        self.setLayout(self.container)

        # Set the video widget as the media player's output
        if sys.platform.startswith("linux"):  # for Linux using the X Server
            self.media_player.set_xwindow(self.video_widget.winId())
        elif sys.platform == "win32":  # for Windows
            self.media_player.set_hwnd(self.video_widget.winId())
        elif sys.platform == "darwin":  # for macOS
            self.media_player.set_nsobject(int(self.video_widget.winId()))

        # Create a timer to update the position slider and label
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()

    def set_position(self, position):
        """Set the video position."""
        self.media_player.set_position(position / 1000.0)

    def set_volume(self, volume):
        """Set the volume."""
        self.media_player.audio_set_volume(volume)

    def update_ui(self):
        """Update the UI elements."""
        # Update the position slider and label
        media_pos = self.media_player.get_position()
        self.position_slider.setValue(int(media_pos * 1000))
        self.position_label.setText(self.format_time(self.media_player.get_time()))

    @staticmethod
    def format_time(ms):
        """Format time in milliseconds to mm:ss."""
        seconds = ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02}:{seconds:02}"

    def set_video(self, item):
        self.media_player.stop()
        self.media = self.instance.media_new(item.uri)
        self.media_player.set_media(self.media)
        self.set_position(100)

    def playVideo(self):
        self.media_player.play()

    def stopVideo(self):
        self.media_player.stop()

    def pauseVideo(self):
        self.media_player.pause()

    def forwardVideo(self):
        self.media_player.set_time(
            self.media_player.get_time() + 10000
        )  # Forward 10 seconds

    def backwardVideo(self):
        self.media_player.set_time(
            self.media_player.get_time() - 10000
        )  # Backward 10 seconds


class PhotoItem(QWidget):
    def __init__(self):
        super().__init__()
        layout = QStackedLayout()
        layout.setStackingMode(QStackedLayout.StackAll)

        self.item = QLabel()
        self.item.setAlignment(Qt.AlignCenter)

        self.exif_table = QTableWidget()
        self.exif_table.setVisible(False)
        self.exif_table.setColumnCount(2)
        self.exif_table.setHorizontalHeaderLabels(["Key", "Value"])
        self.exif_table.verticalHeader().setVisible(False)
        self.exif_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.exif_table.setSizeAdjustPolicy(
            QTableWidget.SizeAdjustPolicy.AdjustToContents
        )
        # 50% transparent black
        self.exif_table.setStyleSheet(
            "QTableWidget { background-color: rgba(0, 0, 0, 100); }"
            "QHeaderView::section { background-color: rgba(0, 0, 0, 127); }"
        )

        # Scroll area for EXIF table
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setWidget(self.exif_table)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; }")
        self.scroll_area.viewport().setStyleSheet("background-color: transparent;")

        self.scroll_area_container = QWidget()
        self.scroll_area_container.setStyleSheet("background: transparent;")
        self.scroll_area_layout = QHBoxLayout()
        self.scroll_area_layout.addStretch()
        self.scroll_area_layout.addWidget(self.scroll_area)
        self.scroll_area_container.setLayout(self.scroll_area_layout)
        self.scroll_area_container.setVisible(False)

        layout.addWidget(self.item)
        layout.addWidget(self.scroll_area_container)

        self.setLayout(layout)

    def load_exif(self, filename: str):
        tags = load_exif(filename)
        self.show_exif(tags)

    def show_exif(self, tags):
        self.exif_table.clearContents()
        self.exif_table.setRowCount(len(tags))
        for row, (key, value) in enumerate(sorted(tags.items())):
            key_item = QTableWidgetItem(key)
            value_item = QTableWidgetItem(self.format_str(value))
            self.exif_table.setItem(row, 0, key_item)
            self.exif_table.setItem(row, 1, value_item)
        self.exif_table.resizeColumnsToContents()
        self.adjust_scroll_area_width()

    def adjust_scroll_area_width(self):
        # Calculate the required width for the scroll area
        width = (
            self.exif_table.verticalHeader().width()
            + self.exif_table.columnWidth(0)
            + self.exif_table.columnWidth(1)
            + self.exif_table.verticalScrollBar().width()
        )
        self.scroll_area.setMinimumWidth(width)
        self.scroll_area_container.setMinimumWidth(width)
        self.scroll_area_container.resize(self.item.size())

    def format_str(self, s) -> str:
        s = str(s)
        if len(s) > 20:
            s = s[:17] + "..."
        return s

    def setPixmap(self, pixmap):
        self.item.setPixmap(pixmap)

    def toggle_exif_visibility(self):
        self.scroll_area_container.setVisible(
            not self.scroll_area_container.isVisible()
        )

    def set_photo(self, item):
        pixmap = load_full_pixmap(str(item.uri))
        pixmap = pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self.setPixmap(pixmap)
        self.load_exif(str(item.uri))


class SingleItem(QWidget):
    def __init__(self):
        super().__init__()
        layout = QStackedLayout()
        layout.setStackingMode(QStackedLayout.StackAll)

        self.photo = PhotoItem()
        self.video = VideoItem()

        self.filename = QLineEdit()
        self.filename.setReadOnly(True)
        self.filename.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.filename.setStyleSheet("background: transparent; border: none;")
        self.filename.setVisible(False)

        layout.addWidget(self.photo)
        layout.addWidget(self.video)
        layout.addWidget(self.filename)

        self.setLayout(layout)

    def toggle_exif_visibility(self):
        self.photo.toggle_exif_visibility()

    def toggle_filename_visibility(self):
        self.filename.setVisible(not self.filename.isVisible())

    def set_item(self, item):
        file_path = Path(item.uri)

        if not file_path.is_file():
            print(f"[ERROR] file {file_path} does not exist")
            return

        self.filename.setText(item.uri)

        if file_path.suffix.lower() in config.PHOTO_SUFFIX:
            self.photo.set_photo(item)
            self.video.setVisible(False)
            self.photo.setVisible(True)
        elif file_path.suffix.lower() in config.VIDEO_SUFFIX:
            self.video.set_video(item)
            self.photo.setVisible(False)
            self.video.setVisible(True)
        else:
            print(f"[ERROR] file {file_path} has unknown file type.")
