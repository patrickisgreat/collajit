"""Orchestrate a fetch: plan → search (all sources) → download → ingest.

This is the single entry point the UI drives on a background thread. It returns a
summary the UI shows; the downloaded images are already in the catalog when it
returns.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..engine import image_ops
from ..library import ingest_file
from ..library.catalog import Catalog
from . import planner
from .downloader import download_results
from .sources import SOURCES
from .sources.base import HttpClient, ImageResult

ProgressCb = Callable[[int, int], None]
LogCb = Callable[[str], None]


@dataclass
class FetchRequest:
    terms: list[str]
    target_path: str | None = None
    count: int = 300
    min_width: int = 400
    min_height: int = 400
    sources: list[str] = field(default_factory=lambda: list(SOURCES.keys()))


@dataclass
class FetchResult:
    downloaded: int
    ingested: int
    dest_dir: str
    queries: list[str]
    catalog_total: int
    source_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _slug(terms: list[str]) -> str:
    head = re.sub(r"[^a-z0-9]+", "-", terms[0].lower()).strip("-") if terms else "fetch"
    digest = hashlib.sha1("|".join(terms).encode("utf-8")).hexdigest()[:8]
    return f"{head or 'fetch'}-{digest}"


def run_fetch(
    request: FetchRequest,
    catalog: Catalog,
    *,
    dest_dir: str | Path | None = None,
    http: HttpClient | None = None,
    progress: ProgressCb | None = None,
    log: LogCb | None = None,
) -> FetchResult:
    _log = log or (lambda *_: None)
    enabled = [s for s in request.sources if s in SOURCES] or list(SOURCES.keys())
    sources = [SOURCES[s]() for s in enabled]

    target = None
    if request.target_path:
        target = image_ops.load_image(request.target_path, mode="RGB")

    planned = planner.plan_queries(request.terms, target, total=request.count)
    _log(f"Planned {len(planned)} queries across {len(sources)} source(s).")

    # Fan out searches across (query x source). Each returns up to that query's
    # budget; the union over-fetches and the downloader caps + dedupes.
    def do_search(args):
        pq, source = args
        try:
            return source.search(
                pq.query,
                limit=max(pq.count, 1),
                http=http or _default_http(),
                min_width=request.min_width,
                min_height=request.min_height,
            )
        except Exception as exc:  # noqa: BLE001 - reported per source to the user
            return exc

    tasks = [(pq, src) for pq in planned for src in sources]
    candidates: list[ImageResult] = []
    source_counts: dict[str, int] = {src.id: 0 for src in sources}
    errors: list[str] = []
    # No numeric progress here — searching is opaque (a source may internally
    # paginate), so the UI shows an indeterminate "Searching…" bar driven by these
    # log lines; the determinate bar kicks in during download below.
    with ThreadPoolExecutor(max_workers=min(4, len(tasks) or 1)) as pool:
        for i, outcome in enumerate(pool.map(do_search, tasks)):
            pq, src = tasks[i]
            if isinstance(outcome, Exception):
                note = f"{src.id}: {type(outcome).__name__} (likely rate-limited)"
                if note not in errors:
                    errors.append(note)
                _log(f"searched {src.id} “{pq.query}” → error ({outcome})")
                continue
            candidates.extend(outcome)
            source_counts[src.id] += len(outcome)
            _log(f"searched {src.id} “{pq.query}” → {len(outcome)} results")

    dest = Path(dest_dir) if dest_dir else config.cache_root() / "fetched" / _slug(request.terms)
    _log(f"Found {len(candidates)} candidates; downloading up to {request.count}…")

    ingested = 0

    def on_saved(path: Path) -> None:
        nonlocal ingested
        if ingest_file(path, catalog):
            ingested += 1
            if ingested % 25 == 0:
                _log(f"  added {ingested} images to the library…")

    saved = download_results(
        candidates,
        dest,
        max_count=request.count,
        min_width=request.min_width,
        min_height=request.min_height,
        http=http or _default_http(),
        progress=progress,
        on_saved=on_saved,
    )

    total = catalog.count()
    _log(f"Done — downloaded {len(saved)}, added {ingested}. Library now has {total}.")
    return FetchResult(
        downloaded=len(saved),
        ingested=ingested,
        dest_dir=str(dest),
        queries=[pq.query for pq in planned],
        catalog_total=total,
        source_counts=source_counts,
        errors=errors,
    )


def _default_http() -> HttpClient:
    from .sources.base import RequestsHttp

    return RequestsHttp()
