"""Layer stack list plus property controls for the selected layer.

The list shows layers top-of-stack first (matching how they paint). Editing a
control mutates the model in place and emits :attr:`layerChanged` so the canvas
re-syncs that one item.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..engine.compositor import BLEND_MODES
from ..model.project import Project


class LayersPanel(QWidget):
    layerSelected = Signal(object)  # layer_id or None
    layerChanged = Signal(str)
    moveRequested = Signal(str, int)
    deleteRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Project | None = None
        self._current: str | None = None
        self._loading = False

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_row_changed)
        self.list.itemChanged.connect(self._on_item_checked)

        up = QPushButton("▲")
        down = QPushButton("▼")
        delete = QPushButton("Delete")
        up.clicked.connect(lambda: self._move(+1))
        down.clicked.connect(lambda: self._move(-1))
        delete.clicked.connect(self._delete)
        btns = QHBoxLayout()
        btns.addWidget(up)
        btns.addWidget(down)
        btns.addStretch(1)
        btns.addWidget(delete)

        # --- selected-layer properties ---
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.valueChanged.connect(self._on_opacity)

        self.blend = QComboBox()
        self.blend.addItems(BLEND_MODES)
        self.blend.currentTextChanged.connect(self._on_blend)

        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.01, 50.0)
        self.scale.setSingleStep(0.05)
        self.scale.valueChanged.connect(self._on_scale)

        self.rotation = QDoubleSpinBox()
        self.rotation.setRange(-360.0, 360.0)
        self.rotation.setSingleStep(1.0)
        self.rotation.valueChanged.connect(self._on_rotation)

        form = QFormLayout()
        form.addRow("Opacity", self.opacity)
        form.addRow("Blend", self.blend)
        form.addRow("Scale", self.scale)
        form.addRow("Rotation", self.rotation)
        self._props = QWidget()
        self._props.setLayout(form)
        self._props.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Layers"))
        layout.addWidget(self.list, 1)
        layout.addLayout(btns)
        layout.addWidget(self._props)

    # -- population ---------------------------------------------------------

    def set_project(self, project: Project) -> None:
        self.project = project
        self.reload()

    def reload(self) -> None:
        self._loading = True
        self.list.clear()
        if self.project is not None:
            for layer in reversed(self.project.layers):  # top of stack first
                item = QListWidgetItem(layer.name)
                item.setData(256, layer.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
                )
                self.list.addItem(item)
        self._loading = False
        self.set_selected(self._current)

    def set_selected(self, layer_id: str | None) -> None:
        self._current = layer_id
        self._loading = True
        match = None
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(256) == layer_id:
                match = it
                break
        self.list.setCurrentItem(match)
        self._load_props(layer_id)
        self._loading = False

    def _load_props(self, layer_id: str | None) -> None:
        layer = self.project.find(layer_id) if (self.project and layer_id) else None
        self._props.setEnabled(layer is not None)
        if layer is None:
            return
        self.opacity.setValue(int(round(layer.opacity * 100)))
        self.blend.setCurrentText(layer.blend)
        self.scale.setValue(layer.transform.scale)
        self.rotation.setValue(layer.transform.rotation)

    # -- list events --------------------------------------------------------

    def _on_row_changed(self, current, _prev) -> None:
        if self._loading:
            return
        layer_id = current.data(256) if current else None
        self._current = layer_id
        self._load_props(layer_id)
        self.layerSelected.emit(layer_id)

    def _on_item_checked(self, item: QListWidgetItem) -> None:
        if self._loading or self.project is None:
            return
        layer = self.project.find(item.data(256))
        if layer is None:
            return
        layer.visible = item.checkState() == Qt.CheckState.Checked
        self.layerChanged.emit(layer.id)

    # -- property events ----------------------------------------------------

    def _current_layer(self):
        if self._loading or self.project is None or self._current is None:
            return None
        return self.project.find(self._current)

    def _on_opacity(self, value: int) -> None:
        layer = self._current_layer()
        if layer:
            layer.opacity = value / 100.0
            self.layerChanged.emit(layer.id)

    def _on_blend(self, mode: str) -> None:
        layer = self._current_layer()
        if layer:
            layer.blend = mode
            self.layerChanged.emit(layer.id)

    def _on_scale(self, value: float) -> None:
        layer = self._current_layer()
        if layer:
            layer.transform.scale = value
            self.layerChanged.emit(layer.id)

    def _on_rotation(self, value: float) -> None:
        layer = self._current_layer()
        if layer:
            layer.transform.rotation = value
            self.layerChanged.emit(layer.id)

    def _move(self, delta: int) -> None:
        if self._current:
            self.moveRequested.emit(self._current, delta)

    def _delete(self) -> None:
        if self._current:
            self.deleteRequested.emit(self._current)
