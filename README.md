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

## Install

Requires Python 3.12+ (developed on Homebrew Python 3.14).

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Run

```bash
.venv/bin/python -m collajit      # or: .venv/bin/collajit
```

1. **Library → Add folder…** to index your images (thumbnails + colour features
   are cached in `~/.collajit`, so re-opening is instant).
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
