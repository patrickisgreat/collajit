"""Generative / algorithmic layouts: arrange a whole library into one image.

Two families:

* **colour sort** — order every image by hue/brightness and lay them out in a grid.
  Produces clean colour gradients across the canvas.
* **embedding** — project the feature vectors to 2-D (PCA or t-SNE) so visually
  similar images land near each other, then snap that cloud to a tidy grid with a
  fast band assignment (sort into ``rows`` horizontal bands, order each by x).
"""

from __future__ import annotations

import colorsys
import math
from collections.abc import Callable

import numpy as np
from PIL import Image

from ..engine import image_ops
from ..library.catalog import ImageRecord

ProgressCb = Callable[[int, int], None]

SORT_KEYS = ("hue", "brightness", "darkness")
EMBED_METHODS = ("pca", "tsne")


def _sort_key(rec: ImageRecord, key: str) -> float:
    r, g, b = (float(x) for x in rec.feature[0:3])
    h, _s, v = colorsys.rgb_to_hsv(r, g, b)
    if key == "hue":
        return h
    if key == "brightness":
        return -v
    if key == "darkness":
        return v
    return h


def _grid_dims(n: int, cols: int) -> tuple[int, int]:
    cols = max(1, cols)
    rows = max(1, math.ceil(n / cols))
    return cols, rows


def _paste_grid(
    ordered: list[ImageRecord],
    cols: int,
    rows: int,
    tile_px: int,
    progress: ProgressCb | None,
) -> Image.Image:
    canvas = Image.new("RGBA", (cols * tile_px, rows * tile_px), (0, 0, 0, 0))
    total = len(ordered)
    for i, rec in enumerate(ordered):
        try:
            tile = image_ops.load_image(rec.thumb_path, mode="RGB")
        except OSError:
            continue
        tile = image_ops.fit_tile(tile, (tile_px, tile_px))
        r, c = divmod(i, cols)
        canvas.paste(tile.convert("RGBA"), (c * tile_px, r * tile_px))
        if progress is not None and i % 32 == 0:
            progress(i + 1, total)
    if progress is not None:
        progress(total, total)
    return canvas


def color_sort_layout(
    records: list[ImageRecord],
    *,
    cols: int = 40,
    tile_px: int = 64,
    key: str = "hue",
    progress: ProgressCb | None = None,
) -> Image.Image:
    """Lay images out in a grid ordered by ``key`` (see :data:`SORT_KEYS`)."""
    if not records:
        raise ValueError("layout needs a non-empty image library")
    ordered = sorted(records, key=lambda r: _sort_key(r, key))
    cols, rows = _grid_dims(len(ordered), cols)
    return _paste_grid(ordered, cols, rows, tile_px, progress)


def _embed_2d(features: np.ndarray, method: str) -> np.ndarray:
    """Project ``(N, D)`` features to ``(N, 2)``."""
    if method == "tsne":
        from sklearn.manifold import TSNE

        n = features.shape[0]
        perplexity = float(min(30, max(5, n // 4)))
        return TSNE(
            n_components=2, perplexity=perplexity, init="pca", random_state=0
        ).fit_transform(features)
    from sklearn.decomposition import PCA

    return PCA(n_components=2, random_state=0).fit_transform(features)


def embedding_layout(
    records: list[ImageRecord],
    features: np.ndarray,
    *,
    cols: int = 40,
    tile_px: int = 64,
    method: str = "pca",
    progress: ProgressCb | None = None,
) -> Image.Image:
    """Embed features to 2-D, snap to a grid, and render.

    The band snap: sort all points by y into ``rows`` bands of ~``cols`` points,
    then order each band by x. Cheap (O(n log n)) and gives a grid that preserves
    the embedding's broad structure without solving full assignment.
    """
    if not records:
        raise ValueError("layout needs a non-empty image library")
    coords = _embed_2d(features, method)
    n = len(records)
    cols, rows = _grid_dims(n, cols)

    by_y = np.argsort(coords[:, 1])
    ordered: list[ImageRecord] = []
    for r in range(rows):
        band = by_y[r * cols : (r + 1) * cols]
        band = band[np.argsort(coords[band, 0])]  # within band, left -> right
        ordered.extend(records[i] for i in band)
    return _paste_grid(ordered, cols, rows, tile_px, progress)
