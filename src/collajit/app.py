"""Application entry point. ``collajit`` (console script) or ``python -m collajit``."""

from __future__ import annotations

import sys

from .library.catalog import Catalog


def main() -> int:
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
