"""REQ-INSP-008, crash-safety part (S11): no finished result is lost and nothing is left half-written.

A process kill is not a power cut: the operating system still flushes what the process handed it, and the
disk's own cache is not involved. The full test, with the power pulled on the reference PC, is a station check
(docs/tests/station-checks.md).

Random kills seldom land inside a file write (a few milliseconds of each inspection), so they show that no finished
result is lost, not that every file is written whole (#202). That rests on three other tests: every write in `aoi/` by
the calls a scan of the source knows goes through `aoi/data/atomic.py` (non_atomic_writes lists them), every file an
inspection and a training run leave was written through it (a run), and a kill inside such a write leaves the target
absent and a temporary file the next start sweeps away.
"""

from __future__ import annotations

import ast
import os
import queue
import random
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import pytest

from aoi.config import Settings
from aoi.core.imaging import IMAGE_EXTS, load_image
from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.data.db import Database
from tests.conftest import TrainedModel
from tools.trainable import trainable

ROOT = Path(__file__).resolve().parents[1]
KILLS = 20
SEED = 2026
LIMIT_S = 120  # for the worker's next line: generous, so a loaded runner is slow, not failed
# Calls that write a file under the name they are given, by their full name, and methods that do on any object.
INTO_A_FILE = {"torch.save", "numpy.save", "numpy.savez", "numpy.savez_compressed", "numpy.savetxt"}  # write_with's too
WRITE_CALLS = INTO_A_FILE | {"cv2.imwrite", "os.replace", "os.rename", "shutil.move", "shutil.copytree"}
WRITE_CALLS |= {"shutil.copy", "shutil.copy2", "shutil.copyfile"}
WRITE_METHODS = {"write_bytes", "write_text", "tofile", "save", "rename"}  # with an argument: not QPainter.save()
OPENS = {"open", "io.open", "codecs.open", "os.fdopen", "gzip.open", "tarfile.open", "zipfile.ZipFile"}  # (file, mode)
QT_WRITERS = {"PySide6.QtGui." + c for c in ("QPdfWriter", "QImageWriter", "QTextDocumentWriter")}
QT_WRITERS |= {"PySide6.QtSvg.QSvgGenerator"}  # Qt classes writing the file they are given, unless a QBuffer (memory)
QBUFFER, QFILE = "PySide6.QtCore.QBuffer", "PySide6.QtCore.QFile"
QT_METHODS = {("copy", QFILE), *(("setFileName", w) for w in QT_WRITERS)}  # write a file on the object a class made
NOT_ATOMIC = {  # (file, call as the scan shows it): why it may write outside atomic.py
    ("aoi/errors.py", "DOC_PATH.write_text()"): "a developer tool writing docs/error-codes.md in the repository",
    ("aoi/logging_setup.py", "open(..., 'a')"): "the log appends line by line; a cut can shorten only its last line",
    ("aoi/data/migrate.py", "os.replace()"): "the schema backup: SQLite's backup API writes a temp copy, renamed whole",
    ("aoi/core/services.py", "model.save()"): "AnomalyModel.save writes the .pt through atomic.write_with",
    ("aoi/data/workspace_lock.py", "os.open(write)"): "an empty lock file, never written: the OS lock counts (#204)",
}


def test_req_insp_008_writes_are_atomic(tmp_path: Path) -> None:
    target = tmp_path / "board.png"
    atomic.write_bytes(target, b"old")

    def half(f: object) -> None:
        f.write(b"new but")  # type: ignore[attr-defined]
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        atomic.write_with(target, half)
    assert target.read_bytes() == b"old"  # the old file is untouched ...
    assert [p.name for p in tmp_path.iterdir()] == ["board.png"]  # ... and no temporary file remains
    atomic.write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    atomic.copy_file(target, tmp_path / "sub" / "copy.png")
    assert (tmp_path / "sub" / "copy.png").read_bytes() == b"new"
    (tmp_path / "sub" / ".left.deadbeef.tmp").write_bytes(b"x")
    assert atomic.sweep_temp_files(tmp_path) == (1, []) and not (tmp_path / "sub" / ".left.deadbeef.tmp").exists()


