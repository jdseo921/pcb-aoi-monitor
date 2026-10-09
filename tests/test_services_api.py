"""REQ-USR-001, layering part (stage S15): the AppContext calls the screens use in place of the database."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.imaging import list_images
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import cell_text
from aoi.ui.pages.training import NgDialog
from tests.test_req_done_in_v01 import BOARD, _window


def test_req_usr_001_appcontext_reads_and_writes_what_the_screens_need(trained_ctx: AppContext, tmp_path: Path) -> None:
    ctx = trained_ctx
    assert ctx.board_models() == ["TINY"]
    ctx.ensure_board_model("NEW")
    assert ctx.board_models() == ["NEW", "TINY"]
    new = ctx.board_status("NEW")  # the default recipe is stored as revision 1 with the board model (S25a-2)
    assert (new.recipe_revision, new.recipe_is_default) == (1, True)
    samples, ok = ctx.samples("TINY"), ctx.samples("TINY", "OK")
    assert ok and len(ok) < len(samples) and all(Path(s["path"]).is_absolute() for s in samples)
    ctx.set_reference("TINY", ok[1]["id"])
    assert ctx.reference_image("TINY") == ctx.sample_path(ok[1]["id"]) == ok[1]["path"]
    ctx.update_sample(ok[0]["id"], "NG", "Scratch")
    assert next(s for s in ctx.samples("TINY", "NG") if s["id"] == ok[0]["id"])["defect_type"] == "Scratch"
    ctx.delete_sample(ok[0]["id"])
    assert all(s["id"] != ok[0]["id"] for s in ctx.samples("TINY"))
    (model,) = ctx.models("TINY")
    assert ctx.active_model("TINY") == model == ctx.model(model["id"]) and Path(model["path"]).is_file()
    assert ctx.export_model(model["id"], tmp_path / "exported.pt").read_bytes() == Path(model["path"]).read_bytes()
    ctx.inspect_file("TINY", ok[1]["path"])
    (row,) = ctx.inspections()
    assert row["board_model"] == "TINY" and Path(row["overlay_path"]).is_file()
    assert ctx.defects_for(row["id"]) == ctx.db.defects_for(row["id"])
    status = ctx.board_status("TINY")
    # one OK sample was relabelled NG and then removed
    assert (status.ok_samples, status.ng_samples) == (len(ok) - 1, len(samples) - len(ok))
    assert status.model_version == model["version"] and status.recipe_revision == 1 and status.last_test is None
    assert status.recipe_is_default, "the Home card still says the recipe uses defaults"
    assert (status.inspected, status.ng) == (1, int(row["result"] == "NG"))
    assert ctx.export_overlays(ctx.inspections(), tmp_path / "overlays") == 1
    assert ctx.inspections(board_model="OTHER") == [] and ctx.archive_old() == 0
    assert ctx.archive_old(-1) == 1  # a cutoff in the future, so the record saved this second counts
    assert ctx.inspections() == [] and len(ctx.inspections(include_archived=True)) == 1
    ctx.set_user("admin")  # users are an Admin's to change
    ctx.add_user("kim", "Engineer")
    assert ("kim", "Engineer") in [(u["name"], u["role"]) for u in ctx.users()]
    assert [h["revision"] for h in ctx.recipe_history("TINY")] == [1]  # revision 1: the stored default (S25a-2)
    assert ctx.save_recipe(ctx.recipe("TINY")[1]) == 2
    assert [h["revision"] for h in ctx.recipe_history("TINY")] == [2, 1]
    assert (ctx.board_status("TINY").recipe_revision, ctx.board_status("TINY").recipe_is_default) == (2, False)


def test_req_trn_007_only_an_ok_sample_can_be_the_reference(
    qtbot: QtBot, trained_ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """An NG sample never becomes the reference image that inspections compare against (#168): set_reference refuses it
    with AOI-TRN-006 before anything is written or audited, and the Training page shows that error; an OK sample still
    becomes the reference at once."""
    ctx = trained_ctx
    reference, entries, ng = ctx.reference_image(BOARD), ctx.audit_entries(), ctx.samples(BOARD, "NG")[0]
    with pytest.raises(AoiError) as refused:
        ctx.set_reference(BOARD, ng["id"])
    assert refused.value.code == "AOI-TRN-006"
    assert refused.value.what.startswith(f"Sample {Path(ng['path']).name} is labelled NG; only an OK")
    assert (ctx.reference_image(BOARD), ctx.audit_entries()) == (reference, entries)
    win = _window(qtbot, ctx)
    win.navigate("Training")
    page = win.pages["Training"]
    ok = ctx.samples(BOARD, "OK")[1]
    for sample in (ng, ok):
        page.samples.selectRow(
            next(r for r in range(page.samples.rowCount()) if cell_text(page.samples, r, 0) == str(sample["id"]))
        )
        page._set_reference()
    assert dialogs == [(f"AOI-TRN-006 {refused.value.entry.title}", f"{refused.value.what}\n\n{refused.value.action}")]
    assert ctx.reference_image(BOARD) == ok["path"] != reference
    assert win.statusBar().currentMessage().startswith("Reference image set: inspections compare against it now")


def test_req_trn_007_the_reference_sample_is_never_relabelled_ng_or_removed(
    qtbot: QtBot,
    ctx: AppContext,
    synthetic_dataset: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An import makes its first OK sample the reference; relabelling that sample NG, or removing it, is refused with
    AOI-TRN-007 before anything is written or audited, so inspections never compare against a board found defective
    (#168 review: before, the relabel went through and a good board was judged NG). Once another OK sample is the
    reference, the first can be relabelled and removed; the Training page shows the refusal."""
    defective = list_images(synthetic_dataset / "test" / "ng")[0]
    oks = list_images(synthetic_dataset / "train" / "ok")[:2]
    ctx.import_samples("B", [str(defective), *map(str, oks)], "OK")  # a defective board imported as OK by mistake
    first = ctx.samples("B", "OK")[0]
    assert ctx.reference_image("B") == first["path"]
    entries = ctx.audit_entries()
    for change, call in (("relabelled NG", lambda: ctx.update_sample(first["id"], "NG", "Missing Component")),
                         ("removed", lambda: ctx.delete_sample(first["id"]))):  # fmt: skip
        with pytest.raises(AoiError) as refused:
            call()
        assert refused.value.code == "AOI-TRN-007" and f"so it cannot be {change} while it is" in refused.value.what
    assert (ctx.samples("B", "OK")[0], ctx.audit_entries()) == (first, entries)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("engineer")
    win._on_board_model("B")
    win.navigate("Training")
    page = win.pages["Training"]
    page.samples.selectRow(
        next(r for r in range(page.samples.rowCount()) if cell_text(page.samples, r, 0) == str(first["id"]))
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    page._remove()
    assert [d[0] for d in dialogs] == ["AOI-TRN-007 Reference sample cannot change"]
    ctx.set_reference("B", ctx.samples("B", "OK")[1]["id"])
    ctx.update_sample(first["id"], "NG", "Missing Component")
    ctx.delete_sample(first["id"])
    assert all(s["id"] != first["id"] for s in ctx.samples("B"))


def test_req_trn_007_mark_ng_and_remove_skip_only_the_reference_whatever_the_selection_order(
    qtbot: QtBot,
    ctx: AppContext,
    synthetic_dataset: Path,
    dialogs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mark NG and Remove on several rows change every selected sample but the reference, which stays and is named in
    one AOI-TRN-007 dialog, whichever row was selected first (#168 review: before, the loop stopped at the reference,
    so the rows selected after it were silently left unchanged)."""
    ctx.import_samples("B", [str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:4]], "OK")
    ref, a, b, c = (s["id"] for s in ctx.samples("B", "OK"))
    assert ctx.reference_image("B") == ctx.sample_path(ref)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("engineer")
    win._on_board_model("B")
    win.navigate("Training")
    page = win.pages["Training"]
    monkeypatch.setattr(NgDialog, "exec", lambda self: self.type.setCurrentIndex(self.type.findData("Scratch")) or 1)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    def select(*ids: int) -> None:  # in this order: the reference first
        page.samples.clearSelection()
        rows = {int(cell_text(page.samples, r, 0)): r for r in range(page.samples.rowCount())}
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for i in ids:
            page.samples.selectionModel().select(page.samples.model().index(rows[i], 0), flags)

    select(ref, a, b)
    page._relabel("NG")
    assert {s["id"]: s["label"] for s in ctx.samples("B")} == {ref: "OK", a: "NG", b: "NG", c: "OK"}
    select(ref, c)
    page._remove()
    assert [s["id"] for s in ctx.samples("B")] == [ref, a, b]
    assert [d[0] for d in dialogs] == ["AOI-TRN-007 Reference sample cannot change"] * 2
