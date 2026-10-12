"""The demo workspace in the app (REQ-SET-007, REQ-SET-009; S53): loaded beside the station's workspace from Settings,
or at start-up with `main.py --demo`, so a presenter whose app crashed is back in the demo in a few seconds. The
engine's side is aoi/core/demo.py; the window switches workspace in `MainWindow.switch_workspace`."""

from __future__ import annotations

from pathlib import Path

from ..config import Settings, use_workspace
from ..core import demo
from ..core.imaging import list_images
from ..core.services import AppContext, ErrorReport
from ..errors import QT_TRANSLATE_NOOP, AoiError
from .errors import log_start_failure, open_workspace, show_error


def open_demo() -> AppContext | None:
    """The AppContext `main.py --demo` starts with: the demo workspace beside the one settings.json names, loaded first
    when it is not there yet; None, after the coded message, when it cannot be, which goes to the default workspace's
    log with its detail. An error without a code, a drive full as the demo is copied say, is AOI-SET-007, its trace in
    that log, as `open_workspace` does: never the traceback a frozen build would show for an error that leaves
    `main`."""
    try:
        folder = demo.load_beside(Settings.load())
    except AoiError as e:  # a bad settings.json (AOI-SET-008, -010), a missing bundle (-015), a foreign folder (-016)
        log_start_failure(e)
        show_error(None, ErrorReport.of(e))
        return None
    except Exception as e:
        log_start_failure(e)
        show_error(None, ErrorReport.of(e, QT_TRANSLATE_NOOP("Errors", "start-up")))
        return None
    use_workspace(folder)
    return open_workspace()


def boards(root: Path) -> list[Path]:
    """The boards the demo workspace at `root` plays in a scripted run, in run order (REQ-SET-009)."""
    return list_images(root / demo.BOARDS)
