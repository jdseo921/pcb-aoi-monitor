"""Entry point: python main.py"""

import sys

from PySide6.QtWidgets import QApplication

from aoi.config import APP_NAME
from aoi.ui.errors import open_workspace
from aoi.ui.main_window import build_window
from aoi.ui.theme import QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(QSS)
    ctx = open_workspace()  # a refused workspace (ADR 0004): its coded message, then a picker for another (REQ-SET-016)
    if ctx is None:  # cancelled, or a bad settings.json
        return 2
    try:
        win = build_window(ctx)  # unhandled errors from here on: logged with the trace, one coded dialog (REQ-LOG-005)
        if win is None:  # an error while the window was built: shown and logged, the workspace closed below (#205)
            return 2
        win.showMaximized()
        return app.exec()
    finally:  # closing the window closed it already; this covers every other way out (#171, #205)
        ctx.close()


if __name__ == "__main__":
    sys.exit(main())
