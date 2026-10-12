"""F12 of the 2026-10 business-readiness brief, item A6: starting the app while it is already open on the same workspace
brings the open copy's window to the front; where the system cannot do that, one plain sentence with one button says
so, never a folder picker (REQ-SET-019, #204)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import demo
from aoi.core.services import AppContext, RunningCopy, running_copy, workspace_in_use
from aoi.data import credentials
from aoi.data.workspace_lock import LOCK_NAME
from aoi.errors import CODES, AoiError
from aoi.ui import demo_workspace, front
from aoi.ui import errors as ui_errors
from aoi.ui.errors import AlreadyOpenBox, ErrorBox
from aoi.ui.main_window import MainWindow
from tests.test_demo_path_messages import banned
from tests.test_demo_ui import shown_window, station
from tests.test_explain import not_words
from tests.test_workspace_lock import FIRST_COPY, ROOT

WINDOW = 0x2A0F6  # a window handle as Windows gives one: any number the fake system below knows
BROUGHT = ["owner", "responding", "restore", "activate"]  # what bringing a window to the front asks the system


class FakeSystem:
    """The system's window calls, as Windows answers them for `windows` (handle -> process id); what was asked, in
    order; `refuse` makes it refuse to bring a window to the front, as Windows can, and `hung` says the copy that owns
    the window has stopped answering."""

    def __init__(self, windows: dict[int, int], refuse: bool = False, hung: bool = False) -> None:
        self.windows, self.refuse, self.hung = windows, refuse, hung
        self.asked: list[tuple[str, int]] = []

    def owner(self, window: int) -> int | None:
        self.asked.append(("owner", window))
        return self.windows.get(window)

    def responding(self, window: int) -> bool:
        self.asked.append(("responding", window))
        return not self.hung

    def restore(self, window: int) -> None:
        self.asked.append(("restore", window))

    def activate(self, window: int) -> bool:
        self.asked.append(("activate", window))
        return not self.refuse


@pytest.fixture
def second_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[AppContext, list[AlreadyOpenBox], list[object], list[str]]]:
    """The first copy open on the workspace settings.json names, its window noted; and what a second start shows:
    the one-sentence boxes, the folder pickers, the error dialogs (each recorded, none shown). A first copy still
    starting is waited for 0.3 s here, not front.WAIT_S."""
    ws = tmp_path / "ws"
    Settings(workspace=str(ws), device="cpu").save()
    first = AppContext(Settings.load())
    first.note_window(WINDOW)
    boxes: list[AlreadyOpenBox] = []
    pickers: list[object] = []
    errors: list[str] = []
    monkeypatch.setattr(AlreadyOpenBox, "exec", lambda box: boxes.append(box) or 0)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a: pickers.append(a) or ""))
    monkeypatch.setattr(ErrorBox, "exec", lambda box: errors.append(box.windowTitle()) or 0)
    monkeypatch.setattr(front, "WAIT_S", 0.3)
    monkeypatch.setattr(front, "POLL_S", 0.02)
    yield first, boxes, pickers, errors
    first.close()


def test_req_set_019_the_copy_open_notes_its_process_and_window(ctx: AppContext) -> None:
    """The lock names the copy that holds it from the moment it is taken, its window once noted; a second start finds
    them there, while the first copy runs."""
    assert running_copy(ctx.settings.root) == RunningCopy(os.getpid(), 0)
    ctx.note_window(WINDOW)
    assert running_copy(ctx.settings.root) == RunningCopy(os.getpid(), WINDOW)
    ctx.note_window(7)  # a shorter note leaves nothing of the longer one before
    assert running_copy(ctx.settings.root) == RunningCopy(os.getpid(), 7)


@pytest.mark.parametrize("held", [b"", b"not json", b'{"pid": "1", "window": 2}', b'{"pid": -1, "window": 2}'])
def test_req_set_019_a_lock_file_without_a_note_names_no_copy(tmp_path: Path, held: bytes) -> None:
    """A lock file from before this version (empty) or changed by hand names no copy: the second start says so."""
    (tmp_path / ".aoi.lock").write_bytes(held)
    assert running_copy(tmp_path) is None
    assert running_copy(tmp_path / "gone") is None


def test_req_set_019_a_workspace_is_in_use_only_while_its_lock_is_held(tmp_path: Path, workspace: Settings) -> None:
    """Asked by the lock itself, not by the note a copy that ended leaves behind; asking creates nothing and lets go of
    nothing, so the copy open keeps the workspace."""
    assert not workspace_in_use(tmp_path / "gone") and not (tmp_path / "gone").exists()
    assert not workspace_in_use(tmp_path) and not (tmp_path / LOCK_NAME).exists()
    first = AppContext(workspace)
    assert workspace_in_use(workspace.workspace) and workspace_in_use(workspace.workspace)
    with pytest.raises(AoiError) as refused:
        AppContext(Settings(workspace=workspace.workspace, device="cpu"))
    assert refused.value.code == "AOI-SET-019"
    first.close()
    assert not workspace_in_use(workspace.workspace) and running_copy(workspace.workspace) is not None
    AppContext(workspace).close()


def test_req_set_019_a_second_start_brings_the_open_copy_to_the_front(
    second_start: tuple[AppContext, list[AlreadyOpenBox], list[object], list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path where the system can (Windows): the second start restores the first copy's window, makes it the active
    one and ends, with no message, no folder picker and nothing changed in the workspace."""
    first, boxes, pickers, errors = second_start
    system = FakeSystem({WINDOW: os.getpid()})
    monkeypatch.setattr(front, "this_system", lambda: system)
    before = sorted(p.name for p in first.settings.root.iterdir())
    assert ui_errors.open_workspace() is None
    assert system.asked == [(call, WINDOW) for call in BROUGHT]
    assert boxes == [] and pickers == [] and errors == []
    assert sorted(p.name for p in first.settings.root.iterdir()) == before
    first.audit("probe", "workspace", None, None, None)  # the first copy still works on its workspace


