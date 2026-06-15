# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`collajit` makes digital art from large image collections — hundreds to thousands
of images. Three art modes: **photo mosaic**, **generative/algorithmic layouts**,
and **freeform layered collage**.

**The UI is a Tauri desktop app** (Rust shell → React/Vite frontend → local FastAPI
backend that wraps the Python core). The Python compute core is UI-agnostic and is
the source of truth; the Qt/PySide6 app (`collajit.ui`, `python -m collajit`) is the
**legacy** first UI, kept working but superseded by the web/Tauri UI.

### Run

```bash
# Desktop app (built .app):
open frontend/src-tauri/target/release/bundle/macos/collajit.app
# Desktop app, dev (hot reload; spawns backend via .venv):
cd frontend && npm run tauri dev
# Build the .app:
cd frontend && npm run tauri build
# Web app only (one process serves API + built UI): open http://127.0.0.1:8756
.venv/bin/collajit-server
# Legacy Qt UI:
.venv/bin/python -m collajit
```

The Tauri shell (`frontend/src-tauri/src/lib.rs`) spawns `.venv/bin/collajit-server`
on launch (found by walking up from the executable to the repo root, so `.env`
loads) and kills it on exit. Distribution to machines without the `.venv` needs a
PyInstaller sidecar (not yet built — `spawn_backend()` already prefers a `collajit-server`
binary next to the executable if present).

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

fetch/   ── pull source images from the web into the library (all keyless/CC sources)
  sources/    Openverse / Wikimedia / Met adapters behind one ImageSource interface;
              they take an injectable HttpClient (RequestsHttp default) so tests run offline
  planner     derive palette-spanning queries from the target's colours, budget count across them
  downloader  concurrent download, decode-verify + min-resolution filter, hash-dedupe, manifest.jsonl
  tagger      OPTIONAL Claude-vision term suggestion (anthropic SDK, claude-opus-4-8); only fills
              the terms box — typed terms always work and take precedence
  service     run_fetch(): plan → search all sources → download → ingest into the catalog

server/  ── FastAPI backend (the API the web/Tauri UI calls; reuses the core)
  app         create_app(): REST + SSE over library/fetch/generators/project; serves
              frontend/dist at / when built; physical-sizing + no-repeat live here
  jobs        in-process JobManager: long ops run on threads, progress streamed via SSE

ui/      ── PySide6 editor (LEGACY Qt UI; superseded by the Tauri app)
  main_window owns the Catalog + active Project; turns panel signals into model edits
  canvas      QGraphicsView; each Layer is a movable LayerItem, edits write back to the model
  worker      run_async(): heavy work on QThreadPool, off the UI thread
```

Outside the Python package:

```
frontend/         Vite + React + TS UI (the real front end)
  src/api.ts      thin client: REST helpers + runJob() SSE subscriber; API_BASE = :8756
  src/App.tsx     layout + Library / Fetch / Mosaic / Generative tabs + Preview
  src-tauri/      Tauri 2 (Rust) desktop shell; lib.rs spawns/kills the backend
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
  `COLLAJIT_HOME` env var (see `tests/conftest.py`). Fetched images land in
  `~/.collajit/fetched/<slug>/` and are auto-ingested.
- **Fetch is Qt-free and network-isolated for tests.** Sources never import
  `requests` directly — they take an `HttpClient`; `tests/test_fetch.py` injects a
  `FakeHttp`. Don't add real network calls to the test suite.
- **Claude vision tagging** needs `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`).
  `app.main()` calls `config.load_env()` first, which loads a project-root `.env`
  (via python-dotenv, real env vars win) — so the key lives in `.env` (gitignored;
  `.env.example` is the template), not the shell. `tagger.suggest_terms` raises a
  friendly `RuntimeError` if it's missing, and the UI falls back to typed terms. It
  uses `claude-opus-4-8` with a JSON-schema output — see the `claude-api` skill
  before changing it.
