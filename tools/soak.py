"""The soak test of REQ-INSP-011 (stage S55): the app inspects a board every few seconds for hours with no crash, its
time per board slowing by at most 10 % and its memory growing by at most 10 %.

    python tools/soak.py --out <new folder> [--hours 8] [--pace 3] [--warm-up 10] [--device auto]
        [--workspace <folder> --board-model <name> --boards <folder>] [--epochs <n>] [--image-size <px>]
    python tools/soak.py --check --out <a run's folder> --workspace <its workspace>

The app opens as main.py opens it, its window shown, on the workspace; the Operator is signed in, Inspection shows the
board model and the boards are queued, as Load Images… queues them, over and over; Next Board (F8) is pressed every
`--pace` seconds until `--hours` have passed, and each board is judged and saved as on a station. A board still being
inspected when Next Board is due delays the next one to the press after it, and the summary counts those presses.

Without --workspace the tool first writes, under --out, the synthetic boards of tools/make_synthetic_dataset.py
(boards/) and a workspace (workspace/) with board model SOAK, trains its AI model on the boards' training split (with
the app's training settings unless --epochs or --image-size are given) and activates it; the run inspects the test
split. A key store in memory holds the samples' dataset store key for that set-up only: nothing goes to the Windows
Credential Manager. The verdicts are of synthetic boards: a load for the app, never an accuracy.

--out/soak.csv has one line per board, written to disk as it finishes, so a crash or a power cut leaves the lines
before it: utc (ISO 8601 with offset), board (its count), file, seconds (Next Board pressed to the result shown and
saved), rss_mb (the process's resident memory then: the working set on Windows), verdict, and record (the saved
record's id, empty when the board was not saved).

The judgement, printed and written to --out/soak.json: the boards that finish after the warm-up (the first --warm-up
minutes, 10 by default, at most a fifth of the run) are taken in order, and the first tenth of them is compared with
the last tenth: slowdown = median seconds of the last / median of the first - 1, and growth = median rss_mb of the
last / median of the first - 1. PASS needs the whole run done, every board inspected and saved, no unhandled error, at
least 10 boards in each tenth, a slowdown of at most 10 % and a growth of at most 10 %; anything else is FAIL, with
the reasons. A crash prints nothing: the CSV stops. Exit codes: 0 PASS, 1 FAIL, 2 a usage error.

--check is the count after a forced power-off (REQ-INSP-008, docs/tests/station-checks.md): it opens the workspace as
the next start opens it, which sweeps an interrupted write's temporary file away, and passes when the database is
whole, every board soak.csv names as saved is there with its verdict, and every record there is whole, as
tests/test_power_cut.py checks one: its checks and result stored, its defects counted, and its overlay and maps there,
each decoding. A record saved after the last line reached the disk is no loss: the board was in hand at the cut.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from types import TracebackType
from typing import Any, TextIO

if __package__ in (None, ""):  # run as a script: the repository root on the path, so `aoi` and `tools` import
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from aoi.config import Settings  # noqa: E402
from aoi.core.imaging import list_images, load_image  # noqa: E402
from aoi.core.services import AppContext  # noqa: E402
from aoi.data import credentials  # noqa: E402
from aoi.ui.main_window import build_window  # noqa: E402
from aoi.ui.theme import QSS  # noqa: E402
from aoi.ui.workers import collect_on_ui_thread  # noqa: E402
from tools.make_synthetic_dataset import ng_type, write_dataset  # noqa: E402
from tools.memory import resident  # noqa: E402
from tools.trainable import trainable  # noqa: E402

LIMIT = 0.10  # REQ-INSP-011: slowdown and memory growth, each at most 10 %
TENTH = 0.10  # the share of the boards after the warm-up compared at each end
MIN_BOARDS = 10  # in each tenth: fewer judge nothing
POLL_MS = 10  # how often the run looks for the board's result shown
BOARD_MODEL = "SOAK"
COLUMNS = ("utc", "board", "file", "seconds", "rss_mb", "verdict", "record")


@dataclass(frozen=True)
class Board:
    """One board of the run, as soak.csv holds it, and when it finished in seconds since the run started."""

    at: float
    utc: str
    board: int
    file: str
    seconds: float
    rss_mb: float
    verdict: str
    record: int | None


@dataclass
class Judgement:
    """The run judged against REQ-INSP-011's limits, and the figures behind it."""

    passed: bool
    boards: int  # finished in the whole run
    judged: int  # finished after the warm-up
    tenth: int  # boards in each end compared
    slowdown: float | None  # last tenth's median seconds over the first's, less 1
    growth: float | None  # last tenth's median memory over the first's, less 1
    first_s: float | None = None
    last_s: float | None = None
    first_mb: float | None = None
    last_mb: float | None = None
    reasons: list[str] = field(default_factory=list)


