"""Freeform-collage controls: scatter N library images as editable layers."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

#: Named blend-mode pools the user can scatter with.
BLEND_PRESETS = {
    "Normal": ("normal",),
    "Varied (screen/multiply/overlay)": ("screen", "multiply", "overlay"),
    "Lighten / screen": ("lighten", "screen"),
}


class FreeformPanel(QWidget):
    generateRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.count = QSpinBox()
        self.count.setRange(1, 2000)
        self.count.setValue(40)

        self.size_min = QDoubleSpinBox()
        self.size_min.setRange(0.02, 2.0)
        self.size_min.setSingleStep(0.05)
        self.size_min.setValue(0.2)
        self.size_max = QDoubleSpinBox()
        self.size_max.setRange(0.02, 2.0)
        self.size_max.setSingleStep(0.05)
        self.size_max.setValue(0.5)

        self.rotation = QDoubleSpinBox()
        self.rotation.setRange(0.0, 180.0)
        self.rotation.setValue(25.0)

        self.blend = QComboBox()
        self.blend.addItems(BLEND_PRESETS.keys())

        self.scatter_btn = QPushButton("Scatter images")
        self.scatter_btn.clicked.connect(self._emit)

        form = QFormLayout()
        form.addRow("Count", self.count)
        form.addRow("Min size", self.size_min)
        form.addRow("Max size", self.size_max)
        form.addRow("Rotation ±°", self.rotation)
        form.addRow("Blend", self.blend)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.scatter_btn)
        layout.addStretch(1)

    def _emit(self) -> None:
        lo = self.size_min.value()
        hi = max(self.size_max.value(), lo)
        self.generateRequested.emit(
            {
                "mode": "freeform",
                "count": self.count.value(),
                "size_frac": (lo, hi),
                "rotation_jitter": self.rotation.value(),
                "blend_modes": BLEND_PRESETS[self.blend.currentText()],
            }
        )
