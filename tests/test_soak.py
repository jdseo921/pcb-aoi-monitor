"""REQ-INSP-011 (stage S55): tools/soak.py, the 8-hour soak test the reference PC runs, judges a run against the 10 %
limits, and a short run of it inspects and saves every board through the app's own window.

The 8-hour run itself is a station check on the reference PC: a run of a minute or two on a shared CI runner
measures its neighbours' load as much as the app, so the short run here asserts everything but the 10 % time limit,
which the judgement tests below prove instead, and prints the figure it measured."""

from __future__ import annotations

import csv
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from tools.soak import Board, judge

ROOT = Path(__file__).resolve().parents[1]


def _run(seconds: list[float], mb: list[float], start_at: float = 0.0) -> list[Board]:
    """Boards one second apart from `start_at`, taking `seconds` each with `mb` resident after each."""
    return [
        Board(start_at + i, "", i + 1, f"b{i}.png", s, m, "OK", i + 1)
        for i, (s, m) in enumerate(zip(seconds, mb, strict=True))
    ]


def test_req_insp_011_judge_holds_the_10_percent_limits() -> None:
    """The first tenth of the boards after the warm-up against the last tenth, by their medians: 9 % slower or 9 %
    bigger passes, 11 % fails; a slow start inside the warm-up is not judged; and a run cut short, a board not saved,
    an unhandled error or too few boards fail whatever the figures."""
    flat = judge(_run([0.5] * 200, [900.0] * 200), 0, True, 0, 0)
    assert flat.passed and (flat.tenth, flat.slowdown, flat.growth) == (20, 0.0, 0.0)
    for later, passed in ((0.545, True), (0.555, False)):  # 9 % and 11 % slower in the last tenth
        j = judge(_run([0.5] * 180 + [later] * 20, [900.0] * 200), 0, True, 0, 0)
        assert j.passed is passed and (j.reasons == []) is passed, j.reasons
    for later, passed in ((981.0, True), (999.0, False)):  # 9 % and 11 % bigger
        j = judge(_run([0.5] * 200, [900.0] * 180 + [later] * 20), 0, True, 0, 0)
        assert j.passed is passed, j.reasons
    warm = judge(_run([3.0] * 50 + [0.5] * 200, [400.0] * 50 + [900.0] * 200), 50, True, 0, 0)
    assert warm.passed and (warm.boards, warm.judged, warm.first_s) == (250, 200, 0.5)
    cold = judge(_run([3.0] * 50 + [0.5] * 200, [400.0] * 50 + [900.0] * 200), 0, True, 0, 0)
    assert not cold.passed and cold.growth is not None and cold.growth > 1
    broken = judge(_run([0.5] * 99, [900.0] * 99), 0, False, 1, 2)
    assert not broken.passed and broken.slowdown is None
    assert broken.reasons == [
        "the run did not reach its end",
        "1 board(s) not inspected or not saved",
        "2 unhandled error(s), in the workspace's log",
        "99 board(s) after the warm-up: at least 100 are needed to judge",
    ]


@pytest.fixture(scope="module")
def soaked(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """The folder of a run of 72 s at a board every 0.25 s on the synthetic set-up, with an AI model trained for 2
    epochs at 64 px, and what the tool printed."""
    out = tmp_path_factory.mktemp("soak") / "run"
    cmd = [sys.executable, "-m", "tools.soak", "--out", str(out), "--hours", "0.02", "--pace", "0.25"]
    cmd += ["--warm-up", "0.1", "--device", "cpu", "--epochs", "2", "--image-size", "64"]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
    print(done.stdout)
    assert done.returncode in (0, 1), done.stderr
    return out, done.stdout


def test_req_insp_011_soak_inspects_and_saves_every_board_through_the_window(soaked: tuple[Path, str]) -> None:
    """The run reaches its end with every board judged by the active AI model and saved, one line each in soak.csv in
    order, in UTC with an offset; memory grows by at most 10 %; and soak.json holds what the tool printed."""
    out, printed = soaked
    summary = json.loads((out / "soak.json").read_text(encoding="utf-8"))
    other = [r for r in summary["reasons"] if not r.startswith("slowed by")]  # the time limit: see the module's note
    assert other == [] and summary["growth"] <= 0.10, summary
    assert printed.strip().splitlines()[-1] == ("PASS" if summary["passed"] else "FAIL: " + summary["reasons"][0])
    with open(out / "soak.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == summary["boards"] > 200 and [int(r["board"]) for r in rows] == list(range(1, len(rows) + 1))
    assert all(datetime.fromisoformat(r["utc"]).utcoffset() is not None for r in rows)
    assert {r["verdict"] for r in rows} <= {"OK", "WARN", "NG"} and len({r["record"] for r in rows}) == len(rows)
    with closing(sqlite3.connect(out / "workspace" / "aoi.sqlite")) as db:
        stored = db.execute("SELECT id, result, model_version FROM inspections ORDER BY id").fetchall()
    assert [(str(i), v) for i, v, _ in stored] == [(r["record"], r["verdict"]) for r in rows]
    assert all(version for _, _, version in stored), "a board was judged without the AI model"
