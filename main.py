"""Entry point: python main.py"""

import sys

from PySide6.QtWidgets import QApplication

from aoi.config import APP_NAME, Settings
from aoi.core.services import AppContext, ErrorReport
from aoi.errors import AoiError
from aoi.ui.errors import install_excepthook, show_error
from aoi.ui.main_window import MainWindow
from aoi.ui.theme import QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(QSS)
    try:
        ctx = AppContext(Settings.load())
    except AoiError as e:  # a v0.1 or unusable workspace (ADR 0004), or a bad settings.json: say so and stop
        show_error(None, ErrorReport.of(e))  # no workspace yet, so no log: the dialog carries the code
        return 2
    win = MainWindow(ctx)
    install_excepthook(ctx, win)  # unhandled errors: log with the trace, show a coded dialog (REQ-LOG-005)
    win.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
