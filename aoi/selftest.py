"""The built app's self-test (REQ-SET-012, ADR 0007): `main.py --self-test WORKSPACE [BOARDS]` inspects one synthetic
board, with no window, and exits 0 when it gets the verdict expected of it.

The Windows build is windowed, so nothing can click in it on CI; tools/smoke_test_build.py runs the .exe this way to
show that the build inspects, not only that it opens. On a new or empty workspace folder, signed in as a new station's
first start signs in (its first Admin), it imports the golden board as an OK sample, which makes it the board model's
golden board, saves the recipe the synthetic regression set is judged with, and inspects the board through
`AppContext.inspect_file`, which saves the record as a run on the Inspection page does. One log line,
`selftest.verdict`, names the board, its verdict and the expected one.

BOARDS is the folder tools/make_selftest_data.py writes: the regression set's golden board and one of its boards, with
`selftest.json` (the recipe, the board and the verdict tests/regression/expected.json records for it); a built app
ships it as its own `selftest` folder (installer/aoi.spec). The boards are drawings, so a pass says the build judges as
the code does, never how well it finds defects. No Qt.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from .config import Settings
from .core.recipe import Recipe
from .core.services import AppContext

USAGE = "main.py --self-test WORKSPACE [BOARDS]: a new or empty folder, and one tools/make_selftest_data.py wrote"


def main(args: list[str]) -> int:
    """`main.py --self-test` with the arguments after it: 0 when the board gets its expected verdict; 1 when it gets
    another, or on any error once the workspace is open (logged there); 2 for wrong arguments, a folder that is not new
    and empty, or a workspace that does not open. A built app without BOARDS uses its own."""
    bundled = getattr(sys, "_MEIPASS", None)  # where a PyInstaller build keeps its files
    if not 1 <= len(args) <= 2 or (len(args) == 1 and bundled is None):
        print(USAGE, file=sys.stderr)  # a windowed build has no console: its exit code is what tells
        return 2
    workspace = Path(os.path.abspath(args[0]))
    boards = Path(args[1]) if len(args) == 2 else Path(str(bundled)) / "selftest"
    if workspace.exists() and (not workspace.is_dir() or any(workspace.iterdir())):
        print(f"{workspace} is not a new or empty folder; the self-test adds a board model to it", file=sys.stderr)
        return 2
    try:
        ctx = AppContext(Settings(workspace=str(workspace)))  # a new folder has no settings.json to read
    except Exception as e:  # never an unhandled error: a windowed build would wait for a click on its dialog
        print(f"The workspace did not open: {e}", file=sys.stderr)
        return 2
    try:
        return run(ctx, boards)
    except Exception:
        ctx.log.exception("selftest.error")
        return 1
    finally:
        ctx.close()


def run(ctx: AppContext, boards: Path) -> int:
    """Set up the board model of `boards/selftest.json` and inspect its board: 0 for the expected verdict, else 1."""
    spec = json.loads((boards / "selftest.json").read_text(encoding="utf-8"))
    recipe = Recipe.from_dict(spec["recipe"])
    ctx.set_user(ctx.start_user(setting_up=True))
    ctx.import_samples(recipe.board_model, [str(boards / spec["golden"])], "OK")  # the first OK: its golden board
    ctx.save_recipe(recipe, "self-test: the recipe the synthetic regression set is judged with")
    res = ctx.inspect_file(recipe.board_model, str(boards / spec["board"]))
    passed = res.verdict == spec["expected"]
    extra = {"board_model": recipe.board_model, "board": spec["board"], "verdict": res.verdict}
    extra |= {"expected": spec["expected"], "defects": len(res.defects), "passed": passed}
    ctx.log.log(logging.INFO if passed else logging.ERROR, "selftest.verdict", extra=extra)
    return 0 if passed else 1
