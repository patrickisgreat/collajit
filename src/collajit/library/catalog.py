"""SQLite-backed catalog of source images.

One row per image: its path, mtime/size (for incremental re-ingest), dimensions,
thumbnail location, and the feature vector (stored as a float32 blob). Keeping
this on disk means reopening a 5,000-image folder is instant — we only process
files whose mtime changed.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import config
from ..engine.features import FEATURE_DIM, FEATURE_VERSION


@dataclass
class ImageRecord:
    path: str
    mtime: float
    width: int
    height: int
    thumb_path: str
    feature: np.ndarray  # (FEATURE_DIM,) float32

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 1.0


_SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    path        TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    thumb_path  TEXT NOT NULL,
    feature     BLOB NOT NULL,
    feat_dim    INTEGER NOT NULL,
    feat_ver    INTEGER NOT NULL
);
"""


class Catalog:
    """Open (creating if needed) the catalog database.

    ``db_path`` defaults to ``<cache_root>/catalog.db``. Usable as a context
    manager.

    The connection is shared across threads (ingest/fetch run on worker threads
    while the UI thread reads), so it's opened with ``check_same_thread=False`` and
    every access is serialised by a lock — SQLite forbids concurrent use of one
    connection from multiple threads.
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else config.cache_root() / "catalog.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def __enter__(self) -> Catalog:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- writes -------------------------------------------------------------

    def upsert(self, rec: ImageRecord) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO images
                       (path, mtime, width, height, thumb_path, feature, feat_dim, feat_ver)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET
                       mtime=excluded.mtime, width=excluded.width, height=excluded.height,
                       thumb_path=excluded.thumb_path, feature=excluded.feature,
                       feat_dim=excluded.feat_dim, feat_ver=excluded.feat_ver""",
                (
                    rec.path,
                    rec.mtime,
                    rec.width,
                    rec.height,
                    rec.thumb_path,
                    rec.feature.astype(np.float32).tobytes(),
                    FEATURE_DIM,
                    FEATURE_VERSION,
                ),
            )
            self._conn.commit()

    def remove(self, path: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM images WHERE path = ?", (path,))
            self._conn.commit()

    def clear(self) -> None:
        """Empty the catalog (start over). Does not touch files on disk."""
        with self._lock:
            self._conn.execute("DELETE FROM images")
            self._conn.commit()

    # -- reads --------------------------------------------------------------

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]

    def needs_update(self, path: str, mtime: float) -> bool:
        """True if ``path`` is missing, changed, or has stale features."""
        with self._lock:
            row = self._conn.execute(
                "SELECT mtime, feat_ver FROM images WHERE path = ?", (path,)
            ).fetchone()
        if row is None:
            return True
        return row["mtime"] != mtime or row["feat_ver"] != FEATURE_VERSION

    def _row_to_record(self, row: sqlite3.Row) -> ImageRecord:
        feat = np.frombuffer(row["feature"], dtype=np.float32).copy()
        return ImageRecord(
            path=row["path"],
            mtime=row["mtime"],
            width=row["width"],
            height=row["height"],
            thumb_path=row["thumb_path"],
            feature=feat,
        )

    def all_records(self) -> list[ImageRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM images WHERE feat_ver = ? ORDER BY path", (FEATURE_VERSION,)
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def feature_matrix(self) -> tuple[list[ImageRecord], np.ndarray]:
        """Return current records and a stacked ``(N, FEATURE_DIM)`` feature array."""
        records = self.all_records()
        if not records:
            return [], np.empty((0, FEATURE_DIM), dtype=np.float32)
        feats = np.vstack([r.feature for r in records]).astype(np.float32)
        return records, feats
