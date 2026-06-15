"""FastAPI application exposing the collajit core to the UI.

Stateless-ish: one shared :class:`Catalog` (thread-safe) lives on ``app.state``.
Long operations return a ``job_id``; the UI streams progress from
``/api/jobs/{id}/events`` (SSE) or polls ``/api/jobs/{id}``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from .. import config
from ..engine import image_ops
from ..fetch import FetchRequest, run_fetch, tagger
from ..fetch.sources import SOURCES
from ..generators import generative, mosaic
from ..library import ingest as ingest_images
from ..library.catalog import Catalog
from .jobs import JobManager


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class FolderBody(BaseModel):
    path: str


class SuggestBody(BaseModel):
    target_path: str


class FetchBody(BaseModel):
    terms: list[str]
    target_path: str | None = None
    count: int = 300
    min_resolution: int = 400
    sources: list[str] | None = None
    dest_dir: str | None = None  # where to save originals; None = managed cache


class MosaicBody(BaseModel):
    target_path: str
    sizing: str = "grid"  # "grid" | "physical"
    cols: int = 40
    tile_px: int = 64
    canvas_w_in: float = 7.5
    canvas_h_in: float = 7.5
    tile_in: float = 0.25
    dpi: int = 300
    tint: float = 0.25
    no_repeat: bool = False
    fmt: str = "png"  # "png" | "jpg"


class GenerativeBody(BaseModel):
    mode: str = "color_sort"  # "color_sort" | "embedding"
    key: str = "hue"
    method: str = "pca"
    cols: int = 40
    tile_px: int = 64


class SaveBody(BaseModel):
    name: str  # output filename (basename of an output_url)
    dest: str  # absolute destination path chosen by the user


class OpenBody(BaseModel):
    name: str  # output filename to open in the OS default app (for printing)


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #
def create_app(catalog: Catalog | None = None, http=None) -> FastAPI:
    app = FastAPI(title="collajit", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # local app; the backend only binds to localhost
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.catalog = catalog or Catalog()
    app.state.jobs = JobManager()
    app.state.http = http  # injected fake in tests; None -> real requests
    app.state.lib_index = {}  # id -> source path, for serving originals

    # Static dirs (created on demand by config helpers).
    app.mount("/thumbs", StaticFiles(directory=str(config.thumbnails_dir())), name="thumbs")
    app.mount("/outputs", StaticFiles(directory=str(config.outputs_dir())), name="outputs")
    app.mount("/uploads", StaticFiles(directory=str(config.uploads_dir())), name="uploads")

    _register_routes(app)
    _mount_frontend(app)  # serve the built SPA at / when present (one-command run)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """If ``frontend/dist`` is built, serve it at ``/`` so the whole app runs from
    one ``collajit-server`` process. Registered last so /api and asset mounts win."""
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="app")


def _register_routes(app: FastAPI) -> None:
    @app.get("/api/health")
    def health():
        return {"ok": True, "sources": list(SOURCES.keys())}

    # -- library -----------------------------------------------------------
    @app.get("/api/library")
    def library(request: Request):
        cat: Catalog = request.app.state.catalog
        records = cat.all_records()
        index = {}
        images = []
        for rec in records:
            rid = hashlib.sha1(rec.path.encode()).hexdigest()[:16]
            index[rid] = rec.path
            images.append(
                {
                    "id": rid,
                    "name": Path(rec.path).name,
                    "thumb_url": f"/thumbs/{Path(rec.thumb_path).name}",
                    "width": rec.width,
                    "height": rec.height,
                    "aspect": rec.aspect,
                }
            )
        request.app.state.lib_index = index
        return {"count": len(images), "images": images}

    @app.post("/api/library/folder")
    def add_folder(body: FolderBody, request: Request):
        cat: Catalog = request.app.state.catalog
        if not Path(body.path).is_dir():
            raise HTTPException(400, f"not a folder: {body.path}")
        job_id = request.app.state.jobs.submit(
            _ingest_job, body.path, cat, label="ingest", with_progress=True
        )
        return {"job_id": job_id}

    @app.post("/api/library/clear")
    def clear(request: Request):
        request.app.state.catalog.clear()
        return {"ok": True, "count": 0}

    @app.get("/api/image/{rid}")
    def image(rid: str, request: Request):
        path = request.app.state.lib_index.get(rid)
        if not path:  # rebuild index lazily if stale
            for rec in request.app.state.catalog.all_records():
                if hashlib.sha1(rec.path.encode()).hexdigest()[:16] == rid:
                    path = rec.path
                    break
        if not path or not Path(path).exists():
            raise HTTPException(404, "image not found")
        return FileResponse(path)

    # -- uploads (target images) ------------------------------------------
    @app.post("/api/upload")
    async def upload(file: UploadFile):
        data = await file.read()
        ext = Path(file.filename or "upload.png").suffix.lower() or ".png"
        name = f"{hashlib.sha1(data).hexdigest()[:16]}{ext}"
        dest = config.uploads_dir() / name
        dest.write_bytes(data)
        return {"path": str(dest), "url": f"/uploads/{name}"}

    # -- suggest (Claude vision) ------------------------------------------
    @app.post("/api/suggest")
    def suggest(body: SuggestBody):
        if not Path(body.target_path).exists():
            raise HTTPException(400, "target image not found")
        try:
            terms = tagger.suggest_terms(body.target_path)
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"terms": terms, "has_api_key": tagger.has_api_key()}

    # -- fetch -------------------------------------------------------------
    @app.post("/api/fetch")
    def fetch(body: FetchBody, request: Request):
        terms = [t.strip() for t in body.terms if t.strip()]
        if not terms:
            raise HTTPException(400, "at least one search term is required")
        req = FetchRequest(
            terms=terms,
            target_path=body.target_path,
            count=body.count,
            min_width=body.min_resolution,
            min_height=body.min_resolution,
            sources=body.sources or list(SOURCES.keys()),
        )
        job_id = request.app.state.jobs.submit(
            _fetch_job,
            req,
            request.app.state.catalog,
            request.app.state.http,
            dest_dir=body.dest_dir or None,
            label="fetch",
            with_progress=True,
            with_logs=True,
        )
        return {"job_id": job_id}

    # -- mosaic ------------------------------------------------------------
    @app.post("/api/mosaic")
    def make_mosaic(body: MosaicBody, request: Request):
        if not Path(body.target_path).exists():
            raise HTTPException(400, "target image not found")
        job_id = request.app.state.jobs.submit(
            _mosaic_job, body, request.app.state.catalog, label="mosaic", with_progress=True
        )
        return {"job_id": job_id}

    # -- generative --------------------------------------------------------
    @app.post("/api/generative")
    def make_generative(body: GenerativeBody, request: Request):
        job_id = request.app.state.jobs.submit(
            _generative_job, body, request.app.state.catalog, label="generative", with_progress=True
        )
        return {"job_id": job_id}

    # -- save a generated output to a user-chosen path ---------------------
    @app.post("/api/save")
    def save_output(body: SaveBody):
        # Only allow copying files we generated (basename inside outputs_dir).
        src = config.outputs_dir() / Path(body.name).name
        if not src.exists():
            raise HTTPException(404, "output not found")
        try:
            shutil.copyfile(src, body.dest)
        except OSError as exc:
            raise HTTPException(400, f"could not save: {exc}") from exc
        return {"ok": True, "dest": body.dest}

    @app.post("/api/open_output")
    def open_output(body: OpenBody):
        # Open a generated image in the OS default app (e.g. Preview) so the user
        # can print at full resolution through the printer's own driver dialog.
        src = config.outputs_dir() / Path(body.name).name
        if not src.exists():
            raise HTTPException(404, "output not found")
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(src)])
            elif sys.platform.startswith("win"):
                os.startfile(str(src))  # noqa: S606 - local file we created
            else:
                subprocess.Popen(["xdg-open", str(src)])
        except OSError as exc:
            raise HTTPException(400, f"could not open: {exc}") from exc
        return {"ok": True}

    # -- jobs --------------------------------------------------------------
    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str, request: Request):
        job = request.app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown job")
        return job.snapshot()

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str, request: Request):
        return StreamingResponse(
            request.app.state.jobs.events(job_id), media_type="text/event-stream"
        )


# --------------------------------------------------------------------------- #
# Job bodies (run on worker threads)
# --------------------------------------------------------------------------- #
def _ingest_job(folder: str, catalog: Catalog, progress=None) -> dict:
    processed = ingest_images([folder], catalog, progress=progress)
    return {"processed": processed, "catalog_total": catalog.count()}


def _fetch_job(req: FetchRequest, catalog: Catalog, http, dest_dir=None, progress=None, log=None) -> dict:
    result = run_fetch(req, catalog, dest_dir=dest_dir, http=http, progress=progress, log=log)
    return asdict(result)


def _save_image(img: Image.Image, path: Path, *, dpi: int | None, fmt: str) -> None:
    kwargs = {"dpi": (dpi, dpi)} if dpi else {}
    if fmt == "jpg":
        matte = Image.new("RGB", img.size, (255, 255, 255))
        matte.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[3])
        matte.save(path, quality=95, **kwargs)
    else:
        img.convert("RGBA").save(path, **kwargs)


def _mosaic_job(body: MosaicBody, catalog: Catalog, progress=None) -> dict:
    records, features = catalog.feature_matrix()
    if not records:
        raise ValueError("the library is empty — add or fetch images first")
    target = image_ops.load_image(body.target_path, mode="RGB")

    if body.sizing == "physical":
        spec = mosaic.PhysicalSpec(body.canvas_w_in, body.canvas_h_in, body.tile_in, body.dpi)
        opts = spec.to_options(tint=body.tint, no_repeat=body.no_repeat)
        cols, rows, dpi = spec.cols, spec.rows, body.dpi
    else:
        opts = mosaic.MosaicOptions(
            cols=body.cols,
            tile_px=body.tile_px,
            tint=body.tint,
            max_uses=1 if body.no_repeat else None,
        )
        cols = opts.cols
        rows = max(1, round(cols / (target.width / target.height)))
        opts.rows = rows
        dpi = None

    img = mosaic.build_mosaic(target, records, features, opts, progress=progress)
    fmt = "jpg" if body.fmt == "jpg" else "png"
    name = f"mosaic_{uuid.uuid4().hex}.{fmt}"
    _save_image(img, config.outputs_dir() / name, dpi=dpi, fmt=fmt)

    tiles = cols * rows
    result = {
        "output_url": f"/outputs/{name}",
        "width": img.width,
        "height": img.height,
        "cols": cols,
        "rows": rows,
        "tiles": tiles,
        "unique_needed": tiles if body.no_repeat else 0,
        "library_count": len(records),
        "short_by": max(0, tiles - len(records)) if body.no_repeat else 0,
    }
    if body.sizing == "physical":  # physical size lets the UI print at true inches
        result["inches_w"] = body.canvas_w_in
        result["inches_h"] = body.canvas_h_in
        result["dpi"] = body.dpi
    return result


def _generative_job(body: GenerativeBody, catalog: Catalog, progress=None) -> dict:
    records, features = catalog.feature_matrix()
    if not records:
        raise ValueError("the library is empty — add or fetch images first")
    if body.mode == "embedding":
        img = generative.embedding_layout(
            records, features, cols=body.cols, tile_px=body.tile_px,
            method=body.method, progress=progress,
        )
    else:
        img = generative.color_sort_layout(
            records, cols=body.cols, tile_px=body.tile_px, key=body.key, progress=progress
        )
    name = f"layout_{uuid.uuid4().hex}.png"
    _save_image(img, config.outputs_dir() / name, dpi=None, fmt="png")
    return {"output_url": f"/outputs/{name}", "width": img.width, "height": img.height}


def run(host: str = "127.0.0.1", port: int = 8756) -> None:
    """Console entry point: launch the API server (loads .env first)."""
    import uvicorn

    config.load_env()
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    run()