def non_atomic_writes(path: Path) -> list[tuple[str, str]]:
    """Each file write in a module that does not go through `atomic`, as (line, call): the calls listed above, an open
    for writing (OPENS, a Path's or a QFile's .open) and os.open with write flags; a save into the file `write_with`
    hands its writer is not one, nor is a QBuffer's (in memory: a name the module binds only to QBuffer())."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases |= {a.asname or a.name: a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            aliases |= {a.asname or a.name: f"{'.' * node.level}{node.module or ''}.{a.name}" for a in node.names}

    def full_name(func: ast.expr) -> str:
        parts: list[str] = []
        while isinstance(func, ast.Attribute):
            parts, func = [func.attr, *parts], func.value
        return ".".join([aliases.get(func.id, func.id), *parts]) if isinstance(func, ast.Name) else ""

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    bound = {id(t): n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets}  # target: value
    makers: dict[str, set[str]] = {}  # each name the module binds, and what made it each time ("" if not a call)
    for n in ast.walk(tree):
        if isinstance(n, ast.arg) or isinstance(n, ast.Name | ast.Attribute) and isinstance(n.ctx, ast.Store):
            made = full_name(v.func) if isinstance(v := bound.get(id(n)), ast.Call) else ""
            makers.setdefault(n.arg if isinstance(n, ast.arg) else ast.unparse(n), set()).add(made)

    def made_by(e: ast.expr) -> str:  # what made the object `e` names, if each binding of the name is a call to it
        makes = {full_name(e.func)} if isinstance(e, ast.Call) else makers.get(ast.unparse(e), {full_name(e)})
        return next(iter(makes)) if len(makes) == 1 else ""

    in_writer = {
        id(inner)
        for c in calls
        if full_name(c.func).endswith("write_with")
        for arg in [*c.args[1:], *(k.value for k in c.keywords)]
        for inner in ast.walk(arg)
    }
    shown = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
    found: list[tuple[str, str]] = []
    for c in calls:
        name, attr = full_name(c.func), c.func.attr if isinstance(c.func, ast.Attribute) else ""
        on = made_by(c.func.value) if isinstance(c.func, ast.Attribute) else ""  # what made a method's object
        func = name if name in OPENS | WRITE_CALLS | QT_WRITERS else ast.unparse(c.func)
        if name in OPENS or (attr == "open" and name != "os.open" and on != QBUFFER):
            at = 1 if name in OPENS else 0  # Path.open(mode), QFile.open(flags)
            mode = next((k.value for k in c.keywords if k.arg == "mode"), c.args[at] if len(c.args) > at else None)
            text = "r" if mode is None else mode.value if isinstance(mode, ast.Constant) else "?"
            call = f"{func}(..., {text!r})" if not isinstance(text, str) or set(text) & set("wax+?") else ""
        elif name == "os.open":
            flags = {n.attr for a in c.args[1:] for n in ast.walk(a) if isinstance(n, ast.Attribute)}
            call = "os.open(write)" if flags & {"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC"} else ""
        elif name in WRITE_CALLS:  # a module's function, also when it is called save
            call = "" if name in INTO_A_FILE and id(c) in in_writer else f"{name}()"
        else:
            to_file = attr in WRITE_METHODS and bool(c.args or c.keywords) and not on.endswith("atomic")
            qt = name in QT_WRITERS and c.args and made_by(c.args[0]) != QBUFFER or (attr, on) in QT_METHODS
            call = f"{func}()" if to_file or qt else ""
        if call:
            found.append((f"{shown}:{c.lineno}", call))
    return found


def test_req_insp_008_every_writer_in_the_app_goes_through_atomic() -> None:
    """A file the app writes is written whole or not at all only if it goes through aoi/data/atomic.py (#202): a module
    that writes onto the final name by a call non_atomic_writes knows fails here, whatever a random kill hits."""
    own = ROOT / "aoi" / "data" / "atomic.py"
    found = [w for p in sorted((ROOT / "aoi").rglob("*.py")) if p != own for w in non_atomic_writes(p)]
    seen = {(where.partition(":")[0], call) for where, call in found}
    assert seen >= NOT_ATOMIC.keys(), f"gone, drop from NOT_ATOMIC: {NOT_ATOMIC.keys() - seen}"
    left = [f"{where} {call}" for where, call in found if (where.partition(":")[0], call) not in NOT_ATOMIC]
    assert not left, "write files through aoi/data/atomic.py: " + ", ".join(left)


def test_req_insp_008_the_writer_scan_catches_a_plain_write(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import cv2, shutil, tarfile, torch, zipfile, PySide6.QtGui as QtGui\n"
        "import numpy as np; from PySide6.QtCore import QBuffer, QFile, QIODevice\n"
        "from shutil import copyfile as cp; from PySide6.QtSvg import QSvgGenerator as Svg\n"
        "from ..data import atomic\n"
        "def f(path, img, payload, mode, camera, painter):\n"
        "    open(path, 'wb').write(b''); open(path).read(); open(path, 'rb').read()\n"
        "    Path(path).write_bytes(b'x'); path.open('a'); path.open(mode=mode)\n"
        "    cv2.imwrite(path, img); np.save(path, img); cp(path, path); shutil.copy2(path, path)\n"
        "    torch.save(payload, path)\n"
        "    atomic.write_with(path, lambda f: torch.save(payload, f)); atomic.write_text(path, 'x'); camera.open()\n"
        "    buf = QBuffer(); buf.open(QIODevice.OpenModeFlag.WriteOnly); QtGui.QPdfWriter(buf); painter.save()\n"
        "    out = QFile(path); out.open(QIODevice.OpenModeFlag.WriteOnly); QFile.copy(path, path); out.rename(path)\n"
        "    QtGui.QImage(img).save(path); Svg().setFileName(path); QtGui.QPdfWriter(path); img.copy()\n"
        "    np.savetxt(path, img); zipfile.ZipFile(path, 'w'); tarfile.open(path, mode='w:gz')\n"
        "    mem = QBuffer(); mem = QFile(path); mem.open(QIODevice.OpenModeFlag.WriteOnly); zipfile.ZipFile(path)\n",
        encoding="utf-8",
    )
    assert sorted(non_atomic_writes(sample)) == sorted(
        [
            ("sample.py:6", "open(..., 'wb')"),
            ("sample.py:7", "Path(path).write_bytes()"),
            ("sample.py:7", "path.open(..., 'a')"),
            ("sample.py:7", "path.open(..., '?')"),
            ("sample.py:8", "cv2.imwrite()"),
            ("sample.py:8", "numpy.save()"),
            ("sample.py:8", "shutil.copyfile()"),
            ("sample.py:8", "shutil.copy2()"),
            ("sample.py:9", "torch.save()"),
            ("sample.py:12", "out.open(..., '?')"),
            ("sample.py:12", "QFile.copy()"),
            ("sample.py:12", "out.rename()"),
            ("sample.py:13", "QtGui.QImage(img).save()"),
            ("sample.py:13", "Svg().setFileName()"),
            ("sample.py:13", "PySide6.QtGui.QPdfWriter()"),
            ("sample.py:14", "numpy.savetxt()"),
            ("sample.py:14", "zipfile.ZipFile(..., 'w')"),
            ("sample.py:14", "tarfile.open(..., 'w:gz')"),
            ("sample.py:15", "mem.open(..., '?')"),
        ]
    )


def test_req_insp_008_results_and_the_golden_board_go_through_atomic(
    trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every file an inspection and a training run leave in the workspace went through `atomic.write_with`, apart from
    SQLite's own files and the appended log."""
    root = trained_ctx.settings.root.resolve()
    written: set[Path] = set()
    real = atomic.write_with

    def record(path: str | Path, writer: Callable[[BinaryIO], object]) -> None:
        written.add(Path(path).resolve())
        real(path, writer)

    def stamps() -> dict[Path, tuple[int, int]]:
        return {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*") if p.is_file()}

    monkeypatch.setattr(atomic, "write_with", record)
    before = stamps()
    trained_ctx.inspect_file("TINY", trained_ctx.db.samples("TINY")[0]["path"])
    trained_ctx.train(trainable(trained_ctx, "TINY"), epochs=1, image_size=64)
    changed = {p for p, s in stamps().items() if before.get(p) != s}
    files = {p for p in changed if not p.name.startswith("aoi.sqlite") and p.parent != root / "logs"}
    assert len([p for p in files if p.is_relative_to(root / "results")]) == 3, files  # overlay, difference and AI map
    models = {p.suffix for p in files if p.is_relative_to(root / "models")}
    assert models == {".pt", ".png", ".md", ".json"}, files  # the AI model, its Golden board and its model card
    assert files <= written, f"written outside atomic.write_with: {sorted(files - written)}"


class Worker:
    """One run of tests/power_cut_worker.py, killed on leaving the `with`; a thread reads its lines, so waiting for one
    can time out on any OS (a pipe has no timeout on Windows)."""

    def __init__(self, ws: Path, boards: Path, err: Path, **env: str) -> None:
        self.err, self.killed = err, False
        with open(err, "w", encoding="utf-8") as stderr:
            self.proc = subprocess.Popen(
                [sys.executable, "-m", "tests.power_cut_worker", str(ws), str(boards)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                env={**os.environ, **env},
            )
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def __enter__(self) -> Worker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.kill()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line.strip())
        self.lines.put(None)

    def next_line(self) -> str:
        try:
            line = self.lines.get(timeout=LIMIT_S)
        except queue.Empty:
            line = None
        if line is None:
            pytest.fail(f"the worker gave no line within {LIMIT_S} s: {self.err.read_text(encoding='utf-8')[-2000:]}")
        return line

    def kill(self) -> list[str]:
        """Kill it; the lines it printed and the test has not read yet."""
        if self.killed:
            return []
        self.killed = True
        self.proc.kill()
        self.proc.wait()
        self.reader.join()
        assert self.proc.stdout is not None
        self.proc.stdout.close()
        rest = []  # every line is queued once the reader has ended; a failed next_line took the None already
        while not self.lines.empty() and (line := self.lines.get()) is not None:
            rest.append(line)
        return rest


def check_workspace(ws: Path) -> int:
    """Every row of the workspace has its whole files, checks and defects, and every result file decodes; the number
    of rows."""
    db = Database(ws / "aoi.sqlite", ws)  # reopens cleanly: WAL recovery, migrations consistent
    rows = db.inspections(include_archived=True)
    for r in rows:
        overlay = Path(r["overlay_path"])
        assert overlay.exists(), r
        load_image(overlay)  # decodes, so the whole file is there
        assert r["defect_count"] == len(db.defects_for(r["id"]))
        assert db.checks_for(r["id"]) and db.inspection_result(r["id"]), "a row without its checks or result"
        assert all(r[k] and Path(r[k]).is_file() for k in ("diff_map_path", "ai_map_path")), r  # maps, then the row
    db.close()
    for p in (ws / "results").rglob("*"):
        if p.is_file() and not p.name.endswith(atomic.TEMP_SUFFIX):  # a temp file: an interrupted write
            assert p.suffix in IMAGE_EXTS, f"left half-written: {p}"
            load_image(p)
    return len(rows)


def kill_runs(ws: Path, boards: Path, kills: int, err: Path, **env: str) -> int:
    """Start the worker `kills` times; each time wait for its first saved result, then kill it at a random point of
    the next inspection or its save, timed by the first, so the kill lands there on a fast or a slow PC (#202). Every
    result it said it saved must be in the workspace, whole, and no row ever goes; returns the number of rows."""
    rng = random.Random(SEED)
    finished = 0
    for run in range(kills):
        with Worker(ws, boards, err, **env) as worker:
            assert (line := worker.next_line()) == "ready", line
            start = time.monotonic()
            assert (line := worker.next_line()).startswith("done"), line  # printed once its row is committed
            time.sleep(rng.uniform(0, 1) * (time.monotonic() - start))
            saved = 1 + sum(line.startswith("done") for line in worker.kill())
        rows = check_workspace(ws)
        assert rows >= finished + saved, f"run {run}: {finished} rows before, {saved} saved, {rows} now"
        finished = rows
    return finished


def test_req_insp_008_no_finished_result_lost(
    tmp_path: Path, tiny_model: TrainedModel, synthetic_dataset: Path
) -> None:
    ws = tmp_path / "station"
    shutil.copytree(tiny_model.ctx.settings.root, ws)
    assert kill_runs(ws, synthetic_dataset / "train", KILLS, tmp_path / "worker.err") >= KILLS
    ctx = AppContext(Settings(workspace=str(ws), device="cpu"))  # the next start sweeps the temp files away
    assert not list(ws.rglob(f".*{atomic.TEMP_SUFFIX}")) and ctx.load_model("TINY") is not None


def test_req_insp_008_kills_follow_a_saved_result_on_a_slow_pc(
    tmp_path: Path, tiny_model: TrainedModel, synthetic_dataset: Path
) -> None:
    """With every inspection 2 s longer than the longest wait the test once had (1.5 s), each kill still comes after a
    saved result, and the run does not fail for want of one (#202)."""
    ws = tmp_path / "station"
    shutil.copytree(tiny_model.ctx.settings.root, ws)
    assert kill_runs(ws, synthetic_dataset / "train", 3, tmp_path / "worker.err", AOI_POWER_CUT_SLOW_S="2") >= 3


def test_req_insp_008_a_kill_inside_a_write_leaves_no_part_file(
    tmp_path: Path, tiny_model: TrainedModel, synthetic_dataset: Path
) -> None:
    """The kill a random time seldom hits: inside the second file write of an inspection (one of its maps), with half
    of the bytes on disk. The map is absent, not cut short, no row names it, and the next start removes the
    temporary file."""
    ws = tmp_path / "station"
    shutil.copytree(tiny_model.ctx.settings.root, ws)
    with Worker(ws, synthetic_dataset / "train", tmp_path / "worker.err", AOI_POWER_CUT_IN_WRITE="2") as worker:
        assert (line := worker.next_line()) == "ready", line
        line = worker.next_line()
        assert line.startswith("dying "), f"the second file write did not go through atomic.write_with: {line}"
        assert worker.proc.wait(timeout=LIMIT_S) == 3
    target = Path(line.removeprefix("dying "))
    part = list(target.parent.glob(f".{target.name}.*{atomic.TEMP_SUFFIX}"))
    assert not target.exists() and len(part) == 1 and part[0].stat().st_size > 0, (target, part)
    assert check_workspace(ws) == 0  # the row is written after its files
    AppContext(Settings(workspace=str(ws), device="cpu"))
    assert not part[0].exists()
