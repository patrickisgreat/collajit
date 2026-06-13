# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`collajit` is a local desktop app (PySide6/Qt6) for making digital art from large
image collections — hundreds to thousands of images. Three art modes: **photo
mosaic**, **generative/algorithmic layouts**, and **freeform layered collage**,
all editable on one interactive canvas.

## Environment

The interpreter is a venv on Homebrew **Python 3.14** at `./.venv` (the system
`/usr/bin/python3` is 3.9 and the Homebrew `python@3.12` bottle is broken on this
machine — an `expat` symbol mismatch). Always use `.venv/bin/python`.

```bash
.venv/bin/python -m pip install -e ".[dev]"   # set up / refresh deps
```

## Commands

```bash
# Run the editor
.venv/bin/python -m collajit          # or: .venv/bin/collajit

# Tests (offscreen so the UI smoke tests run without a display)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest

# A single test
.venv/bin/python -m pytest tests/test_generators.py::test_mosaic_size_and_color_match

# Lint / autofix
.venv/bin/ruff check src tests
.venv/bin/ruff check --fix src tests
```

## Architecture

The codebase is a strict stack — lower layers never import higher ones. The
central design idea: **every art mode produces `Layer`s, and a single compositor
renders the layer stack to the final image.** Generate, preview, and export all
go through that one path, so what you see is what you export.

```
engine/  ── pure image logic, ZERO Qt imports (headless, fully unit-tested)
  image_ops   load/resize/crop/tint, PIL<->float-RGBA-array conversions
  features    per-image feature vector (mean RGB + 4x4 grid + HSV hist); FEATURE_VERSION
  matcher     NearestNeighbors index + greedy diversity-aware assignment (mosaic)
  compositor  blend a list of PlacedLayers -> (H,W,4) float image (W3C blend modes)
              `rasterize()` turns a Layer's source+transform into a PlacedLayer

model/   ── the document
  layer       Layer = source (disk path OR in-memory image) + Transform + opacity/blend
  project     Project = canvas size + ordered (bottom-first) layer list; render/save/load/export

library/ ── the source-image catalog (cached in ~/.collajit, override with $COLLAJIT_HOME)
  catalog     SQLite: one row/image with mtime, dims, thumbnail path, feature blob
  ingest      incremental folder scan -> thumbnails + features (skips unchanged files)

generators/ ── the three art modes (consume the library, emit composition output)
  mosaic      rebuild a target from best-matching tiles; returns one composite PIL image
  generative  colour-sort grid OR PCA/t-SNE embedding snapped to a grid; one composite image
  freeform    scatter library images as MANY editable Layers (kept high-res & movable)

ui/      ── PySide6 editor (the only Qt code)
  main_window owns the Catalog + active Project; turns panel signals into model edits
  canvas      QGraphicsView; each Layer is a movable LayerItem, edits write back to the model
  library_panel / layers_panel / panels/*  docked controls
  worker      run_async(): heavy work (ingest, mosaic, generative) on QThreadPool, off the UI thread
```

### Things worth knowing before you change code

- **Keep `engine/` and `generators/` Qt-free.** They're the testable core and are
  imported headless in CI. `app.main()` imports Qt lazily for the same reason.
- **Mosaic/generative return a baked `PIL.Image`; freeform returns `Layer`s.** The
  first two become a single in-memory composite layer; freeform stays editable.
- **In-memory vs path-backed layers:** generator composites live in `Layer._image`
  until `Project.save()` writes them into `<name>_assets/` and sets `Layer.path`.
- **Feature space is shared.** Mosaic features each *target cell* with the *same*
  `extract_features` used on source images, so matching is apples-to-apples. If you
  change the feature layout, bump `FEATURE_VERSION` (catalog auto-invalidates).
- **Transform convention:** `Transform.cx/cy` is the layer's *centre* in canvas px;
  the canvas sets the item's transform origin to its centre so scale/rotation pivot
  there. Keep `canvas` and `compositor.rasterize` consistent if you touch this.
- The catalog/thumbnails persist under `~/.collajit`. Tests isolate it via the
  `COLLAJIT_HOME` env var (see `tests/conftest.py`).
