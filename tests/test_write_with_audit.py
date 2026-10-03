"""#178: a write and its audit entry commit together or not at all (REQ-LOG-004), and a training run whose registration
fails keeps the Golden board in use and never reuses a file name a result may name (REQ-CMP-003)."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from aoi.config import Settings
from aoi.core.imaging import load_image, save_image
from aoi.core.services import AppContext
from tests.test_req_done_in_v01 import BOARD
from tests.test_roles_and_audit import WRITES

ROOT = Path(__file__).resolve().parents[1]


def _fail_audit(monkeypatch: pytest.MonkeyPatch, ctx: AppContext, action: str) -> None:
    """The audit entry `action` cannot be written, as with a full disk or a database another program holds."""
    add = ctx.db.add_audit

    def add_or_fail(*a: Any) -> str:
        if a[2] == action:
            raise sqlite3.OperationalError("database or disk is full")
        return add(*a)

    monkeypatch.setattr(ctx.db, "add_audit", add_or_fail)


def _state(ctx: AppContext, out: Path) -> set[str]:
    """Every row of the database, and every file in the workspace (logs and the database aside) and in `out`."""
    files = [p for root in (ctx.settings.root, out) for p in root.rglob("*") if p.is_file()]
    kept = {str(p) for p in files if "logs" not in p.parts and not p.name.startswith("aoi.sqlite")}
    return set(ctx.db._conn.iterdump()) | kept


@pytest.mark.parametrize("method", list(WRITES))
def test_req_log_004_a_write_whose_audit_entry_fails_leaves_nothing(
    method: str, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    action, call = WRITES[method]
    trained_ctx.set_user("admin", "Admin")  # every write's role
    out = tmp_path / "out"
    out.mkdir()
    before = _state(trained_ctx, out)
    _fail_audit(monkeypatch, trained_ctx, action)
    with pytest.raises(sqlite3.OperationalError):
        call(trained_ctx, synthetic_dataset, out)
    assert _state(trained_ctx, out) ^ before == set()  # no row, revision or file without its entry


def test_req_log_004_a_recipe_revision_and_its_entry_survive_a_crash_together(workspace: Settings) -> None:
    script = f"""
import os
from aoi.config import Settings
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
ctx = AppContext(Settings(workspace={workspace.workspace!r}, device="cpu"))
ctx.set_user("engineer", "Engineer")
ctx.ensure_board_model("B1")
add = ctx.db.add_audit
ctx.db.add_audit = lambda *a: os._exit(9) if a[2] == "recipe.save" else add(*a)  # the process dies in between
ctx.save_recipe(Recipe.from_dict({{**Recipe(board_model="B1").to_dict(), "warn_ratio": 2.1}}))
"""
    assert subprocess.run([sys.executable, "-c", script], cwd=ROOT, timeout=120).returncode == 9
    ctx = AppContext(workspace)
    assert ctx.recipe("B1")[0] == 1 and ctx.recipe("B1")[1].warn_ratio != 2.1
    assert ctx.audit_entries(action="recipe.save") == []
    ctx.close()


def test_req_trn_010_a_run_that_fails_to_register_keeps_the_golden_board(
    trained_ctx: AppContext, ng_board: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = trained_ctx
    golden, entries = ctx.reference_image(BOARD), ctx.audit_entries()
    with monkeypatch.context() as m:
        m.setattr(ctx.db, "register_model", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
        with pytest.raises(sqlite3.OperationalError):
            ctx.train(BOARD, epochs=1, image_size=32)
    assert ctx.reference_image(BOARD) == golden and ctx.audit_entries() == entries
    assert [m["version"] for m in ctx.models(BOARD)] == ["v1.0"]
    assert not list((ctx.settings.models_dir / BOARD).glob("*v1.1*"))  # the failed run's files are removed
    ctx.inspect_file(BOARD, str(ng_board))
    rid = ctx.inspections()[0]["id"]
    ctx.train(BOARD, epochs=1, image_size=32)
    assert ctx.judged_reference(rid)[1] == "same"


def test_req_cmp_003_training_never_writes_over_a_golden_board_a_result_names(
    trained_ctx: AppContext, ng_board: Path
) -> None:
    ctx = trained_ctx
    left = ctx.settings.models_dir / BOARD / f"{BOARD}_v1.1_golden.png"  # a run that died before it was registered
    img = load_image(str(ctx.reference_image(BOARD)))
    img[:20] = 0
    save_image(left, img)
    ctx.db.set_reference(BOARD, str(left))  # in use, as the code before #178 left it
    ctx.inspect_file(BOARD, str(ng_board))
    rid, judged = ctx.inspections()[0]["id"], left.read_bytes()
    ctx.train(BOARD, epochs=1, image_size=32)
    assert [m["version"] for m in ctx.models(BOARD)] == ["v1.2", "v1.0"]
    assert left.read_bytes() == judged and ctx.judged_reference(rid)[1] == "same"
