"""Web image fetching: turn a theme (typed or Claude-suggested) into a folder of
source images, color-balanced to a target, ingested straight into the library.

Pipeline: :mod:`~collajit.fetch.tagger` (optional, suggest terms from the target)
→ :mod:`~collajit.fetch.planner` (palette-spanning queries) →
:mod:`~collajit.fetch.sources` (keyless Openverse / Wikimedia / Met) →
:mod:`~collajit.fetch.downloader` → catalog ingest, all driven by
:func:`~collajit.fetch.service.run_fetch`.
"""

from .service import FetchRequest, FetchResult, run_fetch

__all__ = ["FetchRequest", "FetchResult", "run_fetch"]
