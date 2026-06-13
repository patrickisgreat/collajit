"""A single placed image in a composition.

A layer is either backed by a file on disk (``path`` — e.g. a library image used
in a freeform collage) or by an in-memory image (``set_image`` — e.g. the
composite produced by the mosaic or generative generators). In-memory images are
written to the project's asset folder on save and become path-backed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from ..engine import compositor, image_ops


@dataclass
class Transform:
    """Centre position (canvas px), uniform ``scale`` and ``rotation`` (degrees)."""

    cx: float = 0.0
    cy: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0

    def to_dict(self) -> dict:
        return {"cx": self.cx, "cy": self.cy, "scale": self.scale, "rotation": self.rotation}

    @classmethod
    def from_dict(cls, d: dict) -> Transform:
        return cls(
            cx=d.get("cx", 0.0),
            cy=d.get("cy", 0.0),
            scale=d.get("scale", 1.0),
            rotation=d.get("rotation", 0.0),
        )


@dataclass
class Layer:
    name: str = "Layer"
    path: str | None = None
    transform: Transform = field(default_factory=Transform)
    opacity: float = 1.0
    blend: str = "normal"
    visible: bool = True
    locked: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # In-memory source for generator output; never serialised directly.
    _image: Image.Image | None = field(default=None, repr=False, compare=False)

    # -- image source -------------------------------------------------------

    def set_image(self, img: Image.Image) -> None:
        """Attach an in-memory RGBA image (clears any cached disk load)."""
        self._image = img.convert("RGBA")

    def get_image(self) -> Image.Image:
        """Return the layer's source image, loading from ``path`` if needed."""
        if self._image is not None:
            return self._image
        if self.path:
            self._image = image_ops.load_image(self.path, mode="RGBA")
            return self._image
        raise ValueError(f"layer {self.name!r} has no image source")

    @property
    def has_image(self) -> bool:
        return self._image is not None or bool(self.path)

    # -- rendering ----------------------------------------------------------

    def rasterize(self, canvas_size: tuple[int, int]) -> compositor.PlacedLayer:
        """Build the :class:`PlacedLayer` for this layer on ``canvas_size``."""
        return compositor.rasterize(
            self.get_image(),
            canvas_size=canvas_size,
            cx=self.transform.cx,
            cy=self.transform.cy,
            scale=self.transform.scale,
            rotation_deg=self.transform.rotation,
            opacity=self.opacity,
            blend=self.blend,
            visible=self.visible,
        )

    # -- persistence --------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "transform": self.transform.to_dict(),
            "opacity": self.opacity,
            "blend": self.blend,
            "visible": self.visible,
            "locked": self.locked,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Layer:
        return cls(
            id=d.get("id", uuid.uuid4().hex),
            name=d.get("name", "Layer"),
            path=d.get("path"),
            transform=Transform.from_dict(d.get("transform", {})),
            opacity=d.get("opacity", 1.0),
            blend=d.get("blend", "normal"),
            visible=d.get("visible", True),
            locked=d.get("locked", False),
        )

    def materialize(self, assets_dir: Path) -> None:
        """Persist an in-memory image to ``assets_dir`` and adopt it as ``path``.

        No-op for layers that already have a ``path`` and no overriding image.
        """
        if self._image is None:
            return
        assets_dir.mkdir(parents=True, exist_ok=True)
        out = assets_dir / f"{self.id}.png"
        self._image.save(out)
        self.path = str(out)
