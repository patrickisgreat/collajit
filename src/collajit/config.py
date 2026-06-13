"""Filesystem locations and small app-wide constants."""

from __future__ import annotations

import os
from pathlib import Path

#: Image extensions we ingest. Lower-case, leading dot.
IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
)

#: Edge length (px) of the square thumbnails cached for the library browser and
#: used as the feature-extraction working size. Small = fast catalog, still
#: enough signal for colour/feature matching.
THUMBNAIL_SIZE = 128


def cache_root() -> Path:
    """Root directory for catalogs, thumbnails and other derived data.

    Override with ``COLLAJIT_HOME`` (useful for tests and throwaway runs).
    """
    env = os.environ.get("COLLAJIT_HOME")
    base = Path(env) if env else Path.home() / ".collajit"
    base.mkdir(parents=True, exist_ok=True)
    return base


def thumbnails_dir() -> Path:
    d = cache_root() / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d
