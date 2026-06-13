"""Low-level image helpers shared by the generators and compositor.

Everything works in terms of float RGBA arrays in ``[0, 1]`` (shape ``(H, W, 4)``)
for compositing math, with conversions to/from :class:`PIL.Image.Image` at the edges.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

# ---------------------------------------------------------------------------
# Loading / conversion
# ---------------------------------------------------------------------------


def load_image(path: str | Path, *, mode: str = "RGBA") -> Image.Image:
    """Load an image from disk, applying EXIF orientation and converting mode.

    EXIF transpose matters: phone photos are frequently stored rotated.
    """
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img.convert(mode)


def to_float(img: Image.Image) -> np.ndarray:
    """RGBA :class:`PIL.Image` -> ``(H, W, 4)`` float array in ``[0, 1]``."""
    arr = np.asarray(img.convert("RGBA"), dtype=np.float32) / 255.0
    return arr


def to_pil(arr: np.ndarray) -> Image.Image:
    """``(H, W, 3|4)`` float array in ``[0, 1]`` -> RGBA :class:`PIL.Image`."""
    a = np.clip(arr, 0.0, 1.0)
    if a.shape[-1] == 3:
        alpha = np.ones((*a.shape[:2], 1), dtype=a.dtype)
        a = np.concatenate([a, alpha], axis=-1)
    return Image.fromarray((a * 255.0 + 0.5).astype(np.uint8), mode="RGBA")


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def center_crop_to_aspect(img: Image.Image, aspect: float) -> Image.Image:
    """Center-crop ``img`` to the given width/height ``aspect`` ratio."""
    w, h = img.size
    cur = w / h
    if cur > aspect:  # too wide -> trim width
        new_w = max(1, int(round(h * aspect)))
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    new_h = max(1, int(round(w / aspect)))
    top = (h - new_h) // 2
    return img.crop((0, top, w, top + new_h))


def fit_tile(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Center-crop then resize ``img`` to exactly ``size`` (cover semantics)."""
    tw, th = size
    cropped = center_crop_to_aspect(img, tw / th)
    return cropped.resize((tw, th), Image.LANCZOS)


def make_square_thumbnail(img: Image.Image, edge: int) -> Image.Image:
    """Center-cropped square thumbnail of side ``edge`` (RGB)."""
    return fit_tile(img.convert("RGB"), (edge, edge))


# ---------------------------------------------------------------------------
# Colour adjustment
# ---------------------------------------------------------------------------


def tint_toward(arr: np.ndarray, target_rgb: np.ndarray, strength: float) -> np.ndarray:
    """Blend an RGB(A) float array toward a solid ``target_rgb`` colour.

    Used by the mosaic generator to nudge each tile toward the colour of the
    region it replaces, which dramatically tightens the illusion. ``strength``
    in ``[0, 1]``; 0 leaves the tile untouched, 1 replaces it with flat colour.
    """
    strength = float(np.clip(strength, 0.0, 1.0))
    out = arr.copy()
    out[..., :3] = (1.0 - strength) * arr[..., :3] + strength * target_rgb[:3]
    return out
