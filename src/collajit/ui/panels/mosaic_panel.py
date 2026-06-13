"""Photo-mosaic controls: pick a target image, tune the grid, generate."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class MosaicPanel(QWidget):
    generateRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_path: str | None = None

        self.choose_btn = QPushButton("Choose target image…")
        self.choose_btn.clicked.connect(self._choose_target)
        self.target_label = QLabel("No target chosen")
        self.target_label.setWordWrap(True)

        self.cols = QSpinBox()
        self.cols.setRange(4, 400)
        self.cols.setValue(60)

        self.tile_px = QSpinBox()
        self.tile_px.setRange(8, 128)
        self.tile_px.setValue(48)

        self.tint = QSlider(Qt.Orientation.Horizontal)
        self.tint.setRange(0, 100)
        self.tint.setValue(25)

        self.max_uses = QSpinBox()
        self.max_uses.setRange(0, 1000)
        self.max_uses.setValue(8)
        self.max_uses.setToolTip("Max times a source repeats (0 = unlimited)")

        self.generate_btn = QPushButton("Generate mosaic")
        self.generate_btn.clicked.connect(self._emit)

        form = QFormLayout()
        form.addRow("Tiles across", self.cols)
        form.addRow("Tile px", self.tile_px)
        form.addRow("Colour tint", self.tint)
        form.addRow("Max reuse", self.max_uses)

        layout = QVBoxLayout(self)
        layout.addWidget(self.choose_btn)
        layout.addWidget(self.target_label)
        layout.addLayout(form)
        layout.addWidget(self.generate_btn)
        layout.addStretch(1)

    def _choose_target(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose target image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
        )
        if path:
            self._target_path = path
            self.target_label.setText(path)

    def _emit(self) -> None:
        self.generateRequested.emit(
            {
                "mode": "mosaic",
                "target_path": self._target_path,
                "cols": self.cols.value(),
                "tile_px": self.tile_px.value(),
                "tint": self.tint.value() / 100.0,
                "max_uses": self.max_uses.value() or None,
            }
        )
