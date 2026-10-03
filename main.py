"""Entry point: python main.py"""

import sys

from PySide6.QtWidgets import QApplication

from aoi.config import APP_NAME
from aoi.ui.errors import install_excepthook, open_workspace
from aoi.ui.main_window import MainWindow
from aoi.ui.theme import QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(QSS)
    ctx = open_workspace()  # a refused workspace (ADR 0004): its coded message, then a picker for another (REQ-SET-016)
    if ctx is None:  # cancelled, or a bad settings.json
        return 2
    win = MainWindow(ctx)
    install_excepthook(ctx, win)  # unhandled errors: log with the trace, show a coded dialog (REQ-LOG-005)
    win.showMaximized()
    try:
        return app.exec()
    finally:  # closing the window closed it already; this covers an event loop that ended another way (#171)
        ctx.close()


if __name__ == "__main__":
    sys.exit(main())
