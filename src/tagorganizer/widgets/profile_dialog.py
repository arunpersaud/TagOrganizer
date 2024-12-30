from qtpy.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QHBoxLayout,
)


class ProfileDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Create New Profile")

        # Create layout
        layout = QVBoxLayout()

        # Profile name
        self.profile_name_label = QLabel("Profile Name:")
        self.profile_name_edit = QLineEdit()
        layout.addWidget(self.profile_name_label)
        layout.addWidget(self.profile_name_edit)

        # Database location
        self.db_location_label = QLabel("Database Location:")
        self.db_location_edit = QLineEdit()
        self.db_location_button = QPushButton("Browse...")
        self.db_location_button.clicked.connect(self.browse_db_location)
        db_layout = QHBoxLayout()
        db_layout.addWidget(self.db_location_edit)
        db_layout.addWidget(self.db_location_button)
        layout.addWidget(self.db_location_label)
        layout.addLayout(db_layout)

        # Photos directory
        self.photos_dir_label = QLabel("Photos Directory:")
        self.photos_dir_edit = QLineEdit()
        self.photos_dir_button = QPushButton("Browse...")
        self.photos_dir_button.clicked.connect(self.browse_photos_dir)
        photos_layout = QHBoxLayout()
        photos_layout.addWidget(self.photos_dir_edit)
        photos_layout.addWidget(self.photos_dir_button)
        layout.addWidget(self.photos_dir_label)
        layout.addLayout(photos_layout)

        # Videos directory
        self.videos_dir_label = QLabel("Videos Directory:")
        self.videos_dir_edit = QLineEdit()
        self.videos_dir_button = QPushButton("Browse...")
        self.videos_dir_button.clicked.connect(self.browse_videos_dir)
        videos_layout = QHBoxLayout()
        videos_layout.addWidget(self.videos_dir_edit)
        videos_layout.addWidget(self.videos_dir_button)
        layout.addWidget(self.videos_dir_label)
        layout.addLayout(videos_layout)

        # OK and Cancel buttons
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.ok_button)
        buttons_layout.addWidget(self.cancel_button)
        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def browse_db_location(self):
        dir_name = QFileDialog.getExistingDirectory(self, "Select Database Directory")
        if dir_name:
            self.db_location_edit.setText(dir_name)

    def browse_photos_dir(self):
        dir_name = QFileDialog.getExistingDirectory(self, "Select Photos Directory")
        if dir_name:
            self.photos_dir_edit.setText(dir_name)

    def browse_videos_dir(self):
        dir_name = QFileDialog.getExistingDirectory(self, "Select Videos Directory")
        if dir_name:
            self.videos_dir_edit.setText(dir_name)

    def get_profile_data(self):
        return {
            "profile_name": self.profile_name_edit.text(),
            "db_location": self.db_location_edit.text(),
            "photos_dir": self.photos_dir_edit.text(),
            "videos_dir": self.videos_dir_edit.text(),
        }
