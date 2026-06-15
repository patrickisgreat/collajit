"""Folder ingest: scan directories, build thumbnails + features, fill the catalog.

Incremental — files already current in the catalog (matching mtime and feature
version) are skipped, so re-ingesting a large folder after adding a few images is
cheap. Designed to be driven from a background thread with a ``progress`` callback.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from pathlib import Path

from PIL import Image

from .. import config
from ..engine import image_ops
from ..engine.features import extract_features
from .catalog import Catalog, ImageRecord

# (done, total) — same shape as the generator/fetch progress callbacks.
ProgressCb = Callable[[int, int], None]


def scan_folders(folders: Iterable[str | Path], *, recursive: bool = True) -> list[Path]:
    """Return all image files under ``folders`` (deduplicated, sorted)."""
    found: set[Path] = set()
    for folder in folders:
        folder = Path(folder)
        if folder.is_file():
            if folder.suffix.lower() in config.IMAGE_EXTENSIONS:
                found.add(folder.resolve())
            continue
        if not folder.is_dir():
            continue
        walker = folder.rglob("*") if recursive else folder.glob("*")
        for p in walker:
            if p.is_file() and p.suffix.lower() in config.IMAGE_EXTENSIONS:
                found.add(p.resolve())
    return sorted(found)


def _thumb_path_for(src: Path) -> Path:
    digest = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:20]
    return config.thumbnails_dir() / f"{digest}.png"


def _process_one(src: Path) -> ImageRecord:
    img = image_ops.load_image(src, mode="RGB")
    width, height = img.size
    thumb = image_ops.make_square_thumbnail(img, config.THUMBNAIL_SIZE)
    thumb_path = _thumb_path_for(src)
    thumb.save(thumb_path)
    feature = extract_features(thumb)
    return ImageRecord(
        path=str(src),
        mtime=src.stat().st_mtime,
        width=width,
        height=height,
        thumb_path=str(thumb_path),
        feature=feature,
    )


def ingest_file(path: str | Path, catalog: Catalog) -> bool:
    """Ingest a single image into the catalog. Returns True if (re)processed.

    Used by the fetcher to add images one-by-one as they download, so the library
    grid fills live instead of all at once at the end.
    """
    src = Path(path)
    try:
        if not catalog.needs_update(str(src), src.stat().st_mtime):
            return False
        catalog.upsert(_process_one(src))
        return True
    except (OSError, Image.DecompressionBombError, ValueError):
        return False


def ingest(
    folders: Iterable[str | Path],
    catalog: Catalog,
    *,
    recursive: bool = True,
    progress: ProgressCb | None = None,
) -> int:
    """Ingest images from ``folders`` into ``catalog``. Returns count processed.

    ``progress(done, total)`` is called per file (including skips) so a UI can show
    a determinate progress bar.
    """
    files = scan_folders(folders, recursive=recursive)
    total = len(files)
    processed = 0
    for i, src in enumerate(files, start=1):
        try:
            mtime = src.stat().st_mtime
            if catalog.needs_update(str(src), mtime):
                catalog.upsert(_process_one(src))
                processed += 1
        except (OSError, Image.DecompressionBombError, ValueError):
            # Unreadable / corrupt / absurdly large image — skip, keep going.
            pass
        if progress is not None:
            progress(i, total)
    return processed
