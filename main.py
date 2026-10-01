"""Entry point: python main.py"""

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from aoi.config import APP_NAME, Settings
from aoi.core.services import AppContext
from aoi.data.errors import WorkspaceError
from aoi.ui.main_window import MainWindow
from aoi.ui.theme import QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(QSS)
    try:
        ctx = AppContext(Settings.load())
    except WorkspaceError as e:  # a v0.1 or unusable workspace: say so and stop, never change it (ADR 0004)
        QMessageBox.critical(None, APP_NAME, str(e))
        return 2
    win = MainWindow(ctx)
    win.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
