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


def load_env() -> str | None:
    """Load a local ``.env`` into the process environment, if one exists.

    Looks upward from the current working directory (so running the app from the
    project root picks up ``./.env``). Existing environment variables win over
    ``.env`` values. Returns the loaded path, or ``None`` if nothing was found or
    python-dotenv isn't installed. Safe to call more than once.
    """
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return None
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)
        return path
    return None


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


def fetched_dir() -> Path:
    """Where web-fetched images are downloaded before ingest."""
    d = cache_root() / "fetched"
    d.mkdir(parents=True, exist_ok=True)
    return d


def outputs_dir() -> Path:
    """Where the server writes generated composites for the UI to fetch."""
    d = cache_root() / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def uploads_dir() -> Path:
    """Where the server stores uploaded target images."""
    d = cache_root() / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d
