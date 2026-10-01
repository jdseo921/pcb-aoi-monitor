"""Entry point: python main.py"""

import sys

from PySide6.QtWidgets import QApplication

from aoi.config import APP_NAME, Settings
from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.theme import QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(QSS)
    ctx = AppContext(Settings.load())
    win = MainWindow(ctx)
    win.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
