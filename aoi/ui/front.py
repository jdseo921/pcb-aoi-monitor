"""A second start brings the copy of the app already open on the workspace to the front (A6 of the 2026-10
business-readiness brief, F12; REQ-SET-019).

The copy that holds the workspace's lock notes its process and its main window beside the lock
(`AppContext.note_window`); a second start, refused by the lock, reads that note (`running_copy`) and asks the system
to show that window and make it the active one. A first copy still starting (its database upgraded, its pages built)
has no window yet: the second start waits for it, up to WAIT_S. Only Windows lets one process do that for another's
window, through user32, and it may still refuse (a copy that stopped answering, another user's session, the focus taken
meanwhile): `bring_to_front` is then False and the caller says in one sentence where the app is open
(`errors.show_already_open`). No network and no socket: a second copy finds the first through the workspace folder
alone.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Protocol

from ..core.services import RunningCopy

WAIT_S = 15.0  # how long a second start waits for a first copy still starting to show its window
POLL_S = 0.25  # how often it reads the first copy's note meanwhile


class System(Protocol):
    """What the system lets a process do with another process's window."""

    def owner(self, window: int) -> int | None:
        """The process id of `window`, or None when it is no window (closed since it was noted)."""
        ...

    def responding(self, window: int) -> bool:
        """False when the copy that owns `window` has stopped answering the system: asking it to show itself would wait
        on it."""
        ...

    def restore(self, window: int) -> None:
        """Show `window` as it was before it was minimised, without waiting on its copy; one not minimised stays."""
        ...

    def activate(self, window: int) -> bool:
        """Make `window`, or the dialog its copy has open over it, the active one, in front; False when the system
        refuses or makes another the active one."""
        ...


def bring_to_front(
    read: Callable[[], RunningCopy | None], system: System | None = None, wait: float | None = None
) -> bool:
    """True when the window of the copy of the app that has the workspace open, as `read` gives it (None: no copy holds
    the workspace), is now in front: a window still of that process, restored when minimised and made the active
    window. A copy with no window yet is read again every POLL_S, up to `wait` seconds (WAIT_S). False when there is no
    such window, the system offers no way (any but Windows), the copy does not answer or the system refuses."""
    system = system if system is not None else this_system()
    if system is None:
        return False
    copy, end = read(), time.monotonic() + (WAIT_S if wait is None else wait)
    while copy is not None and not copy.window and time.monotonic() < end:
        time.sleep(POLL_S)
        copy = read()
    if copy is None or not copy.window or system.owner(copy.window) != copy.pid:
        return False
    if not system.responding(copy.window):
        return False
    system.restore(copy.window)
    return system.activate(copy.window)


def this_system() -> System | None:
    """Windows' user32, or None on a system that lets no process bring another's window to the front."""
    if sys.platform == "win32":
        return _Windows()
    return None


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _SW_RESTORE = 9
    _CONFIRM_S = 1.0  # Windows makes another thread's window the active one a moment after it agrees to

    class _Windows:
        """user32's calls for another process's top-level window: IsWindow, GetWindowThreadProcessId, IsHungAppWindow,
        IsIconic, ShowWindowAsync, GetLastActivePopup, SetForegroundWindow and GetForegroundWindow, with their argument
        and result types declared."""

        def __init__(self) -> None:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._is_window = user32.IsWindow
            self._is_window.argtypes, self._is_window.restype = [wintypes.HWND], wintypes.BOOL
            self._owner = user32.GetWindowThreadProcessId
            self._owner.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            self._owner.restype = wintypes.DWORD
            self._hung = user32.IsHungAppWindow
            self._hung.argtypes, self._hung.restype = [wintypes.HWND], wintypes.BOOL
            self._is_iconic = user32.IsIconic
            self._is_iconic.argtypes, self._is_iconic.restype = [wintypes.HWND], wintypes.BOOL
            self._show = user32.ShowWindowAsync  # ShowWindow would wait on the other copy's thread
            self._show.argtypes, self._show.restype = [wintypes.HWND, ctypes.c_int], wintypes.BOOL
            self._popup = user32.GetLastActivePopup
            self._popup.argtypes, self._popup.restype = [wintypes.HWND], wintypes.HWND
            self._set_foreground = user32.SetForegroundWindow
            self._set_foreground.argtypes, self._set_foreground.restype = [wintypes.HWND], wintypes.BOOL
            self._foreground = user32.GetForegroundWindow
            self._foreground.argtypes, self._foreground.restype = [], wintypes.HWND

        def owner(self, window: int) -> int | None:
            if not self._is_window(window):
                return None
            pid = wintypes.DWORD(0)
            return int(pid.value) if self._owner(window, ctypes.byref(pid)) else None

        def responding(self, window: int) -> bool:
            return not self._hung(window)

        def restore(self, window: int) -> None:
            if self._is_iconic(window):
                self._show(window, _SW_RESTORE)

        def activate(self, window: int) -> bool:
            target = self._popup(window) or window  # a dialog the copy has open over its window, else the window
            if not self._set_foreground(target):
                return False
            end = time.monotonic() + _CONFIRM_S
            while self._foreground() != target:  # refused after all: Windows flashes its taskbar button instead
                if time.monotonic() > end:
                    return False
                time.sleep(0.05)
            return True
