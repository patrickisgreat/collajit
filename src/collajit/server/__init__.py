"""Local HTTP backend (FastAPI) that exposes the Python core to the Tauri/web UI.

The UI never imports the engine directly — it calls this API. Long operations
(ingest, fetch, mosaic, generative) run as background *jobs* with live progress
streamed over SSE. See :func:`collajit.server.app.create_app`.
"""

from .app import create_app

__all__ = ["create_app"]
