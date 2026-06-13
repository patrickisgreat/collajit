"""Library browser: thumbnail grid of catalogued source images.

Holds the active :class:`~collajit.library.catalog.Catalog`. Adding a folder runs
ingest off-thread (via the owner) and then :meth:`reload` repopulates the grid.
Double-clicking an image asks the owner to drop it onto the canvas as a layer.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..library.catalog import Catalog


class LibraryPanel(QWidget):
    ingestFolderRequested = Signal(str)
    imageActivated = Signal(str)  # source path

    def __init__(self, catalog: Catalog, parent=None):
        super().__init__(parent)
        self.catalog = catalog

        self.add_btn = QPushButton("Add folder…")
        self.add_btn.clicked.connect(self._choose_folder)
        self.count_label = QLabel("0 images")

        top = QHBoxLayout()
        top.addWidget(self.add_btn)
        top.addStretch(1)
        top.addWidget(self.count_label)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(96, 96))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setSpacing(4)
        self.list.itemDoubleClicked.connect(self._on_activate)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.list, 1)

        self.reload()

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add image folder")
        if folder:
            self.ingestFolderRequested.emit(folder)

    def reload(self) -> None:
        """Rebuild the thumbnail grid from the catalog."""
        self.list.clear()
        records = self.catalog.all_records()
        for rec in records:
            item = QListWidgetItem(QIcon(rec.thumb_path), "")
            item.setData(256, rec.path)  # Qt.UserRole
            item.setToolTip(rec.path)
            self.list.addItem(item)
        self.count_label.setText(f"{len(records)} images")

    def _on_activate(self, item: QListWidgetItem) -> None:
        path = item.data(256)
        if path:
            self.imageActivated.emit(path)
