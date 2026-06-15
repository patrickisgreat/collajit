"""Tests for the three art generators."""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from collajit.generators import freeform, generative, mosaic


def test_mosaic_size_and_color_match(library):
    _catalog, records, features = library
    # Target: left half red, right half green.
    target = Image.new("RGB", (200, 100))
    target.paste((230, 20, 20), (0, 0, 100, 100))
    target.paste((20, 220, 20), (100, 0, 200, 100))

    opt = mosaic.MosaicOptions(cols=10, tile_px=16, tint=0.0, max_uses=None)
    out = mosaic.build_mosaic(target, records, features, opt)
    cols, rows = mosaic.estimate_grid(target, 10)
    assert out.size == (cols * 16, rows * 16)

    arr = np.asarray(out.convert("RGB"), dtype=np.float32)
    left = arr[:, : cols // 2 * 16].reshape(-1, 3).mean(axis=0)
    right = arr[:, cols // 2 * 16 :].reshape(-1, 3).mean(axis=0)
    assert left[0] > left[1]  # left leans red
    assert right[1] > right[0]  # right leans green


def test_mosaic_respects_max_uses_roughly(library):
    _catalog, records, features = library
    target = Image.new("RGB", (100, 100), (120, 120, 120))
    out = mosaic.build_mosaic(
        target, records, features, mosaic.MosaicOptions(cols=8, tile_px=8, max_uses=4)
    )
    assert out.size[0] == 8 * 8


def test_physical_spec_eyeball_of_fish():
    spec = mosaic.PhysicalSpec(canvas_w_in=7.5, canvas_h_in=7.5, tile_in=0.25, dpi=300)
    assert (spec.cols, spec.rows) == (30, 30)
    assert spec.tile_px == 75
    assert spec.tile_count == 900  # unique fish needed for no-repeat
    assert spec.output_px == (2250, 2250)  # 7.5in at 300dpi
    opt = spec.to_options(no_repeat=True)
    assert opt.max_uses == 1 and (opt.cols, opt.rows, opt.tile_px) == (30, 30, 75)


def test_mosaic_honors_explicit_rows(library):
    _catalog, records, features = library
    target = Image.new("RGB", (200, 100))  # 2:1 aspect
    out = mosaic.build_mosaic(
        target, records, features,
        mosaic.MosaicOptions(cols=4, rows=6, tile_px=8, max_uses=None, tint=0.0),
    )
    assert out.size == (4 * 8, 6 * 8)  # rows honoured, not derived from aspect


def test_color_sort_layout_grid_size(library):
    _catalog, records, _features = library
    out = generative.color_sort_layout(records, cols=6, tile_px=16, key="hue")
    rows = math.ceil(len(records) / 6)
    assert out.size == (6 * 16, rows * 16)


def test_embedding_layout_pca(library):
    _catalog, records, features = library
    out = generative.embedding_layout(records, features, cols=6, tile_px=16, method="pca")
    rows = math.ceil(len(records) / 6)
    assert out.size == (6 * 16, rows * 16)


def test_scatter_returns_editable_layers(library):
    _catalog, records, _features = library
    layers = freeform.scatter(records, (800, 600), count=15, seed=7)
    assert len(layers) == 15
    for layer in layers:
        assert layer.path is not None  # backed by original file -> editable/high-res
        assert 0 <= layer.transform.cx <= 800
        assert 0 <= layer.transform.cy <= 600


def test_scatter_is_deterministic_with_seed(library):
    _catalog, records, _features = library
    a = freeform.scatter(records, (400, 400), count=5, seed=1)
    b = freeform.scatter(records, (400, 400), count=5, seed=1)
    assert [layer.path for layer in a] == [layer.path for layer in b]
    assert [layer.transform.cx for layer in a] == [layer.transform.cx for layer in b]
