"""How the scenario tool puts boards through a station (#459): one row per board, in order, whatever a run meets. A fake
cycle stands in for the app's, so the bookkeeping is tested without a trained station."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np

from aoi.errors import AoiError
from tools.proxy_judge import Frames, judge
from tools.proxy_validation import Board


class Cycle:
    """Each frame judged OK, but a file named refuse* refused mid-run, one named nosave* not saved, and the whole run
    refused before any frame while `blocked`."""

    def __init__(self, blocked: bool = False) -> None:
        self.blocked, self.runs = blocked, 0

    def run(self, bm: str, src: Frames) -> Iterator[Any]:
        self.runs += 1
        if self.blocked:
            raise AoiError("AOI-INSP-016", board_model=bm, reason="none has passed")
        while (got := src.grab()) is not None:
            name = Path(got[1].path).name
            if name.startswith("refuse"):
                raise AoiError("AOI-INSP-006", kind="PNG", path=name, reason="cut short")
            result = SimpleNamespace(verdict="OK", defects=[], checks=[], elapsed_ms=5.0)
            engine = SimpleNamespace(reference=None, recipe=SimpleNamespace(fine_alignment=False))
            failed = OSError("disk") if name.startswith("nosave") else None
            yield SimpleNamespace(result=result, engine=engine, record_id=None if failed else 1, save_error=failed)
            if failed:
                return


def boards(tmp_path: Path, names: list[str]) -> list[Any]:
    out = []
    for n in names:
        cv2.imwrite(str(tmp_path / n), np.zeros((8, 8, 3), np.uint8))
        out.append((Board(tmp_path / n, "OK"), None, n))
    return out


def test_459_judge_keeps_one_row_per_board_in_order_through_refusals_and_failed_saves(tmp_path: Path) -> None:
    items = boards(tmp_path, ["a.png", "refuse.png", "b.png", "nosave.png", "c.png"])
    cycle = Cycle()
    rows = judge(SimpleNamespace(), "PCB1", items, cycle=cycle)  # type: ignore[arg-type]
    assert [r["tag"] for r in rows] == ["a.png", "refuse.png", "b.png", "nosave.png", "c.png"]
    assert [r["verdict"] for r in rows] == ["OK", None, "OK", "OK", "OK"]
    assert rows[1]["refused"]["code"] == "AOI-INSP-006" and rows[1]["label"] == "OK"
    assert rows[3]["save_error"] == "disk" and rows[3]["record_id"] is None
    assert cycle.runs == 3  # a refusal and a failed save each end a run, as on the page


def test_459_a_run_refused_before_any_frame_refuses_every_board_left(tmp_path: Path) -> None:
    rows = judge(SimpleNamespace(), "PCB1", boards(tmp_path, ["a.png", "b.png"]), cycle=Cycle(blocked=True))  # type: ignore[arg-type]
    assert [(r["tag"], r["verdict"], r["taken"], r["refused"]["code"]) for r in rows] == [
        ("a.png", None, False, "AOI-INSP-016"),
        ("b.png", None, False, "AOI-INSP-016"),
    ]
