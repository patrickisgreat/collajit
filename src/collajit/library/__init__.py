"""The image library: a cached catalog of source images with thumbnails and
feature vectors, plus the folder ingest that populates it."""

from .catalog import Catalog, ImageRecord
from .ingest import ingest, scan_folders

__all__ = ["Catalog", "ImageRecord", "ingest", "scan_folders"]
