"""Boards put through a station of tools/proxy_station.py the way the line does it, for the scenarios of #459:
`judge` hands frames, read from file or changed in memory (tools/proxy_frames.py), to `InspectionCycle.run`, one row
per board with its verdict, whether a defect box lies on its defect, its checks and its times. The mask is registered
onto the Golden board again, the way the engine registers a board, from the frame the tool holds. A refusal ends a run
on the page, so the next frame starts a new run; a refusal before any frame is taken refuses every board left.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

from aoi.core.cycle import FrameMeta, InspectionCycle
from aoi.core.imaging import registration
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tools.proxy_stage1 import VIEW, board_mask, code_of
from tools.proxy_validation import Board, found

Change = Callable[[np.ndarray, np.ndarray | None], tuple[np.ndarray, np.ndarray | None]]
Item = tuple[Board, Change | None, str]  # a board, how its photo differs (None: the file as it is), a tag


class Frames:
    """A FrameSource over items: a frame read from its file by the cycle, or changed in memory and handed over."""

    def __init__(self, items: list[Item]) -> None:
        self.todo, self.given = list(items), list[tuple[Item, np.ndarray | None, np.ndarray | None, float]]()

    def grab(self) -> tuple[np.ndarray | None, FrameMeta] | None:
        if not self.todo:
            return None
        item = self.todo.pop(0)
        b, how, tag = item
        img = cv2.imread(str(b.path), cv2.IMREAD_COLOR)
        mask = board_mask(b, img.shape[:2]) if img is not None else None
        if how is not None and img is not None:
            img, mask = how(img, mask)
        self.given.append((item, img, mask, time.perf_counter()))
        name = b.path if how is None else b.path.with_name(f"{b.path.stem}_{tag}{b.path.suffix}")
        return (None if how is None else img), FrameMeta(name, VIEW)


def judge(
    ctx: AppContext,
    bm: str,
    items: list[Item],
    on_board: Callable[[int, dict[str, Any]], None] | None = None,
    cycle: InspectionCycle | None = None,
    src: Frames | None = None,
) -> list[dict[str, Any]]:
    """Each item through `InspectionCycle.run`, one row per item in order: its verdict, whether a defect box lies on
    its defect (the mask registered onto the Golden board the way the engine registers a board), the AI score, times,
    and the refusal that ended a run, if one did, after which the next item starts a new run. Only the cycle's own
    refusal is caught: an error in the tool's bookkeeping or in `on_board` stops the run loudly. A `cycle` given is
    the page's own, kept across board models as a changeover keeps it; a `src` given replaces the frames made from
    `items`."""
    src, rows = src or Frames(items), list[dict[str, Any]]()
    cycle = cycle or ctx.inspection_cycle()
    while src.todo:
        run = cycle.run(bm, src)
        while True:
            try:
                out = next(run, None)
            except AoiError as e:  # a refused frame (AOI-INSP-006, -010, -011 …) ends the run, as on the page
                if not src.given:  # refused before a frame was taken (AOI-INSP-016): no board goes, each is a row
                    rows += [refused(b, tag, e, taken=False) for b, _, tag in src.todo]
                    src.todo.clear()
                else:
                    (b, _, tag), *_ = src.given.pop(0)
                    rows.append(refused(b, tag, e))
                break
            if out is None:  # the run ended: no frame left, or a failed save ended it as the page does
                break
            rows.append(row(out, src.given.pop(0)))
            if on_board is not None:
                on_board(len(rows) - 1, rows[-1])
    return rows


def refused(b: Board, tag: str, e: AoiError, taken: bool = True) -> dict[str, Any]:
    """The row of a board refused with `e`: no verdict, so never OK and no escape; `taken` False when no frame was.
    It has every key a judged row has, so a reader never meets a missing one."""
    out = dict.fromkeys(("kind", "found", "ai", "checks", "ms", "wall_ms", "record_id", "save_error"))
    return out | {
        "board": b.path.name,
        "tag": tag,
        "label": b.label,
        "verdict": None,
        "refused": code_of(e),
        "taken": taken,
    }


def row(out: Any, given: tuple[Item, np.ndarray | None, np.ndarray | None, float]) -> dict[str, Any]:
    wall = time.perf_counter()
    (b, _, tag), img, mask, t0 = given
    res, ref = out.result, out.engine.reference
    hit = True  # no mask (a good board, or a file only the app can read): nothing to find
    if mask is not None and ref is None:  # no Golden board: the engine judges the image as it came
        hit = found([(d.x, d.y, d.w, d.h) for d in res.defects], mask > 127)
    elif mask is not None and ref is not None:
        h, _ = registration(img, ref, fine=out.engine.recipe.fine_alignment is True)
        size = (ref.shape[1], ref.shape[0])
        moved = (
            cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
            if h is None
            else cv2.warpPerspective(mask, h, size, flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
        ) > 127
        hit = found([(d.x, d.y, d.w, d.h) for d in res.defects], moved)
    checks = {c.name: (c.verdict, round(float(c.value), 4)) for c in res.checks}
    return {
        "board": b.path.name,
        "tag": tag,
        "label": b.label,
        "kind": "+".join(b.kinds) or None,
        "verdict": res.verdict,
        "found": hit,
        "ai": checks.get("AI anomaly score", (None, None))[1],
        "checks": checks,
        "ms": round(res.elapsed_ms, 1),
        "wall_ms": round((wall - t0) * 1000, 1),
        "record_id": out.record_id,
        "save_error": str(out.save_error) if out.save_error else None,
        "refused": None,
        "taken": True,
    }
