"""Layer compositor: blend a stack of placed RGBA layers into one image.

This is the single rendering path shared by all three art modes and by export.
Layers are *placed* — already scaled and rotated to their final pixel size — so
the compositor only has to blend and paste. Turning a high-level
:class:`~collajit.model.layer.Layer` (source + transform) into a
:class:`PlacedLayer` happens in :func:`rasterize`, keeping the blend math here
trivially testable.

Blend modes follow the separable W3C compositing spec so partially-transparent
layers blend the way a designer expects.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from . import image_ops

BLEND_MODES = (
    "normal",
    "multiply",
    "screen",
    "overlay",
    "darken",
    "lighten",
    "add",
    "difference",
)


def _blend_rgb(dst: np.ndarray, src: np.ndarray, mode: str) -> np.ndarray:
    if mode == "normal":
        return src
    if mode == "multiply":
        return dst * src
    if mode == "screen":
        return 1.0 - (1.0 - dst) * (1.0 - src)
    if mode == "overlay":
        return np.where(dst < 0.5, 2 * dst * src, 1.0 - 2 * (1.0 - dst) * (1.0 - src))
    if mode == "darken":
        return np.minimum(dst, src)
    if mode == "lighten":
        return np.maximum(dst, src)
    if mode == "add":
        return np.clip(dst + src, 0.0, 1.0)
    if mode == "difference":
        return np.abs(dst - src)
    raise ValueError(f"unknown blend mode: {mode!r}")


@dataclass
class PlacedLayer:
    """An RGBA layer already sized/rotated, ready to paste at ``(x, y)``."""

    rgba: np.ndarray  # (h, w, 4) float in [0, 1]
    x: int  # top-left position in the canvas
    y: int
    opacity: float = 1.0
    blend: str = "normal"
    visible: bool = True


def composite(
    layers: list[PlacedLayer],
    size: tuple[int, int],
    *,
    background: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> np.ndarray:
    """Render ``layers`` (bottom-first) onto a ``size = (W, H)`` canvas.

    Returns a ``(H, W, 4)`` float RGBA array in ``[0, 1]``.
    """
    w, h = size
    canvas = np.empty((h, w, 4), dtype=np.float32)
    canvas[..., :] = background

    for layer in layers:
        if not layer.visible or layer.opacity <= 0.0:
            continue
        _blend_onto(canvas, layer)
    return canvas


def _blend_onto(canvas: np.ndarray, layer: PlacedLayer) -> None:
    H, W, _ = canvas.shape
    lh, lw, _ = layer.rgba.shape

    # Intersection of the layer rect with the canvas rect.
    x0, y0 = layer.x, layer.y
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(W, x0 + lw), min(H, y0 + lh)
    if cx0 >= cx1 or cy0 >= cy1:
        return  # fully off-canvas

    src = layer.rgba[cy0 - y0 : cy1 - y0, cx0 - x0 : cx1 - x0]
    dst = canvas[cy0:cy1, cx0:cx1]

    src_rgb = src[..., :3]
    dst_rgb = dst[..., :3]
    sa = src[..., 3:4] * float(layer.opacity)
    da = dst[..., 3:4]

    blended = _blend_rgb(dst_rgb, src_rgb, layer.blend)
    out_a = sa + da * (1.0 - sa)
    safe_a = np.where(out_a > 1e-6, out_a, 1.0)
    out_rgb = (
        sa * (1.0 - da) * src_rgb + sa * da * blended + (1.0 - sa) * da * dst_rgb
    ) / safe_a

    dst[..., :3] = np.where(out_a > 1e-6, out_rgb, dst_rgb)
    dst[..., 3:4] = out_a


def rasterize(
    img: Image.Image,
    *,
    canvas_size: tuple[int, int],
    cx: float,
    cy: float,
    scale: float,
    rotation_deg: float,
    opacity: float = 1.0,
    blend: str = "normal",
    visible: bool = True,
) -> PlacedLayer:
    """Scale + rotate ``img`` about its centre and place it at canvas point ``(cx, cy)``.

    ``cx, cy`` are the desired centre of the layer in canvas pixels. Rotation
    expands the bounding box (no clipping). Returns a :class:`PlacedLayer`.
    """
    img = img.convert("RGBA")
    w, h = img.size
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    if (new_w, new_h) != (w, h):
        img = img.resize((new_w, new_h), Image.LANCZOS)
    if rotation_deg:
        img = img.rotate(rotation_deg, expand=True, resample=Image.BICUBIC)

    rgba = image_ops.to_float(img)
    rh, rw, _ = rgba.shape
    x = int(round(cx - rw / 2.0))
    y = int(round(cy - rh / 2.0))
    return PlacedLayer(
        rgba=rgba, x=x, y=y, opacity=opacity, blend=blend, visible=visible
    )
