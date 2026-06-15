"""Wikimedia Commons — huge, freely-licensed media library. Keyless MediaWiki API.

Uses a search generator over the File namespace. We deliberately request only
``url|size|mime`` (NOT ``extmetadata``): pulling extmetadata for 50 files per page
made each request take ~10-14s, which dominated fetch time across 12 pages. License
is recorded generically; the description URL is the per-file attribution page.
"""

from __future__ import annotations

import time

from .base import HttpClient, ImageResult, ImageSource

_ENDPOINT = "https://commons.wikimedia.org/w/api.php"
_IMAGE_MIME_PREFIX = "image/"
_MAX_PAGES = 16  # follow MediaWiki `continue` until we hit `limit`
_PAGE_DELAY = 0.25  # be polite — rapid pagination trips Wikimedia's 429 limiter


class WikimediaSource(ImageSource):
    id = "wikimedia"
    label = "Wikimedia Commons"

    def search(self, query, *, limit, http: HttpClient, min_width=0, min_height=0):
        per_page = min(max(limit, 1), 50)
        base = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": "6",  # File:
            "gsrsearch": query,
            "gsrlimit": str(per_page),
            "prop": "imageinfo",
            "iiprop": "url|size|mime",  # light — extmetadata is the slow part
        }
        results: list[ImageResult] = []
        cont: dict = {}
        pages_fetched = 0
        while len(results) < limit and pages_fetched < _MAX_PAGES:
            if pages_fetched:
                time.sleep(_PAGE_DELAY)
            try:
                data = http.get_json(_ENDPOINT, params={**base, **cont})
            except Exception:
                break  # rate-limited / transient — keep the results gathered so far
            pages = (data.get("query") or {}).get("pages") or {}
            for page in pages.values():
                result = self._parse_page(page, min_width, min_height)
                if result is not None:
                    results.append(result)
            pages_fetched += 1
            cont = data.get("continue") or {}
            if not cont:
                break
        return results[:limit]

    def _parse_page(self, page, min_width, min_height) -> ImageResult | None:
        infos = page.get("imageinfo") or []
        if not infos:
            return None
        info = infos[0]
        if not str(info.get("mime", "")).startswith(_IMAGE_MIME_PREFIX):
            return None
        url = info.get("url")
        if not url:
            return None
        w = int(info.get("width") or 0)
        h = int(info.get("height") or 0)
        if w and h and (w < min_width or h < min_height):
            return None
        return ImageResult(
            url=url,
            source=self.id,
            width=w,
            height=h,
            title=page.get("title") or "",
            license="Wikimedia Commons",
            landing_url=info.get("descriptionurl") or "",
        )
