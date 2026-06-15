"""Tests for the FastAPI backend (offline: fake HTTP, threaded jobs polled)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from collajit.server import create_app

from .test_fetch import FakeHttp


@pytest.fixture
def client(catalog):
    app = create_app(catalog=catalog, http=FakeHttp())
    with TestClient(app) as c:
        yield c


def _wait(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job_id}").json()
        if snap["status"] in ("done", "error"):
            return snap
        time.sleep(0.03)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


def _ingest(client: TestClient, folder) -> dict:
    job = client.post("/api/library/folder", json={"path": str(folder)}).json()
    return _wait(client, job["job_id"])


def test_health(client):
    data = client.get("/api/health").json()
    assert data["ok"] is True
    assert "openverse" in data["sources"]


def test_ingest_then_library(client, image_dir):
    snap = _ingest(client, image_dir)
    assert snap["status"] == "done"
    assert snap["result"]["processed"] == 26

    lib = client.get("/api/library").json()
    assert lib["count"] == 26
    assert lib["images"][0]["thumb_url"].startswith("/thumbs/")
    assert "id" in lib["images"][0]


def test_clear_empties_library(client, image_dir):
    _ingest(client, image_dir)
    assert client.post("/api/library/clear").json()["count"] == 0
    assert client.get("/api/library").json()["count"] == 0


def test_fetch_job(client):
    job = client.post(
        "/api/fetch",
        json={"terms": ["eyes"], "count": 2, "min_resolution": 400, "sources": ["openverse"]},
    ).json()
    snap = _wait(client, job["job_id"])
    assert snap["status"] == "done"
    assert snap["result"]["downloaded"] >= 1
    assert client.get("/api/library").json()["count"] >= 1


def test_mosaic_physical_sizing(client, image_dir, tmp_path):
    _ingest(client, image_dir)
    target = tmp_path / "target.png"
    Image.new("RGB", (120, 120), (200, 30, 30)).save(target)

    job = client.post(
        "/api/mosaic",
        json={
            "target_path": str(target),
            "sizing": "physical",
            "canvas_w_in": 1.0,
            "canvas_h_in": 1.0,
            "tile_in": 0.5,
            "dpi": 10,  # -> 2x2 tiles, 5px each, 10x10 output
            "no_repeat": False,
        },
    ).json()
    snap = _wait(client, job["job_id"])
    assert snap["status"] == "done", snap.get("error")
    res = snap["result"]
    assert (res["cols"], res["rows"], res["tiles"]) == (2, 2, 4)
    assert (res["width"], res["height"]) == (10, 10)
    assert res["output_url"].startswith("/outputs/")
    # The generated file is downloadable through the static mount.
    assert client.get(res["output_url"]).status_code == 200


def test_mosaic_no_repeat_reports_shortfall(client, image_dir, tmp_path):
    _ingest(client, image_dir)  # 26 images
    target = tmp_path / "t.png"
    Image.new("RGB", (100, 100), (10, 200, 10)).save(target)
    job = client.post(
        "/api/mosaic",
        json={"target_path": str(target), "sizing": "grid", "cols": 8, "tile_px": 6,
              "no_repeat": True},
    ).json()
    res = _wait(client, job["job_id"])["result"]
    # 8 cols x 8 rows = 64 tiles but only 26 unique images -> short_by 38.
    assert res["unique_needed"] == res["tiles"]
    assert res["short_by"] == res["tiles"] - 26


def test_generative_job(client, image_dir):
    _ingest(client, image_dir)
    job = client.post(
        "/api/generative", json={"mode": "color_sort", "cols": 4, "tile_px": 8}
    ).json()
    snap = _wait(client, job["job_id"])
    assert snap["status"] == "done"
    assert snap["result"]["output_url"].startswith("/outputs/")


def test_fetch_job_emits_logs(client):
    job = client.post(
        "/api/fetch", json={"terms": ["eyes"], "count": 2, "sources": ["openverse"]}
    ).json()
    snap = _wait(client, job["job_id"])
    assert snap["status"] == "done"
    assert any("Planned" in line for line in snap["logs"])
    assert any("Done" in line for line in snap["logs"])


def test_save_output_copies_and_rejects_unknown(client, tmp_path):
    from collajit import config

    (config.outputs_dir() / "mosaic_x.png").write_bytes(b"PNGDATA")
    dest = tmp_path / "saved.png"
    ok = client.post("/api/save", json={"name": "mosaic_x.png", "dest": str(dest)})
    assert ok.json()["ok"] is True
    assert dest.read_bytes() == b"PNGDATA"

    missing = client.post(
        "/api/save", json={"name": "nope.png", "dest": str(tmp_path / "y.png")}
    )
    assert missing.status_code == 404


def test_suggest_missing_target_is_400(client):
    r = client.post("/api/suggest", json={"target_path": "/no/such/file.png"})
    assert r.status_code == 400


def test_job_events_stream_for_finished_job(client, image_dir):
    snap = _ingest(client, image_dir)
    text = client.get(f"/api/jobs/{snap['id']}/events").text
    assert "data:" in text and "done" in text
