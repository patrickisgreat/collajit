"""Freeform collage: scatter library images across the canvas as editable layers.

Unlike mosaic/generative (which return one baked image), this returns a list of
:class:`~collajit.model.layer.Layer` backed by the original full-resolution files,
so each piece can be dragged, scaled, rotated and re-blended in the editor.
"""

from __future__ import annotations

import numpy as np

from ..engine.compositor import BLEND_MODES
from ..library.catalog import ImageRecord
from ..model.layer import Layer, Transform


def scatter(
    records: list[ImageRecord],
    canvas_size: tuple[int, int],
    *,
    count: int = 30,
    size_frac: tuple[float, float] = (0.2, 0.5),
    rotation_jitter: float = 25.0,
    opacity_range: tuple[float, float] = (0.85, 1.0),
    blend_modes: tuple[str, ...] = ("normal",),
    seed: int | None = None,
) -> list[Layer]:
    """Create ``count`` randomly placed layers sampled from ``records``.

    ``size_frac`` is each layer's longest side as a fraction of the canvas's
    shorter side. ``blend_modes`` is the pool to randomly draw from (must be a
    subset of :data:`~collajit.engine.compositor.BLEND_MODES`).
    """
    if not records:
        raise ValueError("scatter needs a non-empty image library")
    bad = set(blend_modes) - set(BLEND_MODES)
    if bad:
        raise ValueError(f"unknown blend modes: {sorted(bad)}")

    rng = np.random.default_rng(seed)
    w, h = canvas_size
    short = min(w, h)
    n_src = len(records)

    layers: list[Layer] = []
    for i in range(count):
        rec = records[int(rng.integers(0, n_src))]
        frac = rng.uniform(*size_frac)
        long_side = max(rec.width, rec.height)
        scale = (short * frac) / long_side if long_side else 1.0
        layer = Layer(
            name=f"Scatter {i + 1}",
            path=rec.path,
            transform=Transform(
                cx=float(rng.uniform(0, w)),
                cy=float(rng.uniform(0, h)),
                scale=float(scale),
                rotation=float(rng.uniform(-rotation_jitter, rotation_jitter)),
            ),
            opacity=float(rng.uniform(*opacity_range)),
            blend=str(rng.choice(blend_modes)),
        )
        layers.append(layer)
    return layers