def test_req_set_019_a_second_start_waits_for_a_copy_still_starting(
    second_start: tuple[AppContext, list[AlreadyOpenBox], list[object], list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second double-click while the first copy still starts (its database upgraded, its pages built), before it
    shows a window: the second start waits for the window, then brings it to the front, with no message."""
    first, boxes, pickers, errors = second_start
    first.note_window(0)
    system = FakeSystem({WINDOW: os.getpid()})
    monkeypatch.setattr(front, "this_system", lambda: system)
    monkeypatch.setattr(front, "WAIT_S", 10.0)
    shows = threading.Timer(0.3, first.note_window, (WINDOW,))
    started = time.monotonic()
    shows.start()
    try:
        assert ui_errors.open_workspace() is None
    finally:
        shows.join()
    assert 0.3 <= time.monotonic() - started < 10
    assert system.asked == [(call, WINDOW) for call in BROUGHT] and boxes == [] and pickers == [] and errors == []


@pytest.mark.parametrize(
    "case",
    ["no-system", "refused", "window-closed", "window-of-another-process", "not-answering", "no-window-in-time"],
)
def test_req_set_019_where_it_cannot_one_sentence_and_one_button(
    case: str,
    second_start: tuple[AppContext, list[AlreadyOpenBox], list[object], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The path where the system cannot: any system but Windows, Windows refusing, the window noted closed since or
    now another process's (its handle reused), a first copy that does not answer, or one that shows no window in the
    time waited. One box with the code in its title, one plain sentence and one OK; never a folder picker, never the
    error dialog."""
    first, boxes, pickers, errors = second_start
    pid = os.getpid()
    system, asked = {  # the system, and what the second start asked it
        "no-system": (None, []),
        "refused": (FakeSystem({WINDOW: pid}, refuse=True), BROUGHT),
        "window-closed": (FakeSystem({}), ["owner"]),
        "window-of-another-process": (FakeSystem({WINDOW: pid + 1}), ["owner"]),
        "not-answering": (FakeSystem({WINDOW: pid}, hung=True), ["owner", "responding"]),
        "no-window-in-time": (FakeSystem({0: pid}), []),
    }[case]
    if case == "no-window-in-time":
        first.note_window(0)
    monkeypatch.setattr(front, "this_system", lambda: system)
    assert ui_errors.open_workspace() is None
    (box,) = boxes
    assert pickers == [] and errors == []
    assert box.windowTitle() == "AOI-SET-019 App already open"
    assert box.standardButtons() == QMessageBox.StandardButton.Ok and box.icon() == QMessageBox.Icon.Information
    text = box.text()
    assert text == CODES["AOI-SET-019"].what and "\n" not in text
    assert text.count(". ") == 0 and text.endswith(".")  # one sentence
    assert "switch to it on the taskbar" in text and banned(text) == [] and not_words(text) == []
    assert [call for call, _window in system.asked] == asked if system else asked == []
    box.deleteLater()


def test_req_set_019_a_copy_that_closes_while_the_second_start_asks_lets_it_open(
    second_start: tuple[AppContext, list[AlreadyOpenBox], list[object], list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first copy closes while the second start asks for its window: the workspace is free, so the second start
    opens it after all, with no message saying it is open."""
    first, boxes, pickers, errors = second_start

    def closes(*_args: object, **_kwargs: object) -> bool:
        first.close()
        return False

    monkeypatch.setattr(front, "bring_to_front", closes)
    ctx = ui_errors.open_workspace()
    try:
        assert ctx is not None and ctx.settings.root == first.settings.root
        assert boxes == [] and pickers == [] and errors == []
    finally:
        if ctx is not None:
            ctx.close()


def test_req_set_019_another_copys_workspace_is_never_a_folder_picker_code(ctx: AppContext) -> None:
    """The lock refuses with AOI-SET-019, which the start-up handles apart, not with a code the folder picker follows;
    AOI-SET-012 stays for a database another program (a database tool) holds."""
    with pytest.raises(AoiError) as refused:
        AppContext(Settings(workspace=ctx.settings.workspace, device="cpu"))
    assert refused.value.code == ui_errors.ALREADY_OPEN == "AOI-SET-019"
    assert ui_errors.ALREADY_OPEN not in ui_errors.ANOTHER_WORKSPACE and "AOI-SET-012" in ui_errors.ANOTHER_WORKSPACE
    assert all("another copy of this app" not in CODES[code].action for code in ("AOI-SET-012", "AOI-SET-013"))


@pytest.mark.parametrize("brought", [True, False], ids=["brought-forward", "one-sentence"])
def test_req_set_019_switching_to_a_workspace_another_copy_has_open_leaves_this_window(
    qtbot: QtBot, demo_bundle: Path, monkeypatch: pytest.MonkeyPatch, brought: bool
) -> None:
    """Load Demo Workspace while another copy has the demo open: that copy comes to the front, or one sentence over
    this window says it is open, and this window stays on its own workspace, nothing closed or opened again."""
    monkeypatch.setenv("AOI_DEMO_BUNDLE", str(demo_bundle))
    win = station(qtbot)
    root = win.ctx.settings.root
    folder = demo.load_beside(win.ctx.settings, credentials.MemoryCredentials())
    other = AppContext(Settings(workspace=str(folder), device="cpu"))
    other.note_window(WINDOW)
    system = FakeSystem({WINDOW: os.getpid()}) if brought else None
    monkeypatch.setattr(front, "this_system", lambda: system)
    boxes: list[AlreadyOpenBox] = []
    monkeypatch.setattr(AlreadyOpenBox, "exec", lambda box: boxes.append(box) or 0)
    try:
        qtbot.mouseClick(win.pages["Settings"].demo.btn_load, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
        assert shown_window() is win and not win.switched and win.ctx.settings.root == root and not win.in_demo
        win.ctx.audit("probe", "workspace", None, None, None)  # this window's workspace is still open
        if brought:
            assert system is not None and system.asked == [(call, WINDOW) for call in BROUGHT] and boxes == []
        else:
            (box,) = boxes
            assert box.windowTitle() == "AOI-SET-019 App already open" and box.parent() is win
    finally:
        other.close()
        win.close()
        win.ctx.close()
        win.deleteLater()


def test_req_set_019_the_demo_entry_brings_the_demo_already_open_forward(
    tmp_path: Path, demo_bundle: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """The Start menu's demo entry (`main.py --demo`) while the demo is open: the demo's window comes to the front and
    the second start ends, with no message and the demo as it was."""
    monkeypatch.setenv("AOI_DEMO_BUNDLE", str(demo_bundle))
    Settings(workspace=str(tmp_path / "ws"), device="cpu").save()
    folder = demo.load_beside(Settings.load(), credentials.MemoryCredentials())
    first = AppContext(Settings(workspace=str(folder), device="cpu"))
    first.note_window(WINDOW)
    system = FakeSystem({WINDOW: os.getpid()})
    monkeypatch.setattr(front, "this_system", lambda: system)
    try:
        assert demo_workspace.open_demo() is None
        assert system.asked == [(call, WINDOW) for call in BROUGHT] and dialogs == []
        first.audit("probe", "workspace", None, None, None)
    finally:
        first.close()


def test_req_set_019_another_process_is_found_by_its_note(workspace: Settings) -> None:
    """A first copy in another process: the second start reads its process id from the lock, as a real second
    double-click on the app would."""
    proc = subprocess.Popen(
        [sys.executable, "-c", FIRST_COPY, workspace.workspace],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        word, pid = proc.stdout.readline().split()  # the first copy's own id (in a venv, not the launcher's)
        assert word == "ready" and workspace_in_use(workspace.workspace)
        assert running_copy(workspace.workspace) == RunningCopy(int(pid), 0)
    finally:
        proc.kill()
        proc.wait()


def test_req_set_019_the_main_window_notes_itself_once_shown(qtbot: QtBot, ctx: AppContext) -> None:
    """The window notes its handle beside the lock when first shown, so a second start finds the window in use."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    assert running_copy(ctx.settings.root) == RunningCopy(os.getpid(), 0)
    win.show()  # the show event comes at once, before show() returns
    assert running_copy(ctx.settings.root) == RunningCopy(os.getpid(), int(win.winId()))


# A first copy's window in another process, with Qt's own Windows platform (the tests run offscreen, where winId() is
# no window of the system's): shown minimised, its process id and window handle printed; it ends when stdin closes.
QT_WINDOW = """
import os
import sys
import threading
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication(sys.argv)
window = QWidget()
window.setWindowTitle("AOI second start")
window.resize(320, 200)
window.showMinimized()
QTimer.singleShot(300, lambda: print("ready", os.getpid(), int(window.winId()), flush=True))
threading.Thread(target=lambda: (sys.stdin.read(), os._exit(0)), daemon=True).start()
app.exec()
"""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' user32 is the only system that brings a window forward")
def test_req_set_019_windows_restores_the_window_of_another_process() -> None:
    """The real calls on Windows, on a minimised Qt window of another process: its owner is that process, it is a
    top-level window, it answers, and bringing it to the front restores it, with a call that does not wait on that
    process; when Windows agrees to make it the active window, it is the window in front."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsIconic.argtypes, user32.IsIconic.restype = [wintypes.HWND], wintypes.BOOL
    user32.GetAncestor.argtypes, user32.GetAncestor.restype = [wintypes.HWND, wintypes.UINT], wintypes.HWND
    user32.GetForegroundWindow.argtypes, user32.GetForegroundWindow.restype = [], wintypes.HWND
    proc = subprocess.Popen(
        [sys.executable, "-c", QT_WINDOW],
        cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "windows"},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        word, pid, window = proc.stdout.readline().split()
        copy = RunningCopy(int(pid), int(window))
        system = front.this_system()
        assert word == "ready" and system is not None and system.owner(copy.window) == copy.pid
        assert user32.GetAncestor(copy.window, 2) == copy.window  # GA_ROOT: the top-level window itself
        assert user32.IsIconic(copy.window) and system.responding(copy.window)
        brought = front.bring_to_front(lambda: copy, system, wait=0.0)
        deadline = time.monotonic() + 5
        while user32.IsIconic(copy.window) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not user32.IsIconic(copy.window)
        assert not brought or user32.GetForegroundWindow() == copy.window
        assert front.bring_to_front(lambda: RunningCopy(copy.pid + 1, copy.window), system, wait=0.0) is False
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(timeout=10)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' user32 is the only system that brings a window forward")
def test_req_set_019_windows_names_the_owner_of_a_window_and_none_once_closed() -> None:
    """A window this process makes: its owner is this process and it answers; once destroyed it has no owner, so a
    note naming a closed window brings nothing forward."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]  # fmt: skip
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes, user32.DestroyWindow.restype = [wintypes.HWND], wintypes.BOOL
    overlapped = 0x00CF0000  # WS_OVERLAPPEDWINDOW
    hwnd = user32.CreateWindowExW(0, "STATIC", "AOI second start", overlapped, 0, 0, 300, 200, None, None, None, None)
    assert hwnd, ctypes.get_last_error()
    window = int(hwnd)
    system = front.this_system()
    try:
        assert system is not None and system.owner(window) == os.getpid() and system.responding(window)
    finally:
        user32.DestroyWindow(hwnd)
    assert system.owner(window) is None
    assert front.bring_to_front(lambda: RunningCopy(os.getpid(), window), system, wait=0.0) is False
