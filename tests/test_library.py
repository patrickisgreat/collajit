"""Tests for catalog + ingest, including incremental re-ingest."""

from __future__ import annotations

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
