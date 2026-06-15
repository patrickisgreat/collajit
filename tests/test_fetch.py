"""Offline tests for the fetch system: sources, planner, downloader, service.

A FakeHttp serves canned JSON and synthesised image bytes so nothing touches the
network. The Claude tagger's pure parsing helper is tested directly.
"""

from __future__ import annotations

import hashlib
import io

import numpy as np
from PIL import Image

from collajit.fetch import FetchRequest, planner, run_fetch
from collajit.fetch.downloader import download_results
from collajit.fetch.sources import (
    MetSource,
    OpenverseSource,
    PexelsSource,
    WikimediaSource,
)
from collajit.fetch.sources.base import ImageResult
from collajit.fetch.tagger import has_api_key, parse_terms_response


def _png_bytes(url: str, size: int = 500) -> bytes:
    # Colour seeded by the URL so distinct URLs yield distinct bytes (no false dedup).
    seed = int(hashlib.sha1(url.encode()).hexdigest()[:6], 16)
    rng = np.random.default_rng(seed)
    arr = (rng.uniform(0, 255, (size, size, 3))).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


class FakeHttp:
    """Dispatches by URL substring; records calls."""

    def __init__(self, *, image_size: int = 500):
        self.image_size = image_size
        self.json_calls: list[str] = []
        self.byte_calls: list[str] = []

    def get_json(self, url, *, params=None, headers=None):
        self.json_calls.append(url)
        if "openverse" in url:
            return {
                "results": [
                    {"url": "http://img/ov_a.png", "width": 500, "height": 500,
                     "title": "A", "creator": "Alice", "license": "cc-by",
                     "foreign_landing_url": "http://ov/a"},
                    {"url": "http://img/ov_b.png", "width": 500, "height": 500},
                    {"url": "http://img/ov_small.png", "width": 100, "height": 100},
                ]
            }
        if "api.php" in url:  # wikimedia
            return {"query": {"pages": {
                "1": {"title": "File:w.jpg", "imageinfo": [{
                    "url": "http://img/wm_a.jpg", "width": 600, "height": 600,
                    "mime": "image/jpeg",
                    "extmetadata": {"LicenseShortName": {"value": "CC BY 2.0"},
                                    "Artist": {"value": "<a href='x'>Bob</a>"}},
                    "descriptionurl": "http://wm/a"}]},
                "2": {"title": "File:doc.pdf", "imageinfo": [{
                    "url": "http://img/doc.pdf", "width": 0, "height": 0,
                    "mime": "application/pdf"}]},
            }}}
        if "pexels" in url:
            return {
                "photos": [
                    {"src": {"original": "http://img/px_a.jpg"}, "width": 800, "height": 600,
                     "photographer": "Jane", "alt": "an eye", "url": "http://px/a"},
                    {"src": {"original": "http://img/px_small.jpg"}, "width": 100, "height": 100,
                     "photographer": "Bob", "url": "http://px/b"},
                ],
                "next_page": None,
            }
        if "/search" in url:  # met search
            return {"total": 2, "objectIDs": [11, 22]}
        if "/objects/" in url:  # met object detail
            oid = url.rstrip("/").split("/")[-1]
            return {
                "primaryImage": f"http://img/met_{oid}.jpg",
                "isPublicDomain": oid == "11",  # only one is public domain
                "title": "Artwork",
                "artistDisplayName": "Painter",
                "objectURL": f"http://met/{oid}",
            }
        return {}

    def get_bytes(self, url, *, headers=None):
        self.byte_calls.append(url)
        return _png_bytes(url, self.image_size)


# -- sources ---------------------------------------------------------------


def test_openverse_parses_and_filters_small():
    http = FakeHttp()
    results = OpenverseSource().search("eyes", limit=10, http=http, min_width=400, min_height=400)
    urls = [r.url for r in results]
    assert "http://img/ov_a.png" in urls
    assert "http://img/ov_small.png" not in urls  # below min resolution
    assert all(r.source == "openverse" for r in results)


def test_wikimedia_parses_and_skips_non_image():
    results = WikimediaSource().search("eyes", limit=10, http=FakeHttp())
    assert [r.url for r in results] == ["http://img/wm_a.jpg"]  # pdf skipped
    assert results[0].license == "Wikimedia Commons"
    assert results[0].landing_url == "http://wm/a"


