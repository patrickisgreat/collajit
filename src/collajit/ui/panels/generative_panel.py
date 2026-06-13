"""Generative-layout controls: colour sort or 2-D embedding into a grid."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...generators.generative import EMBED_METHODS, SORT_KEYS


class GenerativePanel(QWidget):
    generateRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.mode = QComboBox()
        self.mode.addItems(["Colour sort", "Embedding (similarity)"])
        self.mode.currentIndexChanged.connect(self._on_mode)

        self.sort_key = QComboBox()
        self.sort_key.addItems(SORT_KEYS)
        sort_form = QFormLayout()
        sort_form.addRow("Order by", self.sort_key)
        sort_w = QWidget()
        sort_w.setLayout(sort_form)

        self.embed_method = QComboBox()
        self.embed_method.addItems(EMBED_METHODS)
        embed_form = QFormLayout()
        embed_form.addRow("Method", self.embed_method)
        embed_w = QWidget()
        embed_w.setLayout(embed_form)

        self.stack = QStackedWidget()
        self.stack.addWidget(sort_w)
        self.stack.addWidget(embed_w)

        self.cols = QSpinBox()
        self.cols.setRange(2, 400)
        self.cols.setValue(40)
        self.tile_px = QSpinBox()
        self.tile_px.setRange(8, 256)
        self.tile_px.setValue(64)

        common = QFormLayout()
        common.addRow("Columns", self.cols)
        common.addRow("Tile px", self.tile_px)
        common_w = QWidget()
        common_w.setLayout(common)

        self.generate_btn = QPushButton("Generate layout")
        self.generate_btn.clicked.connect(self._emit)

        layout = QVBoxLayout(self)
        layout.addWidget(self.mode)
        layout.addWidget(self.stack)
        layout.addWidget(common_w)
        layout.addWidget(self.generate_btn)
        layout.addStretch(1)

    def _on_mode(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)

    def _emit(self) -> None:
        if self.mode.currentIndex() == 0:
            params = {"mode": "color_sort", "key": self.sort_key.currentText()}
        else:
            params = {"mode": "embedding", "method": self.embed_method.currentText()}
        params.update(cols=self.cols.value(), tile_px=self.tile_px.value())
        self.generateRequested.emit(params)
