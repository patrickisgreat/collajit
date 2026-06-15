"""Application entry point. ``collajit`` (console script) or ``python -m collajit``."""

from __future__ import annotations

import os
import sys

from . import config
from .library.catalog import Catalog


def main() -> int:
    # Load ./.env first so ANTHROPIC_API_KEY (and friends) are available before
    # anything that reads them — the fetch panel and Claude tagger.
    config.load_env()

    # Silence Qt's noisy "fromIccProfile: Failed to parse description" warnings —
    # many web images carry malformed colour profiles; harmless when shown.
    os.environ.setdefault("QT_LOGGING_RULES", "qt.gui.icc=false")

    # Imported lazily so headless/test imports of the package don't require a
    # display or pull in Qt unless the GUI is actually launched.
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("collajit")

    catalog = Catalog()
    window = MainWindow(catalog)
    window.show()

    try:
        return app.exec()
    finally:
        catalog.close()


if __name__ == "__main__":
    raise SystemExit(main())