def test_pexels_parses_filters_and_needs_key(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "test-key")
    res = PexelsSource().search("eyes", limit=10, http=FakeHttp(), min_width=400, min_height=400)
    assert [r.url for r in res] == ["http://img/px_a.jpg"]  # small one filtered out
    assert res[0].license == "Pexels License"
    assert res[0].creator == "Jane"

    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert PexelsSource().search("eyes", limit=10, http=FakeHttp()) == []  # no key → skip


def test_met_two_step_keeps_only_public_domain():
    results = MetSource().search("eyes", limit=10, http=FakeHttp())
    assert [r.url for r in results] == ["http://img/met_11.jpg"]  # 22 is not PD
    assert results[0].license.startswith("Public Domain")


# -- planner ---------------------------------------------------------------


def test_planner_no_target_splits_terms():
    plans = planner.plan_queries(["eyes", "iris"], None, total=10)
    assert {p.query for p in plans} == {"eyes", "iris"}
    assert sum(p.count for p in plans) == 10


def test_planner_with_target_adds_color_queries_and_conserves_total():
    target = Image.new("RGB", (64, 64), (20, 40, 220))  # mostly blue
    plans = planner.plan_queries(["eyes"], target, total=24)
    queries = {p.query for p in plans}
    assert "eyes" in queries  # plain on-theme query retained
    assert any(q.endswith("blue") for q in queries)  # colour-spanning query added
    assert sum(p.count for p in plans) == 24


def test_color_weights_detect_dominant():
    blue = Image.new("RGB", (32, 32), (10, 10, 230))
    weights = planner.color_weights(blue)
    assert max(weights, key=weights.get) == "blue"


# -- downloader ------------------------------------------------------------


def test_downloader_filters_dedupes_and_writes_manifest(tmp_path):
    http = FakeHttp()
    results = [
        ImageResult(url="http://img/one.png", source="openverse"),
        ImageResult(url="http://img/one.png", source="openverse"),  # dup URL
        ImageResult(url="http://img/two.png", source="met"),
    ]
    saved = download_results(
        results, tmp_path, max_count=10, min_width=400, min_height=400, http=http
    )
    assert len(saved) == 2  # duplicate URL collapsed
    assert (tmp_path / "manifest.jsonl").exists()


def test_downloader_skips_already_downloaded_across_runs(tmp_path):
    http = FakeHttp()
    results = [
        ImageResult(url="http://img/one.png", source="openverse"),
        ImageResult(url="http://img/two.png", source="openverse"),
    ]
    first = download_results(results, tmp_path, max_count=10, min_width=400, min_height=400, http=http)
    assert len(first) == 2
    # Re-fetching the same images must add 0 (they're already on disk) — this is
    # the fix for the "added N but library count didn't grow" inconsistency.
    again = download_results(results, tmp_path, max_count=10, min_width=400, min_height=400, http=http)
    assert again == []


def test_downloader_drops_below_min_resolution(tmp_path):
    http = FakeHttp(image_size=200)  # every image is 200x200
    results = [ImageResult(url="http://img/x.png", source="openverse")]
    saved = download_results(
        results, tmp_path, max_count=10, min_width=400, min_height=400, http=http
    )
    assert saved == []


# -- service end to end ----------------------------------------------------


def test_run_fetch_downloads_and_ingests(catalog, tmp_path):
    http = FakeHttp()
    request = FetchRequest(terms=["eyes"], count=2, min_width=400, min_height=400,
                           sources=["openverse"])
    result = run_fetch(request, catalog, dest_dir=tmp_path / "out", http=http)
    assert result.downloaded >= 1
    assert result.ingested >= 1
    assert catalog.count() == result.catalog_total
    assert result.catalog_total >= 1


# -- tagger (pure parsing) -------------------------------------------------


def test_parse_terms_response_dedupes_and_caps():
    text = '{"subject": "eye", "terms": ["eye", "iris macro", "Iris Macro", "eyelashes"]}'
    terms = parse_terms_response(text, max_terms=3)
    assert terms[0] == "eye"
    assert terms == ["eye", "iris macro", "eyelashes"]  # case-insensitive dedup, capped


def test_has_api_key_reads_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert has_api_key() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert has_api_key() is True
