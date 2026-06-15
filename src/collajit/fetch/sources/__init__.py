"""Image-source adapters. Each maps a text query to candidate :class:`ImageResult`s.

All current sources are keyless and return Creative-Commons / public-domain
imagery, so fetched results are safe to display.
"""

from .base import HttpClient, ImageResult, ImageSource, RequestsHttp
from .met import MetSource
from .openverse import OpenverseSource
from .pexels import PexelsSource
from .wikimedia import WikimediaSource

#: Registry keyed by the stable id used in the UI and FetchRequest.sources.
SOURCES: dict[str, type[ImageSource]] = {
    PexelsSource.id: PexelsSource,
    OpenverseSource.id: OpenverseSource,
    WikimediaSource.id: WikimediaSource,
    MetSource.id: MetSource,
}

__all__ = [
    "HttpClient",
    "ImageResult",
    "ImageSource",
    "RequestsHttp",
    "PexelsSource",
    "OpenverseSource",
    "WikimediaSource",
    "MetSource",
    "SOURCES",
]
