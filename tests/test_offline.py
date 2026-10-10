"""REQ-SET-003 (stage S52): the app makes no network call and listens on no port (Engineering standard, "Offline and
least privilege", MUST). Each test runs one scripted session: the app started as `python main.py` starts it, on the
test's own default workspace, and driven through its pages as an Engineer works through Stage 1. A guard refuses each
IPv4 or IPv6 socket call and name lookup meanwhile, from any thread, and lists each with the stack that made it; on
Linux /proc shows the sockets the process holds after each step, also one opened below Python (Qt's C++). The built
app's 1-hour run on the reference PC is tools/check_offline.ps1 (S55); docs/install/ports.md lists the ports: none."""

from __future__ import annotations

import _socket
import errno
import os
import shutil
import socket
import sys
import traceback
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

import main
from aoi.ui.main_window import MainWindow
from tests.conftest import listed
from tests.test_startup import _App, _shown_window
from tools.make_synthetic_dataset import ng_type
from tools.trainable import trainable

BOARD = "OFFLINE"
INET = (socket.AF_INET, socket.AF_INET6)
# Refused on an IPv4 or IPv6 socket (sendmsg where the platform has it: not on Windows). An AF_UNIX socket passes: it
# has no address another machine can reach and no port, so REQ-SET-003 does not cover it, and neither do
# Get-NetTCPConnection and Get-NetUDPEndpoint (tools/check_offline.ps1). socketpair() makes an AF_UNIX pair where
# `_socket` has it (Linux, macOS); elsewhere (Windows) the standard library builds it on a loopback listener: refused.
SOCKET_CALLS = ("connect", "connect_ex", "bind", "listen", "sendto", "sendmsg")
LOOKUPS = ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo", "create_connection")
# Modules only a network feature would load. Not listed: those importing the app loads for their own reasons (torch.hub
# imports urllib.request, http.client and ssl; torch imports asyncio and multiprocessing), whose use reaches the guard.
NETWORK_MODULES = (
    "PySide6.QtNetwork", "PySide6.QtNetworkAuth", "PySide6.QtWebSockets", "PySide6.QtHttpServer",
    "PySide6.QtRemoteObjects", "PySide6.QtWebEngineCore", "requests", "urllib3", "httpx", "aiohttp", "websocket",
    "websockets", "paramiko", "ftplib", "smtplib", "imaplib", "poplib", "xmlrpc.client", "http.server", "socketserver",
)  # fmt: skip
PROC = Path("/proc/self/fd").is_dir() and Path("/proc/net/tcp").is_file()  # Linux
STEPS = ("start", "import samples", "train and export an AI model", "inspect boards",
         "judge a stored result on Compare", "run an AI Model Test on a folder", "export CSV and overlays")  # fmt: skip


class Refused(OSError):
    """What a guarded call raises: the error of an unplugged network, so the app's own handling of one runs too."""


