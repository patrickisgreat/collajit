"""Tests for the headless engine: features, compositor, matcher."""

from __future__ import annotations

import numpy as np
from PIL import Image

from collajit.engine import compositor, image_ops
from collajit.engine.features import FEATURE_DIM, extract_features, mean_rgb
from collajit.engine.matcher import FeatureMatcher


def test_feature_dim_and_mean_color():
    img = Image.new("RGB", (32, 32), (255, 0, 0))
    feat = extract_features(img)
    assert feat.shape == (FEATURE_DIM,)
    assert np.allclose(mean_rgb(img), [1.0, 0.0, 0.0], atol=1e-3)
    assert np.allclose(feat[0:3], [1.0, 0.0, 0.0], atol=1e-3)


def test_fit_tile_exact_size_and_cover():
    img = Image.new("RGB", (200, 100), (10, 20, 30))
    tile = image_ops.fit_tile(img, (50, 50))
    assert tile.size == (50, 50)


def test_composite_normal_over_opaque():
    red = np.zeros((4, 4, 4), dtype=np.float32)
    red[..., 0] = 1.0
    red[..., 3] = 1.0
    blue = np.zeros((4, 4, 4), dtype=np.float32)
    blue[..., 2] = 1.0
    blue[..., 3] = 1.0
    layers = [
        compositor.PlacedLayer(red, 0, 0),
        compositor.PlacedLayer(blue, 0, 0),
    ]
    out = compositor.composite(layers, (4, 4))
    # Top (blue) fully covers bottom (red).
    assert np.allclose(out[0, 0], [0.0, 0.0, 1.0, 1.0], atol=1e-4)


def test_composite_opacity_halfway():
    base = np.zeros((2, 2, 4), dtype=np.float32)
    base[..., 3] = 1.0  # black opaque
    white = np.ones((2, 2, 4), dtype=np.float32)
    layers = [
        compositor.PlacedLayer(base, 0, 0),
        compositor.PlacedLayer(white, 0, 0, opacity=0.5),
    ]
    out = compositor.composite(layers, (2, 2))
    assert np.allclose(out[0, 0, :3], [0.5, 0.5, 0.5], atol=1e-3)


def test_composite_multiply_blend():
    grey = np.full((2, 2, 4), 0.5, dtype=np.float32)
    grey[..., 3] = 1.0
    other = np.full((2, 2, 4), 0.4, dtype=np.float32)
    other[..., 3] = 1.0  # fully opaque so the blend isn't diluted by src alpha
    layers = [
        compositor.PlacedLayer(grey, 0, 0),
        compositor.PlacedLayer(other, 0, 0, blend="multiply"),
    ]
    out = compositor.composite(layers, (2, 2))
    assert np.allclose(out[0, 0, :3], [0.2, 0.2, 0.2], atol=1e-3)


def test_composite_offscreen_placement_clips():
    canvas_layer = np.zeros((2, 2, 4), dtype=np.float32)
    canvas_layer[..., 3] = 1.0
    small = np.ones((2, 2, 4), dtype=np.float32)
    # Place so only its bottom-right pixel lands on the canvas at (0,0).
    out = compositor.composite(
        [compositor.PlacedLayer(canvas_layer, 0, 0), compositor.PlacedLayer(small, -1, -1)],
        (2, 2),
    )
    assert np.allclose(out[0, 0, :3], [1.0, 1.0, 1.0], atol=1e-3)  # covered corner
    assert np.allclose(out[1, 1, :3], [0.0, 0.0, 0.0], atol=1e-3)  # untouched


def test_rasterize_centers_layer():
    img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    placed = compositor.rasterize(
        img, canvas_size=(100, 100), cx=50, cy=50, scale=1.0, rotation_deg=0.0
    )
    assert placed.x == 45 and placed.y == 45


def test_matcher_query_and_diversity():
    feats = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    m = FeatureMatcher(feats)
    idx = m.query(np.array([[0.9, 0.1, 0.0]]), k=1)
    assert idx[0, 0] == 1

    targets = np.tile([1.0, 0.0, 0.0], (4, 1)).astype(np.float32)
    assigned = m.assign_diverse(targets, max_uses=1, candidates=3)
    # With max_uses=1 the four identical targets must spread across sources.
    assert len(set(assigned.tolist())) >= 3
