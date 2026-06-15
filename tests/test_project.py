"""Tests for the document model: rendering, persistence, export."""

from __future__ import annotations

import numpy as np
from PIL import Image

from collajit.model.layer import Layer, Transform
from collajit.model.project import Project


def _red_tile_path(tmp_path):
    p = tmp_path / "red.png"
    Image.new("RGBA", (50, 50), (255, 0, 0, 255)).save(p)
    return str(p)


def test_render_size_matches_canvas(tmp_path):
    proj = Project(width=120, height=80, background=(0, 0, 0, 0))
    proj.add_layer(
        Layer(path=_red_tile_path(tmp_path), transform=Transform(cx=60, cy=40))
    )
    arr = proj.render()
    assert arr.shape == (80, 120, 4)
    # Centre pixel sits under the red tile.
    assert np.allclose(arr[40, 60, :3], [1.0, 0.0, 0.0], atol=1e-2)


def test_in_memory_layer_renders_without_path():
    proj = Project(width=20, height=20)
    layer = Layer(name="composite", transform=Transform(cx=10, cy=10))
    layer.set_image(Image.new("RGBA", (20, 20), (0, 0, 255, 255)))
    proj.add_layer(layer)
    arr = proj.render()
    assert np.allclose(arr[10, 10, :3], [0.0, 0.0, 1.0], atol=1e-2)


def test_save_load_roundtrip_materializes_images(tmp_path):
    proj = Project(width=40, height=40)
    layer = Layer(name="gen", transform=Transform(cx=20, cy=20))
    layer.set_image(Image.new("RGBA", (40, 40), (0, 255, 0, 255)))
    proj.add_layer(layer)

    out = tmp_path / "art.collajit.json"
    proj.save(out)
    assert out.exists()
    assert (tmp_path / "art_assets" / f"{layer.id}.png").exists()
    assert layer.path is not None  # materialised

    loaded = Project.load(out)
    assert loaded.width == 40 and len(loaded.layers) == 1
    arr = loaded.render()
    assert np.allclose(arr[20, 20, :3], [0.0, 1.0, 0.0], atol=1e-2)


def test_export_png_and_jpeg(tmp_path):
    proj = Project(width=30, height=30, background=(1, 1, 1, 1))
    proj.add_layer(
        Layer(path=_red_tile_path(tmp_path), transform=Transform(cx=15, cy=15))
    )
    png = tmp_path / "out.png"
    jpg = tmp_path / "out.jpg"
    proj.export(png)
    proj.export(jpg)
    assert png.exists() and jpg.exists()
    assert Image.open(jpg).mode == "RGB"


def test_export_embeds_dpi(tmp_path):
    proj = Project(width=30, height=30, background=(1, 1, 1, 1))
    proj.add_layer(
        Layer(path=_red_tile_path(tmp_path), transform=Transform(cx=15, cy=15))
    )
    png = tmp_path / "dpi.png"
    proj.export(png, dpi=300)
    info = Image.open(png).info
    assert round(info["dpi"][0]) == 300


def test_layer_reorder():
    proj = Project()
    a = proj.add_layer(Layer(name="a"))
    b = proj.add_layer(Layer(name="b"))
    assert [layer.name for layer in proj.layers] == ["a", "b"]
    proj.move(a.id, +1)
    assert [layer.name for layer in proj.layers] == ["b", "a"]
    proj.remove_layer(b.id)
    assert [layer.name for layer in proj.layers] == ["a"]