def judge(boards: Sequence[Board], warm_up_s: float, finished: bool, failures: int, errors: int) -> Judgement:
    """`boards` judged after `warm_up_s`: PASS needs the run `finished`, no board not inspected or not saved
    (`failures`), no unhandled error (`errors`), MIN_BOARDS in each tenth and both figures within LIMIT."""
    after = [b for b in boards if b.at >= warm_up_s]
    tenth = int(len(after) * TENTH)
    j = Judgement(False, len(boards), len(after), tenth, None, None)
    if not finished:
        j.reasons.append("the run did not reach its end")
    if failures:
        j.reasons.append(f"{failures} board(s) not inspected or not saved")
    if errors:
        j.reasons.append(f"{errors} unhandled error(s), in the workspace's log")
    if tenth < MIN_BOARDS:
        j.reasons.append(f"{len(after)} board(s) after the warm-up: at least {MIN_BOARDS * 10} are needed to judge")
    else:
        first, last = after[:tenth], after[-tenth:]
        j.first_s, j.last_s = (statistics.median(b.seconds for b in bs) for bs in (first, last))
        j.first_mb, j.last_mb = (statistics.median(b.rss_mb for b in bs) for bs in (first, last))
        j.slowdown, j.growth = j.last_s / j.first_s - 1, j.last_mb / j.first_mb - 1
        if j.slowdown > LIMIT:
            j.reasons.append(f"slowed by {j.slowdown:.1%}, over {LIMIT:.0%}")
        if j.growth > LIMIT:
            j.reasons.append(f"memory grew by {j.growth:.1%}, over {LIMIT:.0%}")
    j.passed = not j.reasons
    return j


def synthetic_workspace(out: Path, device: str, epochs: int | None, image_size: int | None) -> tuple[Path, str, Path]:
    """A workspace under `out` with board model SOAK and an active AI model trained on synthetic boards, and the
    folder of the boards the run inspects."""
    boards, ws = out / "boards", out / "workspace"
    write_dataset(boards)
    ctx = AppContext(Settings(workspace=str(ws), device=device), credentials.MemoryCredentials())
    try:
        ctx.set_user("engineer")
        ctx.import_samples(BOARD_MODEL, [str(p) for p in list_images(boards / "train" / "ok")], "OK")
        for p in list_images(boards / "train" / "ng"):  # one call each: an NG sample is imported with its type
            ctx.import_samples(BOARD_MODEL, [str(p)], "NG", ng_type(p))
        ctx.train(trainable(ctx, BOARD_MODEL), epochs=epochs, image_size=image_size)
        ctx.activate_model(int(ctx.models(BOARD_MODEL)[0]["id"]))  # a version installs inactive (REQ-TRN-010)
    finally:
        ctx.close()
    return ws, BOARD_MODEL, boards / "test"