@pytest.fixture
def network_guard(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each network call the test makes, by any thread, refused with Refused and listed with its stack."""
    calls: list[str] = []

    def refuse(what: str) -> NoReturn:
        calls.append(f"{what}\n" + "".join(traceback.format_stack(limit=30)[:-2]))
        raise Refused(errno.ENETUNREACH, f"REQ-SET-003: no network call in an offline session ({what})")

    def guarded(name: str) -> Callable[..., Any]:
        real = getattr(socket.socket, name)

        def call(self: socket.socket, *args: Any) -> Any:
            if self.family in INET:
                refuse(f"socket.{name}{args!r} on {self.family.name}")
            return real(self, *args)

        return call

    for name in SOCKET_CALLS:
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, guarded(name))
    for name in LOOKUPS:
        monkeypatch.setattr(socket, name, lambda *a, _name=name, **k: refuse(f"socket.{_name}{a!r}"))
    return calls


def _listed(calls: list[str]) -> str:
    return f"{len(calls)} network call(s) tried:\n\n" + "\n\n".join(calls)


def ip_sockets() -> list[str]:
    """Each TCP or UDP socket, IPv4 or IPv6, this process holds, by its line in /proc/net (Linux): a TCP one in state
    0A listens, and a UDP one is bound to its local port."""
    inodes = set()
    for fd in Path("/proc/self/fd").iterdir():
        try:
            link = os.readlink(fd)
        except OSError:  # closed since it was listed
            continue
        if link.startswith("socket:["):
            inodes.add(link[len("socket:[") : -1])
    held = []
    for table in ("tcp", "tcp6", "udp", "udp6"):  # every socket of the network namespace, its inode in column 10
        if (path := Path("/proc/net", table)).is_file():  # tcp6 and udp6 only where the kernel has IPv6
            held += [f"{table}: {row.strip()}" for row in path.read_text().splitlines()[1:] if row.split()[9] in inodes]
    return held


def _laid_out(sources: list[Path], folder: Path) -> str:
    """`folder` with a copy of each of `sources`, as an Engineer lays boards out: OK under ok/, NG under ng/<type>/."""
    for src in sources:
        sub = folder / ("ok" if src.parent.name == "ok" else f"ng/{ng_type(src)}")
        sub.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, sub / src.name)
    return str(folder)


def _drive(
    qtbot: QtBot, win: MainWindow, data: Path, out: Path, mp: pytest.MonkeyPatch, done: Callable[[str], None]
) -> None:
    """Stage 1 on the shown window, as an Engineer works through it; `done(step)` after each step of STEPS."""
    pages, ctx, wait = win.pages, win.ctx, qtbot.waitUntil
    training, inspection, compare = pages["Training"], pages["Inspection"], pages["Compare"]
    test, logs = pages["AI Model Test"], pages["Logs & Export"]
    win.set_user("engineer")
    win._on_board_model(BOARD)
    win.navigate("Training")
    train = sorted((data / "train").rglob("*.png"))
    training.import_from(_laid_out(train, out / "import"))
    training.sheet.btn_import.click()
    wait(lambda: training._bg is None and not training.sheet.running, timeout=30000)
    assert len(ctx.samples(BOARD)) == len(train)
    done(STEPS[1])

    trainable(ctx, BOARD)  # a frozen, split dataset version, written as tools/trainable.py writes one for the tests
    training.refresh()
    training.epochs.setValue(training.epochs.minimum())
    training.input_size.setCurrentIndex(0)  # the smallest
    training.btn_train.click()
    wait(lambda: training.worker is None, timeout=120000)  # as test_page_translation: a busy CPU trains slowly
    training.models.selectRow(0)
    training.activate()
    mp.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out / "model.pt"), "")))
    training.models.selectRow(0)
    training.export_model()
    assert ctx.active_model(BOARD) is not None and (out / "model.pt").is_file()
    done(STEPS[2])

    win.navigate("Inspection")
    boards = _laid_out([min((data / "test" / x).glob("*.png")) for x in ("ok", "ng")], out / "boards")
    mp.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: boards))
    inspection.load_folder()
    inspection.start_run()  # F5
    wait(lambda: not inspection.running and inspection.worker is None, timeout=60000)
    assert len(ctx.inspections(board_model=BOARD)) == 2
    done(STEPS[3])

    inspection.open_compare()  # the last board's stored result
    wait(lambda: compare.loaded and compare._bg is None, timeout=30000)
    compare.re_evaluate()  # Ctrl+R: judged again from its stored maps
    wait(compare.would_be.isVisible, timeout=30000)
    done(STEPS[4])

    win.navigate("AI Model Test")
    test.folder = _laid_out(
        [p for x in ("ok", "ng") for p in sorted((data / "test" / x).glob("*.png"))[1:3]], out / "test"
    )
    test.run()
    wait(lambda: bool(test.rows) and test.btn_run.isEnabled(), timeout=60000)
    assert len(test.rows) == 4
    done(STEPS[5])

    win.set_user("admin")  # only an Admin exports (Q58, #151)
    win.navigate("Logs & Export")
    listed(qtbot, logs)  # the page lists its records on the pool (S55); the exports take what it lists
    (out / "overlays").mkdir()
    mp.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out / "inspections.csv"), "")))
    mp.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(out / "overlays")))
    logs.export_csv()
    wait(lambda: logs._bg is None, timeout=30000)
    logs.export_overlays()
    wait(lambda: logs._bg is None, timeout=30000)
    assert (out / "inspections_checks.csv").is_file() and len(list((out / "overlays").iterdir())) == 2
    done(STEPS[6])


@pytest.fixture
def session(
    qtbot: QtBot, network_guard: list[str], synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> Iterator[dict[str, list[str]]]:  # fmt: skip
    """The scripted session under the guard, run by main.main() with the test's application in place of a new one:
    each step done, with the IP sockets the process held after it (Linux; none listed elsewhere). It ends with every
    step done and no error shown, or fails the test with the network calls tried."""
    held: dict[str, list[str]] = {}
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # main() installs the app's own; the test's comes back after
    monkeypatch.setattr(main, "QApplication", _App)

    def done(step: str) -> None:
        held[step] = ip_sockets() if PROC else []

    def loop() -> int:
        win = _shown_window()
        qtbot.addWidget(win)
        done(STEPS[0])
        _drive(qtbot, win, synthetic_dataset, tmp_path, monkeypatch, done)
        win.close()
        return 0

    monkeypatch.setattr(_App, "loop", staticmethod(loop))
    try:
        assert main.main() == 0 and list(held) == list(STEPS), "the session did not run to its end"
        assert dialogs == [], "the session showed an error"
    except Exception as e:
        raise AssertionError(f"the session stopped after {list(held)}: {e}\n\n" + _listed(network_guard)) from e
    yield held


def test_req_set_003_no_network_calls(session: dict[str, list[str]], network_guard: list[str]) -> None:
    """Through the whole session no IPv4 or IPv6 socket is connected, bound, listened on or sent from, no name is
    looked up, and no module of a network feature is loaded, by the session or by the app's own imports before it."""
    assert network_guard == [], _listed(network_guard)
    loaded = [m for m in NETWORK_MODULES if m in sys.modules]
    assert loaded == [], f"modules of a network feature are loaded: {loaded}"


def test_req_set_003_no_listening_ports(session: dict[str, list[str]], network_guard: list[str]) -> None:
    """No socket is bound or listened on through the session, and on Linux /proc shows the process holding no TCP or
    UDP socket after any step, so none listens, not even one opened where the guard cannot see. Only that half needs
    /proc and is left out without it (on Windows check_offline.ps1 is that proof, S55); the rest always runs."""
    bound = [c for c in network_guard if c.startswith(("socket.bind", "socket.listen"))]
    assert bound == [], _listed(bound)
    if PROC:
        assert {step: rows for step, rows in session.items() if rows} == {}, "IP sockets held (0A: listening)"


def test_req_set_003_the_proofs_catch_a_call_and_a_listener(network_guard: list[str]) -> None:
    """The controls of the two tests above: each kind of network call is refused and listed with the stack that made
    it, urllib's included; a socketpair passes where it is AF_UNIX and is refused where it is built from a loopback
    listener; and on Linux /proc lists a listener opened below the guard, as Qt's C++ would open one."""
    with socket.socket() as tcp, socket.socket(type=socket.SOCK_DGRAM) as udp:  # IPv4
        tries: list[Callable[[], object]] = [
            lambda: socket.create_connection(("192.0.2.1", 80), timeout=1),  # TEST-NET-1, never routed
            lambda: socket.getaddrinfo("example.com", 443),
            lambda: urllib.request.urlopen("http://192.0.2.1/", timeout=1),
            lambda: tcp.connect(("192.0.2.1", 80)),
            lambda: tcp.bind(("127.0.0.1", 0)),
            lambda: tcp.listen(),
            lambda: udp.sendto(b"x", ("192.0.2.1", 9)),
        ]
        for attempt in tries:
            with pytest.raises(OSError, match="REQ-SET-003"):  # urllib's in a URLError
                attempt()
    assert len(network_guard) == len(tries) and all(__file__ in c for c in network_guard), _listed(network_guard)
    if hasattr(_socket, "socketpair"):
        a, b = socket.socketpair()
        with a, b:
            a.sendall(b"x")
            assert b.recv(1) == b"x" and len(network_guard) == len(tries)
    else:
        with pytest.raises(Refused):
            socket.socketpair()
    if PROC:
        below = _socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            below.bind(("127.0.0.1", 0))
            below.listen()
            (row,) = ip_sockets()
            assert row.split()[4] == "0A", row  # LISTEN
        finally:
            below.close()
        assert ip_sockets() == []
