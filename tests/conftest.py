"""Shared fixtures: a synthetic image library ingested into a temp catalog."""

from __future__ import annotations

import colorsys

import numpy as np
import pytest
from PIL import Image

from collajit.library import Catalog, ingest


def _solid(rgb: tuple[int, int, int], size: int = 64) -> Image.Image:
    return Image.new("RGB", (size, size), rgb)


@pytest.fixture
def image_dir(tmp_path):
    """A folder of 24 solid hue-wheel images plus a couple of gradients."""
    d = tmp_path / "images"
    d.mkdir()
    for i in range(24):
        h = i / 24.0
        r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(h, 0.9, 0.9))
        _solid((r, g, b)).save(d / f"hue_{i:02d}.png")

    grad = np.linspace(0, 255, 64, dtype=np.uint8)
    Image.fromarray(np.tile(grad, (64, 1))).convert("RGB").save(d / "grad_x.png")
    Image.fromarray(np.tile(grad[:, None], (1, 64))).convert("RGB").save(d / "grad_y.png")
    return d


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """An isolated catalog under a temp COLLAJIT_HOME."""
    monkeypatch.setenv("COLLAJIT_HOME", str(tmp_path / "home"))
    cat = Catalog(db_path=tmp_path / "home" / "catalog.db")
    yield cat
    cat.close()


@pytest.fixture
def library(image_dir, catalog):
    """Ingest ``image_dir`` and return ``(catalog, records, features)``."""
    ingest([image_dir], catalog)
    records, features = catalog.feature_matrix()
    return catalog, records, features
