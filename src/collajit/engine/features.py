"""Per-image feature extraction.

Each image is reduced to a compact float vector so that thousands of them can be
matched and clustered cheaply. The vector concatenates:

* mean RGB (3) — the dominant signal for mosaic tile matching,
* a coarse 4x4 grid of mean RGB (48) — captures rough spatial layout so a tile
  with a bright corner can match a region with a bright corner,
* an HSV histogram (a few bins each, normalised) — captures colour distribution.

The layout is fixed and versioned by :data:`FEATURE_VERSION` so a cached catalog
can be invalidated if the schema changes.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

FEATURE_VERSION = 1

_GRID = 4  # 4x4 spatial grid
_H_BINS = 8
_S_BINS = 4
_V_BINS = 4

#: Total length of the vector produced by :func:`extract_features`.
FEATURE_DIM = 3 + (_GRID * _GRID * 3) + (_H_BINS + _S_BINS + _V_BINS)


def mean_rgb(img: Image.Image) -> np.ndarray:
    """Average colour of ``img`` as an RGB float vector in ``[0, 1]``."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    return arr.reshape(-1, 3).mean(axis=0)


def _grid_means(arr: np.ndarray) -> np.ndarray:
    """Mean RGB of each cell in a ``_GRID x _GRID`` partition, flattened."""
    h, w, _ = arr.shape
    ys = np.linspace(0, h, _GRID + 1, dtype=int)
    xs = np.linspace(0, w, _GRID + 1, dtype=int)
    cells = []
    for i in range(_GRID):
        for j in range(_GRID):
            cell = arr[ys[i] : ys[i + 1], xs[j] : xs[j + 1]]
            cells.append(cell.reshape(-1, 3).mean(axis=0) if cell.size else np.zeros(3))
    return np.concatenate(cells).astype(np.float32)


def _hsv_histogram(img: Image.Image) -> np.ndarray:
    hsv = np.asarray(img.convert("HSV"), dtype=np.float32) / 255.0
    h, s, v = hsv[..., 0].ravel(), hsv[..., 1].ravel(), hsv[..., 2].ravel()
    hist_h, _ = np.histogram(h, bins=_H_BINS, range=(0, 1))
    hist_s, _ = np.histogram(s, bins=_S_BINS, range=(0, 1))
    hist_v, _ = np.histogram(v, bins=_V_BINS, range=(0, 1))
    hist = np.concatenate([hist_h, hist_s, hist_v]).astype(np.float32)
    total = hist.sum()
    return hist / total if total else hist


def extract_features(img: Image.Image) -> np.ndarray:
    """Compute the full feature vector for ``img`` (length :data:`FEATURE_DIM`)."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    parts = [
        rgb.reshape(-1, 3).mean(axis=0),
        _grid_means(rgb),
        _hsv_histogram(img),
    ]
    vec = np.concatenate(parts).astype(np.float32)
    assert vec.shape[0] == FEATURE_DIM, (vec.shape[0], FEATURE_DIM)
    return vec
