"""Offscreen smoke tests: the window boots and the synchronous editor paths work.

Async generators (mosaic/generative) are covered headlessly in test_generators;
here we exercise wiring that doesn't depend on the thread pool: booting, adding a
library image as a layer, freeform scatter, compositing a generated layer, export.
"""

from __future__ import annotations

import os

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from collajit.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_window_boots_and_paths_work(qapp, library, tmp_path):
    catalog, records, _features = library
    win = MainWindow(catalog)
    try:
        assert win.project.layers == []

        # Library activation -> one editable, path-backed layer + a canvas item.
        win.add_image_layer(records[0].path)
        assert len(win.project.layers) == 1
        assert len(win.canvas._items) == 1

        # Freeform scatter (synchronous path) adds N layers.
        win.run_generator(
            {
                "mode": "freeform",
                "count": 8,
                "size_frac": (0.2, 0.4),
                "rotation_jitter": 20.0,
                "blend_modes": ("normal",),
            }
        )
        assert len(win.project.layers) == 9
        assert len(win.canvas._items) == 9

        # A generated composite becomes the bottom-up first layer when empty...
        win.new_project()
        win._add_composite_layer("Mosaic", Image.new("RGBA", (300, 200), (10, 20, 30, 255)))
        assert win.project.size == (300, 200)  # canvas adopts composite size
        assert len(win.project.layers) == 1

        # Export renders through the compositor.
        out = tmp_path / "smoke.png"
        win.project.export(out)
        assert out.exists()
    finally:
        win.close()


def test_layer_delete_and_reorder_via_controller(qapp, library):
    catalog, records, _features = library
    win = MainWindow(catalog)
    try:
        win.add_image_layer(records[0].path)
        win.add_image_layer(records[1].path)
        first_id = win.project.layers[0].id
        win._move_layer(first_id, +1)
        assert win.project.layers[1].id == first_id
        win._delete_layer(first_id)
        assert all(layer.id != first_id for layer in win.project.layers)
    finally:
        win.close()
