"""Download candidate results into a folder, filtering and de-duplicating.

Concurrency keeps a few downloads in flight at once. Every file is decoded to
verify it's a real image and meets the minimum resolution; exact-duplicate bytes
(common when sources overlap) are dropped by content hash. An attribution manifest
(``manifest.jsonl``) is written alongside for licensing/credit.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from .sources.base import HttpClient, ImageResult, RequestsHttp

ProgressCb = Callable[[int, int], None]

_EXT_BY_FORMAT = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "GIF": ".gif",
    "BMP": ".bmp",
    "TIFF": ".tiff",
}


def download_results(
    results: list[ImageResult],
    dest_dir: str | Path,
    *,
    max_count: int,
    min_width: int = 0,
    min_height: int = 0,
    http: HttpClient | None = None,
    workers: int = 8,
    progress: ProgressCb | None = None,
    on_saved: Callable[[Path], None] | None = None,
) -> list[Path]:
    """Download up to ``max_count`` valid, unique images into ``dest_dir``.

    ``on_saved(path)`` is invoked for each file as it lands, so the caller can
    ingest incrementally (the fetcher uses this to fill the library grid live).
    Returns the saved file paths.
    """
    http = http or RequestsHttp()
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # De-dup candidate URLs up front (sources overlap heavily).
    seen_urls: set[str] = set()
    candidates: list[ImageResult] = []
    for r in results:
        if r.url not in seen_urls:
            seen_urls.add(r.url)
            candidates.append(r)

    saved: list[Path] = []
    seen_hashes: set[str] = set()
    manifest: list[dict] = []
    done = 0
    total = min(len(candidates), max_count) or 1

    # Files already on disk from a previous run (by "<source>_<hash>" stem), so a
    # re-fetch of the same term skips images we already have instead of
    # re-downloading + re-ingesting them (which only updated rows and inflated the
    # "added" count without growing the library).
    existing_stems: set[str] = set()
    if dest.exists():
        existing_stems = {p.stem for p in dest.iterdir() if p.is_file()}

    def fetch(result: ImageResult) -> tuple[ImageResult, bytes] | None:
        try:
            return result, http.get_bytes(result.url)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for outcome in pool.map(fetch, candidates):
            if len(saved) >= max_count:
                break
            if outcome is None:
                continue
            result, data = outcome
            digest = hashlib.sha1(data).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            stem = f"{result.source}_{digest[:16]}"
            if stem in existing_stems:
                continue  # already have this exact image from a prior fetch
            path = _validate_and_save(data, digest, result, dest, min_width, min_height)
            if path is None:
                continue
            existing_stems.add(stem)
            saved.append(path)
            manifest.append({"file": path.name, **asdict(result)})
            done += 1
            if on_saved is not None:
                on_saved(path)
            if progress is not None:
                progress(done, total)

    if manifest:
        _append_manifest(dest / "manifest.jsonl", manifest)
    if progress is not None:
        progress(len(saved), total)
    return saved


def _validate_and_save(
    data: bytes,
    digest: str,
    result: ImageResult,
    dest: Path,
    min_width: int,
    min_height: int,
) -> Path | None:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            fmt = img.format
            w, h = img.size
    except Exception:
        return None
    if w < min_width or h < min_height:
        return None
    ext = _EXT_BY_FORMAT.get(fmt or "", ".png")
    path = dest / f"{result.source}_{digest[:16]}{ext}"
    path.write_bytes(data)
    return path


def _append_manifest(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
