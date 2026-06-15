"""The Metropolitan Museum of Art — open-access, public-domain artworks. Keyless.

Two-step API: a search returns object IDs, then each object must be fetched for its
image URL. The object endpoint doesn't report pixel dimensions, so size filtering
defers to the downloader (which checks decoded dimensions). Detail fetches are
capped to keep the request count bounded.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .base import HttpClient, ImageResult, ImageSource

_SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1/search"
_OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/"

#: Hard cap on per-object detail fetches per search (each is a request).
_MAX_DETAIL_FETCHES = 150


class MetSource(ImageSource):
    id = "met"
    label = "The Met (public domain)"

    def search(self, query, *, limit, http: HttpClient, min_width=0, min_height=0):
        data = http.get_json(_SEARCH, params={"q": query, "hasImages": "true"})
        object_ids = data.get("objectIDs") or []
        if not object_ids:
            return []

        budget = min(limit * 2, _MAX_DETAIL_FETCHES)  # over-fetch; many lack PD images

        def fetch_obj(oid):
            try:
                return http.get_json(f"{_OBJECT}{oid}")
            except Exception:
                return None

        # Fetch object details concurrently — sequential was the slow part (~1 req each).
        with ThreadPoolExecutor(max_workers=8) as pool:
            objects = list(pool.map(fetch_obj, object_ids[:budget]))

        results: list[ImageResult] = []
        for obj in objects:
            if len(results) >= limit:
                break
            if not obj:
                continue
            image = obj.get("primaryImage")
            if not image or not obj.get("isPublicDomain"):
                continue
            results.append(
                ImageResult(
                    url=image,
                    source=self.id,
                    title=obj.get("title") or "",
                    creator=obj.get("artistDisplayName") or "",
                    license="Public Domain (CC0)",
                    landing_url=obj.get("objectURL") or "",
                )
            )
        return results
