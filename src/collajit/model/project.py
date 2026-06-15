"""A composition: canvas dimensions plus an ordered, bottom-first layer stack."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from ..engine import compositor, image_ops
from .layer import Layer

FILE_VERSION = 1


@dataclass
class Project:
    width: int = 1920
    height: int = 1080
    background: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    layers: list[Layer] = field(default_factory=list)
    path: str | None = None  # last saved location

    # -- layer management ---------------------------------------------------

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    def add_layer(self, layer: Layer, *, on_top: bool = True) -> Layer:
        self.layers.append(layer) if on_top else self.layers.insert(0, layer)
        return layer

    def remove_layer(self, layer_id: str) -> None:
        self.layers = [layer for layer in self.layers if layer.id != layer_id]

    def find(self, layer_id: str) -> Layer | None:
        return next((layer for layer in self.layers if layer.id == layer_id), None)

    def move(self, layer_id: str, delta: int) -> None:
        """Shift a layer up/down the stack by ``delta`` positions."""
        idx = next((i for i, ll in enumerate(self.layers) if ll.id == layer_id), None)
        if idx is None:
            return
        new = max(0, min(len(self.layers) - 1, idx + delta))
        layer = self.layers.pop(idx)
        self.layers.insert(new, layer)

    def clear(self) -> None:
        self.layers = []

    # -- rendering ----------------------------------------------------------

    def render(self) -> np.ndarray:
        """Composite all layers to a ``(H, W, 4)`` float RGBA array."""
        placed = [layer.rasterize(self.size) for layer in self.layers if layer.has_image]
        return compositor.composite(placed, self.size, background=self.background)

    def render_pil(self) -> Image.Image:
        return image_ops.to_pil(self.render())

    def export(self, path: str | Path, *, quality: int = 95, dpi: int | None = None) -> None:
        """Render and save to ``path``. JPEG gets a white matte (no alpha).

        ``dpi`` embeds print resolution so the file opens at its physical size
        (e.g. a 2250px image at 300 dpi prints at 7.5 inches).
        """
        path = Path(path)
        img = self.render_pil()
        save_kwargs = {"dpi": (dpi, dpi)} if dpi else {}
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            matte = Image.new("RGB", img.size, (255, 255, 255))
            matte.paste(img, mask=img.split()[3])
            matte.save(path, quality=quality, **save_kwargs)
        else:
            img.save(path, **save_kwargs)

    # -- persistence --------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": FILE_VERSION,
            "width": self.width,
            "height": self.height,
            "background": list(self.background),
            "layers": [layer.to_dict() for layer in self.layers],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        return cls(
            width=d.get("width", 1920),
            height=d.get("height", 1080),
            background=tuple(d.get("background", (1.0, 1.0, 1.0, 1.0))),
            layers=[Layer.from_dict(x) for x in d.get("layers", [])],
        )

    def save(self, path: str | Path) -> None:
        """Save the project JSON, materialising in-memory layer images alongside."""
        path = Path(path)
        stem = path.stem  # "art.collajit.json" -> "art.collajit"
        if stem.endswith(".collajit"):
            stem = stem[: -len(".collajit")]
        assets_dir = path.parent / f"{stem}_assets"
        for layer in self.layers:
            layer.materialize(assets_dir)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        self.path = str(path)

    @classmethod
    def load(cls, path: str | Path) -> Project:
        path = Path(path)
        proj = cls.from_dict(json.loads(path.read_text()))
        proj.path = str(path)
        return proj
