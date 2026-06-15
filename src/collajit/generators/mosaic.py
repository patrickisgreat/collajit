"""Photo mosaic: reconstruct a target image from many small source tiles.

The target is divided into a grid. Each cell is described with the same feature
vector the catalog stores for source images, then matched to the best (and, with
``max_uses``, sufficiently un-reused) source. Tiles are optionally tinted toward
their cell's colour, which tightens the illusion at a glance while keeping each
photo recognisable up close.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PIL import Image

from ..engine import image_ops
from ..engine.features import FEATURE_DIM, extract_features
from ..engine.matcher import FeatureMatcher
from ..library.catalog import ImageRecord

ProgressCb = Callable[[int, int], None]


@dataclass
class MosaicOptions:
    cols: int = 60  # tiles across the target
    tile_px: int = 48  # rendered pixel size of each square tile
    tint: float = 0.25  # 0 = untouched tiles, 1 = flat colour
    max_uses: int | None = 8  # cap how often any one source repeats (None = unlimited)
    sample_edge: int = 32  # working size used to feature each target cell
    rows: int | None = None  # explicit row count; None = derive from target aspect


@dataclass
class PhysicalSpec:
    """A print-size mosaic request expressed in inches.

    e.g. a 7.5x7.5 in canvas with 0.25 in tiles at 300 DPI -> 30x30 = 900 tiles,
    each 75px, output 2250x2250px.
    """

    canvas_w_in: float
    canvas_h_in: float
    tile_in: float
    dpi: int = 300

    @property
    def cols(self) -> int:
        return max(1, round(self.canvas_w_in / self.tile_in))

    @property
    def rows(self) -> int:
        return max(1, round(self.canvas_h_in / self.tile_in))

    @property
    def tile_px(self) -> int:
        return max(1, round(self.tile_in * self.dpi))

    @property
    def tile_count(self) -> int:
        """Tiles needed — and, for a no-repeat mosaic, unique images required."""
        return self.cols * self.rows

    @property
    def output_px(self) -> tuple[int, int]:
        return (self.cols * self.tile_px, self.rows * self.tile_px)

    def to_options(self, *, tint: float = 0.25, no_repeat: bool = True) -> MosaicOptions:
        return MosaicOptions(
            cols=self.cols,
            rows=self.rows,
            tile_px=self.tile_px,
            tint=tint,
            max_uses=1 if no_repeat else None,
        )


def _feature_weights() -> np.ndarray:
    """Emphasise mean colour, then coarse layout, then histogram."""
    w = np.ones(FEATURE_DIM, dtype=np.float32)
    w[0:3] = 3.0  # mean RGB dominates the match
    w[3:51] = 1.5  # 4x4 grid means (spatial colour)
    # remaining dims (HSV histogram) keep weight 1.0
    return w


def build_mosaic(
    target: Image.Image,
    records: list[ImageRecord],
    features: np.ndarray,
    options: MosaicOptions | None = None,
    *,
    progress: ProgressCb | None = None,
) -> Image.Image:
    """Build and return the mosaic as an RGBA :class:`PIL.Image.Image`."""
    if not records:
        raise ValueError("mosaic needs a non-empty image library")
    opt = options or MosaicOptions()
    cols = max(1, opt.cols)

    target = target.convert("RGB")
    aspect = target.width / target.height
    rows = opt.rows if opt.rows else max(1, round(cols / aspect))

    # Per-cell target features, computed from a downscaled copy of the target so
    # cropping each cell is cheap.
    sample = target.resize((cols * opt.sample_edge, rows * opt.sample_edge), Image.LANCZOS)
    sample_arr = np.asarray(sample, dtype=np.uint8)
    e = opt.sample_edge
    cell_features = np.empty((rows * cols, FEATURE_DIM), dtype=np.float32)
    for r in range(rows):
        for c in range(cols):
            cell = sample_arr[r * e : (r + 1) * e, c * e : (c + 1) * e]
            cell_features[r * cols + c] = extract_features(Image.fromarray(cell))

    matcher = FeatureMatcher(features, weights=_feature_weights())
    assigned = matcher.assign_diverse(cell_features, max_uses=opt.max_uses)

    out_w, out_h = cols * opt.tile_px, rows * opt.tile_px
    canvas = Image.new("RGBA", (out_w, out_h))
    tile_cache: dict[int, Image.Image] = {}
    total = rows * cols

    for cell_idx in range(total):
        src_idx = int(assigned[cell_idx])
        tile = tile_cache.get(src_idx)
        if tile is None:
            src_img = image_ops.load_image(records[src_idx].thumb_path, mode="RGB")
            tile = image_ops.fit_tile(src_img, (opt.tile_px, opt.tile_px))
            tile_cache[src_idx] = tile

        if opt.tint > 0:
            target_rgb = cell_features[cell_idx, 0:3]
            arr = image_ops.tint_toward(image_ops.to_float(tile), target_rgb, opt.tint)
            placed = image_ops.to_pil(arr)
        else:
            placed = tile.convert("RGBA")

        r, c = divmod(cell_idx, cols)
        canvas.paste(placed, (c * opt.tile_px, r * opt.tile_px))
        if progress is not None and cell_idx % 32 == 0:
            progress(cell_idx + 1, total)

    if progress is not None:
        progress(total, total)
    return canvas


def estimate_grid(target: Image.Image, cols: int) -> tuple[int, int]:
    """Return ``(cols, rows)`` the mosaic would use for ``target`` at ``cols``."""
    cols = max(1, cols)
    rows = max(1, math.ceil(cols / (target.width / target.height)))
    return cols, rows
