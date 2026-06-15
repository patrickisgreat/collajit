"""Pexels — free, high-volume photo API (royalty-free, commercial use OK).

Needs a free API key in ``PEXELS_API_KEY`` (env / .env). Returns up to 80 photos
per request and paginates, so it comfortably exceeds thousands of images per day —
the best keyed source for mosaic volume. Without a key the source is skipped.
"""

from __future__ import annotations

import os

from .base import HttpClient, ImageResult, ImageSource

_ENDPOINT = "https://api.pexels.com/v1/search"
_PER_PAGE = 80  # Pexels max per request
_MAX_PAGES = 40  # up to ~3200 results per query


class PexelsSource(ImageSource):
    id = "pexels"
    label = "Pexels (photos, key)"

    def search(self, query, *, limit, http: HttpClient, min_width=0, min_height=0):
        key = os.environ.get("PEXELS_API_KEY")
        if not key:
            return []  # no key configured → skip gracefully
        headers = {"Authorization": key}  # Pexels uses the raw key, not "Bearer"
        per_page = min(max(limit, 1), _PER_PAGE)
        results: list[ImageResult] = []
        page = 1
        while len(results) < limit and page <= _MAX_PAGES:
            data = http.get_json(
                _ENDPOINT,
                params={"query": query, "per_page": per_page, "page": page},
                headers=headers,
            )
            photos = data.get("photos") or []
            if not photos:
                break
            for p in photos:
                url = (p.get("src") or {}).get("original")
                if not url:
                    continue
                w = int(p.get("width") or 0)
                h = int(p.get("height") or 0)
                if w and h and (w < min_width or h < min_height):
                    continue
                results.append(
                    ImageResult(
                        url=url,
                        source=self.id,
                        width=w,
                        height=h,
                        title=p.get("alt") or "",
                        creator=p.get("photographer") or "",
                        license="Pexels License",
                        landing_url=p.get("url") or "",
                    )
                )
            if not data.get("next_page"):
                break
            page += 1
        return results[:limit]
