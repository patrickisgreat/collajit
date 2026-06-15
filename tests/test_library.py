"""Tests for catalog + ingest, including incremental re-ingest."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from collajit.engine.features import FEATURE_DIM
from collajit.library import ingest, scan_folders


def test_scan_finds_images(image_dir):
    files = scan_folders([image_dir])
    assert len(files) == 26  # 24 hues + 2 gradients
    assert all(p.suffix == ".png" for p in files)


def test_ingest_populates_catalog(library):
    catalog, records, features = library
    assert catalog.count() == 26
    assert len(records) == 26
    assert features.shape == (26, FEATURE_DIM)


def test_ingest_is_incremental(image_dir, catalog):
    first = ingest([image_dir], catalog)
    assert first == 26
    # Nothing changed -> second pass processes zero files.
    second = ingest([image_dir], catalog)
    assert second == 0


def test_records_carry_thumbnails_and_dims(library):
    _catalog, records, _features = library
    rec = records[0]
    assert rec.width == 64 and rec.height == 64
    assert rec.thumb_path.endswith(".png")


def test_clear_empties_catalog(library):
    catalog, _records, _features = library
    assert catalog.count() == 26
    catalog.clear()
    assert catalog.count() == 0
    assert catalog.all_records() == []


def test_catalog_usable_across_threads(image_dir, catalog):
    """Catalog is created on one thread but ingest runs on a worker thread (as in
    the UI). Regression for 'SQLite objects created in a thread...'."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        processed = pool.submit(ingest, [image_dir], catalog).result()
    assert processed == 26
    # Read back from the main thread — would raise without check_same_thread/lock.
    assert catalog.count() == 26
