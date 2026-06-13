"""Interactive canvas built on QGraphicsView.

Each :class:`~collajit.model.layer.Layer` becomes a :class:`LayerItem` whose
position / scale / rotation mirror the layer's transform. User manipulation
(drag to move, modifier+wheel to scale/rotate, Delete to remove) writes straight
back to the model, so :meth:`CanvasView.rebuild` and export always agree.

Controls
--------
* Drag                         move selected layer(s)
* Wheel                        zoom the canvas (anchored under the cursor)
* Ctrl/Cmd + Wheel             scale selected layer(s)
* Alt + Wheel, or ``[`` ``]``  rotate selected layer(s)
* Space-drag / middle-drag     pan
* Delete / Backspace           remove selected layer(s)
"""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)

from ..model.project import Project

_ZOOM_STEP = 1.15
_SCALE_STEP = 1.08
_ROTATE_STEP = 5.0


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class LayerItem(QGraphicsPixmapItem):
    """A graphics item bound to a layer id; reports moves back to the view."""

    def __init__(self, layer_id: str, pixmap: QPixmap, view: CanvasView):
        super().__init__(pixmap)
        self.layer_id = layer_id
        self._view = view
        self.setTransformOriginPoint(pixmap.width() / 2.0, pixmap.height() / 2.0)
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    def itemChange(self, change, value):
        if (
            change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged
            and self.scene() is not None
        ):
            self._view.on_item_geometry_changed(self)
        return super().itemChange(change, value)


class CanvasView(QGraphicsView):
    selectionChangedTo = Signal(object)  # layer_id or None
    layerGeometryChanged = Signal(str)  # layer_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setBackgroundBrush(QColor(48, 48, 50))
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        self.project: Project | None = None
        self._items: dict[str, LayerItem] = {}
        self._page: QGraphicsRectItem | None = None
        self._panning = False
        self._scene.selectionChanged.connect(self._emit_selection)

    # -- project binding ----------------------------------------------------

    def set_project(self, project: Project) -> None:
        self.project = project
        self.rebuild()
        self.fit_page()

    def rebuild(self) -> None:
        """Recreate every scene item from the current project state."""
        self._scene.clear()
        self._items.clear()
        self._page = None
        if self.project is None:
            return

        w, h = self.project.size
        margin = max(w, h) * 0.5
        self._scene.setSceneRect(-margin, -margin, w + 2 * margin, h + 2 * margin)

        self._page = QGraphicsRectItem(QRectF(0, 0, w, h))
        self._page.setBrush(QBrush(QColor(255, 255, 255)))
        self._page.setPen(QPen(QColor(90, 90, 95), 0))
        self._page.setZValue(-1000)
        self._scene.addItem(self._page)

        for z, layer in enumerate(self.project.layers):
            if not layer.has_image:
                continue
            self._add_item(layer, z)

    def _add_item(self, layer, z: int) -> None:
        pixmap = pil_to_qpixmap(layer.get_image())
        item = LayerItem(layer.id, pixmap, self)
        w = pixmap.width()
        h = pixmap.height()
        item.setZValue(z)
        item.setScale(layer.transform.scale)
        item.setRotation(layer.transform.rotation)
        item.setOpacity(layer.opacity)
        item.setPos(layer.transform.cx - w / 2.0, layer.transform.cy - h / 2.0)
        item.setVisible(layer.visible)
        item.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not layer.locked
        )
        self._scene.addItem(item)
        self._items[layer.id] = item

    def refresh_layer(self, layer_id: str) -> None:
        """Re-sync one item to its layer (opacity/visibility/lock/z), cheap."""
        if self.project is None:
            return
        layer = self.project.find(layer_id)
        item = self._items.get(layer_id)
        if layer is None or item is None:
            return
        item.setOpacity(layer.opacity)
        item.setVisible(layer.visible)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not layer.locked)
        item.setZValue(self.project.layers.index(layer))

    def fit_page(self) -> None:
        if self._page is not None:
            self.fitInView(self._page, Qt.AspectRatioMode.KeepAspectRatio)

    # -- selection ----------------------------------------------------------

    def select_layer(self, layer_id: str | None) -> None:
        self._scene.blockSignals(True)
        self._scene.clearSelection()
        if layer_id and layer_id in self._items:
            self._items[layer_id].setSelected(True)
        self._scene.blockSignals(False)
        self._emit_selection()

    def _emit_selection(self) -> None:
        sel = self._scene.selectedItems()
        layer_id = sel[0].layer_id if sel and isinstance(sel[0], LayerItem) else None
        self.selectionChangedTo.emit(layer_id)

    def _selected_layer_items(self) -> list[LayerItem]:
        return [it for it in self._scene.selectedItems() if isinstance(it, LayerItem)]

    # -- model writeback ----------------------------------------------------

    def on_item_geometry_changed(self, item: LayerItem) -> None:
        if self.project is None:
            return
        layer = self.project.find(item.layer_id)
        if layer is None:
            return
        w = item.pixmap().width()
        h = item.pixmap().height()
        layer.transform.cx = item.x() + w / 2.0
        layer.transform.cy = item.y() + h / 2.0
        layer.transform.scale = item.scale()
        layer.transform.rotation = item.rotation()
        self.layerGeometryChanged.emit(layer.id)

    def _apply_scale(self, factor: float) -> None:
        for item in self._selected_layer_items():
            item.setScale(max(0.01, item.scale() * factor))
            self.on_item_geometry_changed(item)

    def _apply_rotation(self, delta_deg: float) -> None:
        for item in self._selected_layer_items():
            item.setRotation(item.rotation() + delta_deg)
            self.on_item_geometry_changed(item)

    def _delete_selected(self) -> None:
        if self.project is None:
            return
        for item in self._selected_layer_items():
            self.project.remove_layer(item.layer_id)
            self._items.pop(item.layer_id, None)
            self._scene.removeItem(item)
        self._emit_selection()

    # -- events -------------------------------------------------------------

    def wheelEvent(self, event):
        mods = event.modifiers()
        delta = event.angleDelta().y()
        if delta == 0:
            return
        up = delta > 0
        if mods & Qt.KeyboardModifier.ControlModifier:
            self._apply_scale(_SCALE_STEP if up else 1.0 / _SCALE_STEP)
        elif mods & Qt.KeyboardModifier.AltModifier:
            self._apply_rotation(_ROTATE_STEP if up else -_ROTATE_STEP)
        else:
            factor = _ZOOM_STEP if up else 1.0 / _ZOOM_STEP
            self.scale(factor, factor)
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected()
        elif key == Qt.Key.Key_BracketLeft:
            self._apply_rotation(-_ROTATE_STEP)
        elif key == Qt.Key.Key_BracketRight:
            self._apply_rotation(_ROTATE_STEP)
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._apply_scale(_SCALE_STEP)
        elif key == Qt.Key.Key_Minus:
            self._apply_scale(1.0 / _SCALE_STEP)
        elif key == Qt.Key.Key_Space and not self._panning:
            self._panning = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self._panning:
            self._panning = False
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            # Re-dispatch as a left press so ScrollHandDrag engages.
            from PySide6.QtGui import QMouseEvent

            fake = QMouseEvent(
                event.type(),
                event.position(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
            super().mousePressEvent(fake)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            return
        super().mouseReleaseEvent(event)
