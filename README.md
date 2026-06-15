# collajit

Make digital art from hundreds-to-thousands of images, on your own machine.

Point it at a folder of images and turn them into:

- **Photo mosaics** — rebuild any target image out of your photos used as tiles.
- **Generative layouts** — arrange the whole collection by colour, or by visual
  similarity (PCA / t-SNE embeddings snapped to a grid).
- **Freeform collage** — scatter images onto a canvas and move, scale, rotate and
  blend each one by hand.

Everything lands on one interactive canvas as editable layers, with blend modes
and opacity, and exports to PNG/JPEG at full resolution.

Don't have thousands of images yet? The **Fetch** panel pulls them from the web —
keyless, Creative-Commons / public-domain sources (Openverse, Wikimedia Commons,
The Met). Point it at your target image and either type what to fetch
("eyes, iris macro") or let Claude suggest terms from the image; it then issues
**colour-balanced** searches so the fetched set actually spans the colours your
mosaic needs, filters by resolution, de-duplicates, and ingests straight into the
library (with an attribution manifest).

## Install

Requires Python 3.12+ (developed on Homebrew Python 3.14).

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Optional — to enable Claude's "Suggest from image" term suggestions, put your
Anthropic API key in a `.env` file in the project root (the rest of the app works
without it). The app loads `.env` automatically on startup; it's gitignored.

```bash
cp .env.example .env
# then edit .env:  ANTHROPIC_API_KEY=sk-ant-...
```

## Run

**Desktop app (Tauri):**

```bash
# build it once (needs Rust + Node):
cd frontend && npm install && npm run tauri build
# then launch:
open frontend/src-tauri/target/release/bundle/macos/collajit.app
# …or for development with hot reload:
cd frontend && npm run tauri dev
```

The desktop app launches the Python backend automatically. To run it as a plain
**web app** instead (one process serves the API and the built UI), use
`.venv/bin/collajit-server` and open <http://127.0.0.1:8756>.

> A legacy Qt UI also exists (`.venv/bin/python -m collajit`); the Tauri/web UI
> supersedes it.

1. Get images into the library, either:
   - **Add folder** to index your own images, or
   - the **Fetch** tab: choose a target, type terms (or click *Suggest from image*),
     set a count, and **Fetch & add to library**.
   (Thumbnails + colour features are cached in `~/.collajit`, so re-opening is instant.)
2. Pick a mode tab on the right:
   - **Mosaic** — choose a target image, set tiles-across, tint and reuse cap, Generate.
   - **Generative** — colour sort or similarity embedding into a grid.
   - **Freeform** — scatter N images, then edit them on the canvas.
3. **File → Export image…**

### Canvas controls

| Action | Control |
| --- | --- |
| Move layer | drag |
| Zoom canvas | mouse wheel |
| Scale selected layer | Ctrl/Cmd + wheel |
| Rotate selected layer | Alt + wheel, or `[` / `]` |
| Pan | Space-drag or middle-drag |
| Delete layer | Delete / Backspace |

## Development

See [CLAUDE.md](CLAUDE.md) for architecture. Tests:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
```
