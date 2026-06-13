"""Control panels for the three art modes. Each emits ``generateRequested(dict)``
with its parameters; the main window runs the matching generator off-thread."""

from .freeform_panel import FreeformPanel
from .generative_panel import GenerativePanel
from .mosaic_panel import MosaicPanel

__all__ = ["MosaicPanel", "GenerativePanel", "FreeformPanel"]
