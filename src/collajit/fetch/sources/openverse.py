"""Openverse — ~700M Creative-Commons images aggregated across many providers.

Anonymous requests now return 401, so Openverse needs an API key. Set
``OPENVERSE_CLIENT_ID`` / ``OPENVERSE_CLIENT_SECRET`` (in ``.env``) and this module
exchanges them for a bearer token (client-credentials grant), caches it until it
expires, and refreshes automatically. Without credentials it falls back to an
(unauthenticated) request that the caller handles gracefully.

Register credentials:
    curl -X POST https://api.openverse.org/v1/auth_tokens/register/ \\
      -H "Content-Type: application/json" \\
      -d '{"name":"collajit","description":"personal collage app","email":"you@example.com"}'
Then verify the email Openverse sends, and paste client_id/secret into .env.
"""

from __future__ import annotations

import os
import threading
import time

from .base import HttpClient, ImageResult, ImageSource

_ENDPOINT = "https://api.openverse.org/v1/images/"
_TOKEN_ENDPOINT = "https://api.openverse.org/v1/auth_tokens/token/"
_MAX_PAGES = 12  # paginate until we hit `limit` or run out

_token_lock = threading.Lock()
_token_cache: dict = {"token": None, "expires_at": 0.0}


def _get_access_token() -> str | None:
    """Return a cached/refreshed bearer token, or None if no creds / on failure."""
    client_id = os.environ.get("OPENVERSE_CLIENT_ID")
    client_secret = os.environ.get("OPENVERSE_CLIENT_SECRET")
    if not (client_id and client_secret):
        return None
    now = time.time()
    with _token_lock:
        if now < _token_cache["expires_at"]:
            return _token_cache["token"]  # valid token, or a recent-failure cooldown
        try:
            import requests

            resp = requests.post(
                _TOKEN_ENDPOINT,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            _token_cache["token"] = data.get("access_token")
            _token_cache["expires_at"] = now + float(data.get("expires_in", 3600)) - 30
        except Exception:
            _token_cache["token"] = None
            _token_cache["expires_at"] = now + 60  # cooldown; don't hammer the token endpoint
        return _token_cache["token"]


class OpenverseSource(ImageSource):
    id = "openverse"
    label = "Openverse (photos, needs key)"

    def search(self, query, *, limit, http: HttpClient, min_width=0, min_height=0):
        token = _get_access_token()
        headers = {"Authorization": f"Bearer {token}"} if token else None
        page_size = min(max(limit, 1), 240)  # Openverse caps page_size at 240
        results: list[ImageResult] = []
        page = 1
        while len(results) < limit and page <= _MAX_PAGES:
            data = http.get_json(
                _ENDPOINT,
                params={
                    "q": query,
                    "page_size": page_size,
                    "page": page,
                    "mature": "false",
                },
                headers=headers,
            )
            items = data.get("results") or []
            if not items:
                break
            for item in items:
                url = item.get("url")
                if not url:
                    continue
                w = int(item.get("width") or 0)
                h = int(item.get("height") or 0)
                if w and h and (w < min_width or h < min_height):
                    continue
                results.append(
                    ImageResult(
                        url=url,
                        source=self.id,
                        width=w,
                        height=h,
                        title=item.get("title") or "",
                        creator=item.get("creator") or "",
                        license=item.get("license") or "",
                        landing_url=item.get("foreign_landing_url") or "",
                    )
                )
            page_count = data.get("page_count")
            if (page_count is not None and page >= page_count) or len(items) < page_size:
                break
            page += 1
        return results[:limit]
