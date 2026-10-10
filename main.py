"""Entry point: python main.py; python main.py --demo starts in the demo workspace (REQ-SET-007); python main.py
--self-test WORKSPACE [BOARDS] inspects one synthetic board with no window (aoi/selftest.py)."""

import sys

from PySide6.QtWidgets import QApplication

from aoi import selftest
from aoi.config import APP_NAME
from aoi.ui.demo_workspace import open_demo
from aoi.ui.errors import open_workspace
from aoi.ui.main_window import MainWindow, build_window
from aoi.ui.theme import QSS
from aoi.ui.workers import collect_on_ui_thread


def main() -> int:
    if sys.argv[1:2] == ["--self-test"]:  # the built app inspects one synthetic board, with no window (REQ-SET-012)
        return selftest.main(sys.argv[2:])
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(QSS)
    collect_on_ui_thread()  # no pool thread runs Python's cycle collector, which could delete a Qt object there
    # A refused workspace (ADR 0004): its coded message, then a picker for another (REQ-SET-016). --demo: the demo
    # workspace beside it, loaded first if it is not there, so a presenter is back in the demo in seconds (S53).
    ctx = open_demo() if "--demo" in sys.argv[1:] else open_workspace()
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
        for w in QApplication.topLevelWidgets():  # a window opened on another workspace since (the demo's, S53)
            if isinstance(w, MainWindow):
                w.ctx.close()


if __name__ == "__main__":
    sys.exit(main())