class Run:
    """The run in the app's window: Next Board every `pace` seconds for `seconds`, each board's line to `out`."""

    def __init__(self, app: QApplication, ctx: AppContext, board_model: str, boards: list[Path], out: TextIO) -> None:
        self.app, self.ctx, self.file, self.out = app, ctx, out, csv.writer(out)
        self.boards: list[Board] = []
        self.failures = self.errors = self.late = 0
        self.finished = False
        self.pressed: tuple[float, Path] | None = None  # when Next Board was pressed for the board being inspected
        win = build_window(ctx)  # as main.py builds it, with the unhandled-error hook in place
        if win is None:
            raise SystemExit("the window could not be built: see the workspace's log")
        self.win = win
        win.showMaximized()
        win.set_user("operator")
        win.bm_combo.setCurrentText(board_model)
        if win.board_model != board_model or not win.navigate("Inspection"):
            raise SystemExit(f"Inspection cannot be opened on {board_model}")
        self.page: Any = win.pages["Inspection"]
        self.queue = boards
        hook = sys.excepthook

        def counted(kind: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
            self.errors += 1  # logged and shown by the app's own hook, and counted here
            hook(kind, exc, tb)

        sys.excepthook = counted
        self.out.writerow(COLUMNS)

    def start(self, seconds: float, pace: float) -> None:
        self.seconds, self.t0 = seconds, perf_counter()
        n = int(seconds / pace) + 2  # every press has a board, and one more for the last press
        self.page._set_queue([self.queue[i % len(self.queue)] for i in range(n)])  # as Load Images… queues them
        self.ticks = self._timer(int(pace * 1000), self._tick)
        self.poll = self._timer(POLL_MS, self._poll)
        self._tick()

    def _timer(self, ms: int, slot: Callable[[], None]) -> QTimer:
        t = QTimer(self.win)
        t.setInterval(ms)
        t.timeout.connect(slot)
        t.start()
        return t

    def _tick(self) -> None:
        if perf_counter() - self.t0 >= self.seconds:
            self.ticks.stop()
            self.finished = True
            if self.pressed is None:
                self.app.quit()
            return
        if self.pressed is not None:  # the board before is still being inspected
            self.late += 1
            return
        path = self.page.queue[self.page.queue_pos + 1]
        self.pressed = perf_counter(), path
        self.page.next_board()  # F8
        if self.page.worker is None:  # refused: no board model, another user, the end of the queue
            self.pressed = None
            self.failures += 1
            self.app.quit()

    def _poll(self) -> None:
        if self.pressed is None or self.page.worker is not None:
            return
        (pressed, path), now = self.pressed, perf_counter()
        self.pressed = None
        saved = self.page.last_path == path and self.page.last_id is not None
        verdict, record = (self.page.last.verdict, self.page.last_id) if saved else ("NOT SAVED", None)
        utc, mb = datetime.now(UTC).isoformat(timespec="milliseconds"), resident()[0] / 2**20
        b = Board(now - self.t0, utc, len(self.boards) + 1, path.name, now - pressed, mb, verdict, record)
        self.boards.append(b)
        self.out.writerow([b.utc, b.board, b.file, f"{b.seconds:.3f}", f"{b.rss_mb:.1f}", b.verdict, b.record or ""])
        self.file.flush()
        os.fsync(self.file.fileno())  # on disk before the next board: a line a power cut leaves names a saved board
        if not saved:  # the page stopped the run and said why: the soak stops with it
            self.failures += 1
            self.finished = False
            self.app.quit()
        elif self.finished:
            self.app.quit()


def check(out: Path, workspace: Path) -> tuple[int, int, list[str]]:
    """The boards `out`/soak.csv names as saved, the records `workspace` holds, and what --check finds lost or not
    whole: nothing, for a pass."""
    with open(out / "soak.csv", newline="", encoding="utf-8") as f:
        saved = [line for line in csv.DictReader(f) if line["record"]]
    problems: list[str] = []
    ctx = AppContext(Settings(workspace=str(workspace), device="cpu"))
    try:
        if (state := ctx.db.query("PRAGMA integrity_check")) != [{"integrity_check": "ok"}]:
            problems.append(f"the database is damaged: {state[:5]}")
        rows = {r["id"]: r for r in ctx.inspections(include_archived=True)}
        for line in saved:
            r = rows.get(int(line["record"]))
            if r is None or r["result"] != line["verdict"]:
                problems.append("lost: board {board}, {file}, {verdict}, record {record}".format(**line))
        for r in rows.values():
            if not ctx.checks_for(r["id"]) or ctx.inspection_result(r["id"]) is None:
                problems.append(f"record {r['id']}: its checks or its result are missing")
            if r["defect_count"] != len(ctx.defects_for(r["id"])):
                problems.append(f"record {r['id']}: {r['defect_count']} defect(s) counted, others stored")
            for key in ("overlay_path", "diff_map_path", "ai_map_path"):
                try:
                    load_image(r[key])
                except Exception as e:  # missing, cut short or damaged: each is a loss
                    problems.append(f"record {r['id']}, {key}: {e}")  # the error names the file
    finally:
        ctx.close()
    return len(saved), len(rows), problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="a new folder for soak.csv, soak.json and any set-up")
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--pace", type=float, default=3.0, help="seconds between two presses of Next Board")
    ap.add_argument("--warm-up", type=float, default=10.0, help="minutes left out of the judgement, at most a fifth")
    ap.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda"))
    ap.add_argument("--workspace", type=Path, help="a trained workspace to run on, in place of the synthetic set-up")
    ap.add_argument("--board-model", help="with --workspace: the board model to inspect")
    ap.add_argument("--boards", type=Path, help="with --workspace: the folder of board images to inspect")
    ap.add_argument("--epochs", type=int, help="the synthetic set-up's training epochs (the app's setting if omitted)")
    ap.add_argument("--image-size", type=int, help="the synthetic set-up's network input size (the app's if omitted)")
    ap.add_argument("--check", action="store_true", help="after a power cut: check a run's soak.csv and --workspace")
    a = ap.parse_args(argv)
    if a.check:
        if a.workspace is None:
            ap.error("--check needs the run's --workspace")
        saved, records, problems = check(a.out, a.workspace)
        print(f"{saved} board(s) saved in soak.csv; {records} record(s) in the workspace; {len(problems)} problem(s)")
        print("\n".join(problems[:50]) + ("\n" if problems else "") + ("FAIL" if problems else "PASS"))
        return 1 if problems else 0
    own = (a.workspace, a.board_model, a.boards)
    if any(own) and not all(own):
        ap.error("--workspace, --board-model and --boards go together")
    if a.out.exists() and any(a.out.iterdir()):
        ap.error(f"{a.out} is not empty: the tool writes into a new folder only")
    (a.out / "settings").mkdir(parents=True, exist_ok=True)
    os.environ["AOI_WORKSPACE"] = str((a.out / "settings").resolve())  # the page the run leaves open is saved in
    # settings.json there, never in the station's
    app = QApplication(sys.argv[:1])
    app.setStyleSheet(QSS)
    collect_on_ui_thread()  # as main.py: no pool thread runs Python's cycle collector
    ws, board_model, folder = own if all(own) else synthetic_workspace(a.out, a.device, a.epochs, a.image_size)
    boards = list_images(folder)
    if not boards:
        ap.error(f"no board images in {folder}")
    seconds = a.hours * 3600
    warm_up = min(a.warm_up * 60, seconds / 5)
    ctx = AppContext(Settings(workspace=str(ws), device=a.device))
    try:
        with open(a.out / "soak.csv", "w", newline="", encoding="utf-8") as out:
            run = Run(app, ctx, board_model, boards, out)
            run.start(seconds, a.pace)
            app.exec()
    finally:
        ctx.close()
    j = judge(run.boards, warm_up, run.finished, run.failures, run.errors)
    summary = {"hours": a.hours, "pace_s": a.pace, "warm_up_s": warm_up, "late_presses": run.late, **asdict(j)}
    (a.out / "soak.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"{j.boards} boards in {a.hours:g} h at one every {a.pace:g} s; {j.judged} after a {warm_up:.0f} s warm-up;"
          f" {run.late} press(es) late")  # fmt: skip
    if j.slowdown is not None and j.growth is not None:
        print(f"seconds per board (median): first tenth {j.first_s:.3f}, last tenth {j.last_s:.3f}, {j.slowdown:+.1%}")
        print(f"memory (median MB): first tenth {j.first_mb:.0f}, last tenth {j.last_mb:.0f}, {j.growth:+.1%}")
    print("PASS" if j.passed else "FAIL: " + "; ".join(j.reasons))
    return 0 if j.passed else 1


if __name__ == "__main__":
    sys.exit(main())
