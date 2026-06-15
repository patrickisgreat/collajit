"""Shared types for image sources plus the HTTP seam used for testing.

Sources never import ``requests`` directly — they receive an :class:`HttpClient`,
so tests inject a fake that serves canned JSON/bytes with no network.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

USER_AGENT = "collajit/0.1 (https://github.com/; image-collage tool)"


@dataclass
class ImageResult:
    """A single candidate image returned by a source (not yet downloaded)."""

    url: str  # full-resolution image URL
    source: str  # source id, e.g. "openverse"
    width: int = 0  # 0 = unknown (Met) — verified after download
    height: int = 0
    title: str = ""
    creator: str = ""
    license: str = ""
    landing_url: str = ""  # human page for attribution


class HttpClient(Protocol):
    def get_json(
        self, url: str, *, params: dict | None = None, headers: dict | None = None
    ) -> dict: ...

    def get_bytes(self, url: str, *, headers: dict | None = None) -> bytes: ...


_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RequestsHttp:
    """Default :class:`HttpClient` backed by ``requests`` (imported lazily).

    Retries rate-limit (429) and transient server errors with exponential backoff,
    honouring ``Retry-After`` when present — anonymous APIs like Openverse throttle.
    """

    def __init__(self, timeout: float = 20.0, retries: int = 2, max_backoff: float = 3.0):
        self.timeout = timeout
        self.retries = retries
        self.max_backoff = max_backoff

    def _get(self, url, params, headers):
        import time

        import requests

        h = {"User-Agent": USER_AGENT, **(headers or {})}
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = requests.get(url, params=params, headers=h, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
            else:
                if resp.status_code in _RETRYABLE_STATUS and attempt < self.retries:
                    # Cap waits so a throttled source (e.g. anonymous Openverse) fails
                    # fast and we move on to the others instead of looking frozen.
                    retry_after = float(resp.headers.get("Retry-After", 0) or 0)
                    time.sleep(min(retry_after or (0.5 * 2**attempt), self.max_backoff))
                    continue
                resp.raise_for_status()
                return resp
            time.sleep(min(0.5 * 2**attempt, self.max_backoff))
        raise last_exc or RuntimeError(f"request failed: {url}")

    def get_json(self, url, *, params=None, headers=None) -> dict:
        return self._get(url, params, headers).json()

    def get_bytes(self, url, *, headers=None) -> bytes:
        return self._get(url, None, headers).content


class ImageSource(ABC):
    """Base class for a queryable image source."""

    id: str  # stable identifier, e.g. "openverse"
    label: str  # human label for the UI

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        limit: int,
        http: HttpClient,
        min_width: int = 0,
        min_height: int = 0,
    ) -> list[ImageResult]:
        """Return up to ``limit`` candidate results for ``query``."""
