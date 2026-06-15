"""Fetch panel: pull source images from the web into the library.

Two ways to say what to fetch, and they compose:
* type terms directly in the editable terms box (the manual override), or
* click "Suggest from image (Claude)" to auto-fill that box from the target — then
  edit freely before fetching.

The target image (optional) also drives colour-coverage planning so the fetched
set spans the colours the mosaic will need.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..fetch.sources import SOURCES
from ..fetch.tagger import has_api_key


class FetchPanel(QWidget):
    suggestRequested = Signal(str)  # target image path
    fetchRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_path: str | None = None

        self.target_btn = QPushButton("Choose target image…")
        self.target_btn.clicked.connect(self._choose_target)
        self.target_label = QLabel("No target (optional)")
        self.target_label.setWordWrap(True)

        self.terms = QLineEdit()
        self.terms.setPlaceholderText("Type what to fetch, e.g. eyes, iris macro")
        self.terms.setClearButtonEnabled(True)

        self.suggest_btn = QPushButton("Suggest from image (Claude)")
        self.suggest_btn.setEnabled(False)
        self.suggest_btn.clicked.connect(self._suggest)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        if not has_api_key():
            self.hint.setText("Tip: set ANTHROPIC_API_KEY to enable Claude suggestions.")

        self.count = QSpinBox()
        self.count.setRange(10, 5000)
        self.count.setValue(300)
        self.min_res = QSpinBox()
        self.min_res.setRange(64, 4000)
        self.min_res.setValue(400)
        self.min_res.setSingleStep(50)

        form = QFormLayout()
        form.addRow("Images", self.count)
        form.addRow("Min resolution", self.min_res)

        self._source_boxes: dict[str, QCheckBox] = {}
        src_box = QGroupBox("Sources")
        src_layout = QVBoxLayout(src_box)
        for sid, cls in SOURCES.items():
            cb = QCheckBox(cls.label)
            cb.setChecked(True)
            self._source_boxes[sid] = cb
            src_layout.addWidget(cb)

        self.fetch_btn = QPushButton("Fetch && add to library")
        self.fetch_btn.clicked.connect(self._emit_fetch)

        suggest_row = QHBoxLayout()
        suggest_row.addWidget(self.suggest_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.target_btn)
        layout.addWidget(self.target_label)
        layout.addWidget(QLabel("Search terms"))
        layout.addWidget(self.terms)
        layout.addLayout(suggest_row)
        layout.addWidget(self.hint)
        layout.addLayout(form)
        layout.addWidget(src_box)
        layout.addWidget(self.fetch_btn)
        layout.addStretch(1)

    # -- target -------------------------------------------------------------

    def set_target(self, path: str) -> None:
        self._target_path = path
        self.target_label.setText(Path(path).name)
        self.suggest_btn.setEnabled(True)

    def _choose_target(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose target image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)",
        )
        if path:
            self.set_target(path)

    # -- terms --------------------------------------------------------------

    def set_terms(self, terms: list[str]) -> None:
        """Fill the (editable) terms box — used by Claude suggestions."""
        self.terms.setText(", ".join(terms))

    def _parsed_terms(self) -> list[str]:
        return [t.strip() for t in self.terms.text().split(",") if t.strip()]

    # -- signals ------------------------------------------------------------

    def _suggest(self) -> None:
        if self._target_path:
            self.suggestRequested.emit(self._target_path)

    def _emit_fetch(self) -> None:
        sources = [sid for sid, cb in self._source_boxes.items() if cb.isChecked()]
        self.fetchRequested.emit(
            {
                "terms": self._parsed_terms(),
                "target_path": self._target_path,
                "count": self.count.value(),
                "min_width": self.min_res.value(),
                "min_height": self.min_res.value(),
                "sources": sources,
            }
        )
