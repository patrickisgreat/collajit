"""The application window: owns the catalog + project and coordinates everything.

Panels never touch each other directly — they emit signals that this window turns
into model mutations, then refreshes the canvas and layer list. Heavy work
(ingest, mosaic, generative) runs through :func:`~collajit.ui.worker.run_async`.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QTabWidget,
)

from ..engine import image_ops
from ..generators import freeform, generative, mosaic
from ..library import ingest as ingest_images
from ..library.catalog import Catalog
from ..model.layer import Layer, Transform
from ..model.project import Project
from .canvas import CanvasView
from .layers_panel import LayersPanel
from .library_panel import LibraryPanel
from .panels import FreeformPanel, GenerativePanel, MosaicPanel
from .worker import run_async

_DEFAULT_W, _DEFAULT_H = 1600, 1000


class MainWindow(QMainWindow):
    def __init__(self, catalog: Catalog):
        super().__init__()
        self.setWindowTitle("collajit")
        self.resize(1500, 950)

        self.catalog = catalog
        self.project = Project(width=_DEFAULT_W, height=_DEFAULT_H)

        self.canvas = CanvasView()
        self.setCentralWidget(self.canvas)
        self.canvas.set_project(self.project)

        self._build_docks()
        self._build_menus()
        self._build_statusbar()
        self._wire()

    # -- construction -------------------------------------------------------

    def _build_docks(self) -> None:
        self.library = LibraryPanel(self.catalog)
        lib_dock = QDockWidget("Library", self)
        lib_dock.setWidget(self.library)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, lib_dock)

        self.mosaic_panel = MosaicPanel()
        self.generative_panel = GenerativePanel()
        self.freeform_panel = FreeformPanel()
        self.modes = QTabWidget()
        self.modes.addTab(self.mosaic_panel, "Mosaic")
        self.modes.addTab(self.generative_panel, "Generative")
        self.modes.addTab(self.freeform_panel, "Freeform")
        modes_dock = QDockWidget("Art modes", self)
        modes_dock.setWidget(self.modes)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, modes_dock)

        self.layers = LayersPanel()
        self.layers.set_project(self.project)
        layers_dock = QDockWidget("Layers", self)
        layers_dock.setWidget(self.layers)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, layers_dock)

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        self._add_action(file_menu, "New", self.new_project, QKeySequence.StandardKey.New)
        self._add_action(file_menu, "Open…", self.open_project, QKeySequence.StandardKey.Open)
        self._add_action(file_menu, "Save", self.save_project, QKeySequence.StandardKey.Save)
        self._add_action(file_menu, "Save As…", self.save_project_as)
        file_menu.addSeparator()
        self._add_action(file_menu, "Export image…", self.export_image, QKeySequence("Ctrl+E"))
        file_menu.addSeparator()
        self._add_action(file_menu, "Quit", self.close, QKeySequence.StandardKey.Quit)

        lib_menu = bar.addMenu("&Library")
        self._add_action(lib_menu, "Add folder…", self.library._choose_folder)

        view_menu = bar.addMenu("&View")
        self._add_action(view_menu, "Fit canvas", self.canvas.fit_page, QKeySequence("Ctrl+0"))

    def _add_action(self, menu, text, slot, shortcut=None) -> None:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut is not None:
            action.setShortcut(shortcut)
        menu.addAction(action)

    def _build_statusbar(self) -> None:
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("Add a folder of images to begin.")

    def _wire(self) -> None:
        self.library.ingestFolderRequested.connect(self.ingest_folder)
        self.library.imageActivated.connect(self.add_image_layer)

        self.mosaic_panel.generateRequested.connect(self.run_generator)
        self.generative_panel.generateRequested.connect(self.run_generator)
        self.freeform_panel.generateRequested.connect(self.run_generator)

        self.canvas.selectionChangedTo.connect(self.layers.set_selected)
        self.canvas.layerGeometryChanged.connect(self.layers.set_selected)

        self.layers.layerSelected.connect(self.canvas.select_layer)
        self.layers.layerChanged.connect(self.canvas.refresh_layer)
        self.layers.moveRequested.connect(self._move_layer)
        self.layers.deleteRequested.connect(self._delete_layer)

    # -- progress helpers ---------------------------------------------------

    def _begin_task(self, message: str) -> None:
        self.statusBar().showMessage(message)
        self.progress.setRange(0, 0)  # indeterminate until first progress tick
        self.progress.setVisible(True)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)

    def _end_task(self, message: str) -> None:
        self.progress.setVisible(False)
        self.statusBar().showMessage(message, 5000)

    def _on_error(self, message: str) -> None:
        self.progress.setVisible(False)
        self.statusBar().showMessage("Error", 5000)
        QMessageBox.warning(self, "Something went wrong", message)

    # -- library ------------------------------------------------------------

    def ingest_folder(self, folder: str) -> None:
        self._begin_task(f"Indexing {folder} …")
        run_async(
            ingest_images,
            [folder],
            self.catalog,
            with_progress=True,
            on_progress=self._on_progress,
            on_done=self._ingest_done,
            on_error=self._on_error,
        )

    def _ingest_done(self, processed: int) -> None:
        self.library.reload()
        self._end_task(f"Indexed {processed} new image(s); {self.catalog.count()} total.")

    # -- adding layers ------------------------------------------------------

    def add_image_layer(self, path: str) -> None:
        try:
            with Image.open(path) as im:
                w, h = im.size
        except OSError:
            return
        short = min(self.project.width, self.project.height)
        scale = (short * 0.4) / max(w, h) if max(w, h) else 1.0
        layer = Layer(
            name=Path(path).name,
            path=path,
            transform=Transform(
                cx=self.project.width / 2.0, cy=self.project.height / 2.0, scale=scale
            ),
        )
        self.project.add_layer(layer)
        self._refresh_all()
        self.canvas.select_layer(layer.id)

    def _add_composite_layer(self, name: str, image: Image.Image) -> None:
        first = len(self.project.layers) == 0
        if first:
            self.project.width, self.project.height = image.size
        layer = Layer(
            name=name,
            transform=Transform(
                cx=self.project.width / 2.0, cy=self.project.height / 2.0
            ),
        )
        layer.set_image(image)
        self.project.add_layer(layer, on_top=True)
        if first:
            self.canvas.set_project(self.project)  # picks up new canvas size + fits
            self.layers.reload()
        else:
            self._refresh_all()

    # -- generators ---------------------------------------------------------

    def run_generator(self, params: dict) -> None:
        records, features = self.catalog.feature_matrix()
        if not records:
            QMessageBox.information(
                self, "No images", "Add a folder of images to the library first."
            )
            return
        mode = params["mode"]
        if mode == "mosaic":
            self._run_mosaic(params, records, features)
        elif mode in ("color_sort", "embedding"):
            self._run_generative(params, records, features)
        elif mode == "freeform":
            self._run_freeform(params, records)

    def _run_mosaic(self, params: dict, records, features) -> None:
        target_path = params.get("target_path")
        if not target_path:
            QMessageBox.information(self, "No target", "Choose a target image first.")
            return
        options = mosaic.MosaicOptions(
            cols=params["cols"],
            tile_px=params["tile_px"],
            tint=params["tint"],
            max_uses=params["max_uses"],
        )

        def task(progress=None):
            target = image_ops.load_image(target_path, mode="RGB")
            return mosaic.build_mosaic(target, records, features, options, progress=progress)

        self._begin_task("Building mosaic …")
        run_async(
            task,
            with_progress=True,
            on_progress=self._on_progress,
            on_done=lambda img: (
                self._add_composite_layer("Mosaic", img),
                self._end_task("Mosaic ready."),
            ),
            on_error=self._on_error,
        )

    def _run_generative(self, params: dict, records, features) -> None:
        cols, tile_px = params["cols"], params["tile_px"]
        if params["mode"] == "color_sort":
            key = params["key"]

            def task(progress=None):
                return generative.color_sort_layout(
                    records, cols=cols, tile_px=tile_px, key=key, progress=progress
                )

            name = f"Colour sort ({params['key']})"
        else:
            method = params["method"]

            def task(progress=None):
                return generative.embedding_layout(
                    records, features, cols=cols, tile_px=tile_px, method=method, progress=progress
                )

            name = f"Embedding ({params['method']})"

        self._begin_task("Building layout …")
        run_async(
            task,
            with_progress=True,
            on_progress=self._on_progress,
            on_done=lambda img: (
                self._add_composite_layer(name, img),
                self._end_task("Layout ready."),
            ),
            on_error=self._on_error,
        )

    def _run_freeform(self, params: dict, records) -> None:
        layers = freeform.scatter(
            records,
            self.project.size,
            count=params["count"],
            size_frac=params["size_frac"],
            rotation_jitter=params["rotation_jitter"],
            blend_modes=params["blend_modes"],
        )
        for layer in layers:
            self.project.add_layer(layer)
        self._refresh_all()
        self._end_task(f"Scattered {len(layers)} images.")

    # -- layer ops ----------------------------------------------------------

    def _move_layer(self, layer_id: str, delta: int) -> None:
        self.project.move(layer_id, delta)
        self._refresh_all()
        self.canvas.select_layer(layer_id)

    def _delete_layer(self, layer_id: str) -> None:
        self.project.remove_layer(layer_id)
        self._refresh_all()

    def _refresh_all(self) -> None:
        self.canvas.rebuild()
        self.layers.reload()

    # -- file ---------------------------------------------------------------

    def new_project(self) -> None:
        self.project = Project(width=_DEFAULT_W, height=_DEFAULT_H)
        self.canvas.set_project(self.project)
        self.layers.set_project(self.project)
        self.statusBar().showMessage("New project.", 3000)

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "collajit project (*.collajit.json *.json)"
        )
        if not path:
            return
        try:
            self.project = Project.load(path)
        except (OSError, ValueError) as exc:
            self._on_error(str(exc))
            return
        self.canvas.set_project(self.project)
        self.layers.set_project(self.project)
        self.setWindowTitle(f"collajit — {Path(path).name}")

    def save_project(self) -> None:
        if self.project.path:
            self.project.save(self.project.path)
            self.statusBar().showMessage("Saved.", 3000)
        else:
            self.save_project_as()

    def save_project_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", "untitled.collajit.json", "collajit project (*.collajit.json)"
        )
        if not path:
            return
        self.project.save(path)
        self.setWindowTitle(f"collajit — {Path(path).name}")
        self.statusBar().showMessage("Saved.", 3000)

    def export_image(self) -> None:
        if not self.project.layers:
            QMessageBox.information(self, "Nothing to export", "The canvas is empty.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export image", "collage.png", "PNG (*.png);;JPEG (*.jpg *.jpeg)"
        )
        if not path:
            return
        self._begin_task("Exporting …")
        run_async(
            self.project.export,
            path,
            on_done=lambda _r: self._end_task(f"Exported {Path(path).name}."),
            on_error=self._on_error,
        )
