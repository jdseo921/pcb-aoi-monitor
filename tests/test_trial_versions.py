"""REQ-TRN-004, REQ-TRN-005, REQ-TRN-012 and REQ-TST-008 for B1 of the 2026-10 business-readiness brief (decision D1;
ADR 0020): one person freezes, splits and locks a Trial dataset version and trains from it, with no second user's label
check and no agreement check. The version and every AI model trained from it are marked Trial wherever they are named;
a Trial AI model goes live while no Validated one has, and never replaces one (ADR 0020, decision 4, as Jay decided on
2026-10-14); the go-live gate then, and the customer validation report always, refuse it with a plain message and
Start the Checks; the Validated path keeps today's checks and is marked Validated. Results on synthetic boards prove a
code path; they are never quoted as accuracy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core import datasets, explain
from aoi.core.imaging import save_image
from aoi.core.labels import DefectBox
from aoi.core.services import FIRST_LIVE, AppContext, ErrorReport
from aoi.errors import AoiError
from aoi.ui import errors as ui_errors
from aoi.ui.main_window import MainWindow
from aoi.ui.pages import base
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.pages.model_test import ModelTestPage
from aoi.ui.pages.training import TrainingPage
from tests.conftest import log_rows
from tests.test_customer_validation_report import with_agreement
from tests.test_datasets import agree, ready
from tests.test_freeze_screen import _datasets, _idle
from tests.test_labeller_agreement import CAL
from tests.test_req_done_in_v01 import BOARD as TINY
from tests.test_test_dataset import held_out
from tests.test_train_from_version import BOARD, boards
from tools.trainable import trainable

ONE = "ONE-1"  # a board model one person works alone
TRIAL_LINE = (
    "Trial: one person froze DS-ONE1-R1-TOP-v1 without a second person checking its labels or an agreement check, so"
    " this AI model can judge boards only while no Validated AI model of its board model has gone live, and cannot"
    " back a customer validation report."
)


def one_person(ctx: AppContext, folder: Path, n_ok: int = 80, n_ng: int = 20) -> list[dict[str, Any]]:
    """ONE-1's `n_ok` OK and `n_ng` NG (Scratch) images of 32 x 32 px, each different and each NG one boxed, imported
    by the admin alone into the admin's new dataset store of Acme: nobody else labels or checks anything."""
    ctx.set_user("admin")
    folder.mkdir()
    rng = np.random.default_rng(20)
    for i in range(n_ok + n_ng):
        save_image(folder / f"board_{i:03d}.png", rng.integers(0, 256, (32, 32, 3), dtype=np.uint8))
    paths = [str(p) for p in sorted(folder.glob("*.png"))]
    ctx.import_samples(ONE, paths[:n_ok], "OK")
    ctx.import_samples(ONE, paths[n_ok:], "NG", "Scratch")
    for s in ctx.samples(ONE, "NG"):
        ctx.set_boxes(s["uuid"], [DefectBox(1, 2, 8, 6, "Scratch")])
    ctx.move_in(ONE, ctx.create_store("Acme")["uuid"])
    return ctx.samples(ONE)


def trial_trained(ctx: AppContext, folder: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """ONE-1 as `one_person` leaves it, frozen as a Trial version, split, locked and trained from by the admin alone:
    the version and the training's metadata."""
    one_person(ctx, folder)
    version = ctx.freeze_dataset(ONE, "Top", "R1", "Acme", trial=True)
    ctx.lock_validation_set(version["uuid"], seed=1)
    return version, ctx.train(version["uuid"], epochs=1, image_size=32)


def kept_inactive(ctx: AppContext) -> None:
    """ONE-1's AI models all inactive, as a Trial AI model trained before Live until Validated was left by the go-live
    gate of the time (ADR 0020, decision 4 as first written)."""
    ctx.db.execute("UPDATE models SET active=0 WHERE board_model=?", (ONE,))


def validated_live(ctx: AppContext, version: dict[str, Any]) -> dict[str, Any]:
    """A Validated version of ONE-1 that holds `version`'s locked validation images back too, trained and made active
    by hand: the metadata of its training."""
    split = cast(dict[str, Any], ctx.validation_split(version["uuid"]))
    locked = {i["sample_uuid"] for i in ctx.dataset_items(version["uuid"]) if i["uuid"] in split["validation"]}
    meta = ctx.train(trainable(ctx, ONE, customer="Acme", held=locked), epochs=1, image_size=32)
    ctx.activate_model(int(next(m for m in ctx.models(ONE) if m["version"] == meta["version"])["id"]))
    return meta


def refusal(call: Any, *args: Any, **kwargs: Any) -> AoiError:
    with pytest.raises(AoiError) as e:
        call(*args, **kwargs)
    return e.value


def test_req_trn_004_one_person_freezes_splits_and_locks_a_trial_version(ctx: AppContext, tmp_path: Path) -> None:
    """With no label checked by a second user and no agreement check, a Validated freeze is refused as before, and the
    gate says a Trial freeze is not: the Trial version names no agreement check, its manifest says so, its audit entry
    names it Trial, and the same person splits and locks it with the validation set minimums unchanged (50 OK, 30 % of
    the NG). The refusals a Trial version still meets hold: another customer than the store's."""
    samples = one_person(ctx, tmp_path / "boards")
    assert all(s["checked_by"] is None for s in samples) and ctx.agreement_checks(ONE) == []
    assert refusal(ctx.freeze_dataset, ONE, "Top", "R1", "Acme").code == "AOI-TRN-020"
    gate = ctx.freeze_gate(ONE, "Top", "R1")
    assert cast(AoiError, gate["refused"]).code == "AOI-TRN-020" and gate["refused_trial"] is None
    assert refusal(ctx.freeze_dataset, ONE, "Top", "R1", "Other", trial=True).code == "AOI-TRN-027"

    version = ctx.freeze_dataset(ONE, "Top", "R1", "Acme", trial=True)
    assert (version["name"], version["assurance"]) == ("DS-ONE1-R1-TOP-v1", "Trial")
    assert version["agreement_check_uuid"] == ""
    assert version["frozen_by"] == ctx.user_uuid == ctx.db.user_uuid("admin")
    checked = ctx.verify_dataset(version["uuid"])
    assert checked["manifest"] == "same" and not checked["changed"] and not checked["missing"]
    [entry] = ctx.audit_entries(action="dataset.freeze")
    assert (entry["after"]["assurance"], entry["after"]["agreement_check_uuid"]) == ("Trial", "")
    split = ctx.lock_validation_set(version["uuid"], seed=1)
    labels = {i["uuid"]: i["label"] for i in ctx.dataset_items(version["uuid"])}
    held = [labels[u] for u in split["validation"]]
    assert (held.count("OK"), held.count("NG")) == (datasets.VALIDATION_OK, 6)  # 30 % of 20 NG
    assert ctx.datasets(ONE)[0]["assurance"] == "Trial"


def test_req_trn_012_a_trial_ai_model_is_marked_trial_and_goes_live_while_no_validated_one_has(
    ctx: AppContext, tmp_path: Path
) -> None:
    """The same person trains from the Trial version: its AI model is v1.0 (Trial), in its files' names as v1.0-trial,
    its card's first line says in plain words what Trial means, and its model.train entry names it Trial. As a board
    model's first AI model it goes live when trained, audited as an activation with the first AI model's reason (ADR
    0018; ADR 0020, decision 4, "Live until Validated"). A second AI model of the version is v1.1 (Trial) and installs
    inactive, as every later one does; with no Validated one live, it is activated by hand and rolled back like any."""
    version, meta = trial_trained(ctx, tmp_path / "boards")
    assert (meta["version"], meta["assurance"], meta["activated"]) == ("v1.0 (Trial)", "Trial", True)
    assert meta["not_live"] is None
    [model] = ctx.models(ONE)
    assert Path(model["path"]).name == "ONE-1_v1.0-trial.pt"
    assert cast(dict[str, Any], ctx.active_model(ONE))["version"] == "v1.0 (Trial)" and ctx.inactive_model(ONE) is None
    assert ctx.validated_live(ONE) is None
    card = ctx.model_card(int(model["id"])) or {}
    assert card["first_line"].startswith(TRIAL_LINE) and card["identity"]["assurance"] == "Trial"
    assert (ctx.card_text(int(model["id"])) or "").startswith(f"# Model card: ONE-1 v1.0 (Trial)\n\n**{TRIAL_LINE}")
    [trained] = ctx.audit_entries(action="model.train")
    assert (trained["after"]["version"], trained["after"]["assurance"]) == ("v1.0 (Trial)", "Trial")
    [live] = ctx.audit_entries(action="model.activate")
    assert (live["after"]["active_version"], live["reason"]) == ("v1.0 (Trial)", FIRST_LIVE)
    again = ctx.train(version["uuid"], epochs=1, image_size=32)
    assert (again["version"], again["activated"], again["not_live"]) == ("v1.1 (Trial)", False, None)
    ctx.activate_model(int(ctx.models(ONE)[0]["id"]))
    assert cast(dict[str, Any], ctx.active_model(ONE))["version"] == "v1.1 (Trial)"
    assert ctx.rollback_model(ONE)["version"] == "v1.0 (Trial)"


def test_req_trn_004_the_validated_path_keeps_its_checks_and_is_marked_validated(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    """A version frozen with every label checked and an agreed check is Validated, names its check, and its audit entry
    says so; an AI model trained from a Validated version keeps its plain name and goes live as the first (ADR 0018).
    A Validated AI model waiting beside a Trial one is the one Inspection offers."""
    samples, cal = ready(ctx, tmp_path / "cal")
    agree(ctx, cal, samples)
    version = ctx.freeze_dataset(CAL, "Top", "R3", "Acme")
    assert version["assurance"] == "Validated"
    assert version["agreement_check_uuid"] == ctx.agreement_checks(CAL)[0]["uuid"]
    assert ctx.audit_entries(action="dataset.freeze")[0]["after"]["assurance"] == "Validated"
    boards(ctx, synthetic_dataset, 21)
    meta = ctx.train(trainable(ctx, BOARD, uses=("own", "demos")), epochs=1, image_size=32, use="demos")
    assert (meta["version"], meta["assurance"], meta["activated"]) == ("v1.0", "Validated", False)  # demos: inactive
    trial = ctx.train(trainable(ctx, BOARD, assurance="Trial"), epochs=1, image_size=32)
    assert (trial["version"], trial["activated"], trial["not_live"]) == ("v1.1 (Trial)", False, None)  # not the first
    assert cast(dict[str, Any], ctx.inactive_model(BOARD))["version"] == "v1.0"  # newest Validated first


def test_req_tst_008_the_customer_validation_report_refuses_a_trial_version(trained_ctx: AppContext) -> None:
    """A run on a Trial version's locked validation set, or of an AI model trained from one, makes no customer
    validation report: AOI-TST-009 says why in plain words and names the board model and view for Start the Checks;
    the run stays stored."""
    ctx = trained_ctx
    with_agreement(ctx)
    oks, ngs = ctx.samples(TINY, "OK")[-4:], ctx.samples(TINY, "NG")[-2:]
    version = trainable(ctx, TINY, held=[s["uuid"] for s in oks + ngs], assurance="Trial")
    run_uuid = ctx.test_dataset(version)[1][0]["run_uuid"]
    e = refusal(ctx.validation_report_data, run_uuid)
    name = ctx.datasets(TINY)[0]["name"]
    assert (e.code, e.params["board"], e.params["view"]) == ("AOI-TST-009", TINY, "Top")
    assert str(e.what) == (
        f"No customer validation report was made: the run tested the locked validation set of {name}, a Trial version"
        " that one person froze without a second person checking its labels or an agreement check."
    )
    assert ctx.test_run(run_uuid) is not None
    validated, _ = held_out(ctx)  # the active AI model on a Validated version, as if it had been trained from a Trial
    run_uuid = ctx.test_dataset(validated)[1][0]["run_uuid"]
    trial = {"name": name, "board_model": TINY, "view": "Top"}
    ctx.trial_version = lambda model: trial  # type: ignore[method-assign]
    e = refusal(ctx.validation_report_data, run_uuid)
    assert e.code == "AOI-TST-009" and f"trained from {name}, a Trial version" in str(e.what)


def test_req_trn_005_freeze_sheet_offers_trial_and_the_versions_table_names_it(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Freeze sheet opens on Validated, its lines ✗ and Freeze off while nobody else has checked a label; Trial
    says the checks are not needed and what Trial means, and Freeze as Trial freezes a Trial version, which the
    Versions table's Checks column and Training's Dataset version list name Trial; Enter on Trial freezes, as Enter
    in the revision field does. The Split sheet's title and Export Manifest's question and file name name it Trial too.
    The sheet opens on Validated again."""
    one_person(ctx, tmp_path / "boards")
    ctx.set_user("engineer")  # the window signs in the engineer; the admin works alone below
    page = _datasets(qtbot, ctx)
    page.shell.set_user("admin")
    page.shell._reload_board_models(ONE)
    sheet = page.working.sheet
    page.working.btn_freeze.click()
    sheet.revision.setText("R1")
    assert sheet.validated.isChecked() and not sheet.btn_now.isEnabled() and sheet.btn_now.text() == "Freeze"
    assert [line.text()[0] for line in sheet.lines] == ["✗", "✗", "✓", "✗"] and not sheet.trial_line.isVisible()
    sheet.trial.click()
    assert [line.text() for line in sheet.lines] == [
        "– Not needed for a Trial version: Every NG label checked by a second user",
        "– Not needed for a Trial version: 0 of 8 OK labels checked (10 % of 80)",
        "✓ Customer Acme, whose dataset store holds it",
        "– Not needed for a Trial version: Agreement check reached its targets",
    ]
    assert sheet.trial_line.isVisible() and sheet.btn_now.text() == "Freeze as Trial" and sheet.btn_now.isEnabled()
    sheet.trial.setFocus()
    qtbot.keyClick(sheet.trial, Qt.Key.Key_Return)  # Enter freezes from the choice too, as from the revision field
    _idle(qtbot, page)
    [version] = ctx.datasets(ONE)
    assert version["assurance"] == "Trial" and version["frozen_by"] == ctx.db.user_uuid("admin")
    assert page.shell.statusBar().currentMessage().startswith("Froze DS-ONE1-R1-TOP-v1 as a Trial version")
    t = page.versions.table
    assert t.horizontalHeaderItem(1).text() == "Checks" and base.cell_text(t, 0, 1) == "Trial"
    assert page.dataset_version.currentText() == "DS-ONE1-R1-TOP-v1 (Trial)"
    page.versions.split.open_for(version, page.versions.counts[version["uuid"]])
    assert page.versions.split.title() == "Split and lock the validation set of DS-ONE1-R1-TOP-v1 (Trial)"
    page.versions.split.close_sheet()
    asked: list[str] = []
    named: list[str] = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, text, *a: asked.append(text) or QMessageBox.Yes)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda _p, _t, start, *a: named.append(start) or ("", ""))
    page.versions.table.selectRow(0)
    page.versions.export_manifest()
    assert asked == [
        f"Export the manifest of DS-ONE1-R1-TOP-v1 (Trial): {len(ctx.dataset_items(version['uuid']))}"
        " files, one row each?"
    ]
    assert Path(named[0]).name == "DS-ONE1-R1-TOP-v1-trial.csv"
    page.working.btn_freeze.click()
    assert sheet.validated.isChecked() and sheet.btn_now.text() == "Freeze"


def test_req_trn_012_start_the_checks_from_the_refusal_and_activate_on_inspection(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Trial AI model that waits with none active, as one trained before Live until Validated was left, is named on
    Inspection's model line with Activate, which makes it live, and What is missing's Trial list is done. With a
    Validated one live, Activate Selected on the Trial AI model shows AOI-TRN-052 with Start the Checks beside OK, which
    opens Training on the board model's Samples tab with Show Unchecked; Roll Back to it is greyed, saying why; and a
    Trial AI model trained then is said not to replace the Validated one."""
    version, _ = trial_trained(ctx, tmp_path / "boards")
    kept_inactive(ctx)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.set_user("admin")
    win._reload_board_models(ONE)
    assert win.navigate("Inspection")
    insp = cast(InspectionPage, win.pages["Inspection"])
    insp._show_waiting()
    assert insp.ai_line.text().startswith("AI model v1.0 (Trial) of ONE-1 is trained but not active:")
    assert insp.btn_activate.text() == "Activate v1.0 (Trial)" and insp.btn_activate.isEnabled()
    insp.btn_activate.click()
    assert cast(dict[str, Any], ctx.active_model(ONE))["version"] == "v1.0 (Trial)" and insp.ai_row.isHidden()
    assert win.navigate("Home")
    cast(Any, win.pages["Home"]).guide.btn_cards.click()  # Show All Steps ›: the first-run guide shows what it made
    done = cast(Any, win.pages["Home"]).missing_list
    assert done.trial.isChecked() and done.done_line.text() == (
        "Nothing a Trial version needs is missing: ONE-1 has an active AI model. Pick Validated to see what a Validated"
        " version needs."
    )

    validated_live(ctx, version)
    shown: list[tuple[ErrorReport, tuple[str, Any] | None]] = []
    monkeypatch.setattr(base, "show_error", lambda parent, report, act=None: shown.append((report, act)))
    assert win.navigate("Training")
    page = cast(TrainingPage, win.pages["Training"])
    page.refresh()
    row = next(r for r in range(page.models.rowCount()) if base.cell_text(page.models, r, 1) == "v1.0 (Trial)")
    page.models.selectRow(row)
    page.tabs.setCurrentIndex(1)
    page.activate()
    [(report, act)] = shown
    assert report.code == "AOI-TRN-052" and act is not None and act[0] == "Start the Checks"
    assert "AOI-TRN-052" not in [a["code"] for a in ctx.alarms()], "approved: said, never an ERROR alarm"
    with monkeypatch.context() as m:  # a theme that hides Training offers no button the window would refuse
        m.setattr(win, "hidden", lambda title: title == "Training")
        assert page.error_act(AoiError("AOI-TRN-052", version="v1.0 (Trial)", board=ONE, dataset="D")) is None
    act[1]()
    assert win.stack.currentWidget() is page and page.tabs.currentIndex() == 0
    assert page.filter.currentData() == "Unchecked" and page.samples.rowCount() == 20  # the NG labels to check
    assert cast(dict[str, Any], ctx.active_model(ONE))["version"] == "v1.1"
    assert page.btn_rollback.text() == "Roll Back to v1.0 (Trial)" and not page.btn_rollback.isEnabled()
    assert page.btn_rollback.toolTip().startswith("A Trial AI model never replaces a Validated one")
    later = {"version": "v1.2 (Trial)", "train_seconds": 1, "board_model": ONE, "assurance": "Trial"}
    page._on_done({**later, "activated": False, "not_live": None})
    assert win.statusBar().currentMessage() == (
        "AI model v1.2 (Trial) trained from a Trial version: Validated AI model v1.1 still judges the boards of ONE-1,"
        " because a Trial AI model never replaces a Validated one. Start the Checks to freeze a Validated version and"
        " train from it."
    )


def test_req_trn_012_the_error_dialog_carries_the_step_it_names(qtbot: QtBot) -> None:
    """The error dialog with a step: its button beside OK, OK still the default and Esc's; closed with the button, the
    step is taken once, closed with OK or Esc it is not. A Trial refusal shows the information icon, another error the
    critical one."""
    report = ErrorReport.of(AoiError("AOI-TRN-052", version="v1.0 (Trial)", board=ONE, dataset="DS-ONE1-R1-TOP-v1"))
    box = ui_errors.ErrorBox(None, report, "Start the Checks")
    qtbot.addWidget(box)
    assert box.act is not None and box.act.text() == "Start the Checks"
    assert box.defaultButton() is box.button(QMessageBox.StandardButton.Ok) and not box.acted()
    box.show()
    box.act.click()
    assert box.acted()
    assert box.icon() == QMessageBox.Icon.Information  # a step taken as approved, not a failure
    escaped = ui_errors.ErrorBox(None, report, "Start the Checks")
    qtbot.addWidget(escaped)
    escaped.show()
    qtbot.keyClick(escaped, Qt.Key.Key_Escape)  # Esc closes it with OK, the second button beside it or not
    assert not escaped.isVisible() and not escaped.acted()
    plain = ui_errors.ErrorBox(None, report)
    qtbot.addWidget(plain)
    assert plain.act is None and not plain.acted()
    other = ui_errors.ErrorBox(None, ErrorReport.of(AoiError("AOI-TRN-044", store="Acme", reason="r")))
    qtbot.addWidget(other)
    assert other.icon() == QMessageBox.Icon.Critical
    assert json.loads(json.dumps(sorted(ui_errors.START_CHECKS))) == ["AOI-TRN-052", "AOI-TST-009"]


def test_req_trn_012_a_validated_ai_model_after_trial_ones_that_did_not_go_live_is_the_first(
    ctx: AppContext, tmp_path: Path
) -> None:
    """With none active, as when the Trial AI models trained before Live until Validated were left inactive, the first
    Validated AI model trained goes live when its training ends, as a board model's first does (ADR 0018)."""
    version, _ = trial_trained(ctx, tmp_path / "boards")
    kept_inactive(ctx)
    split = cast(dict[str, Any], ctx.validation_split(version["uuid"]))
    locked = {i["sample_uuid"] for i in ctx.dataset_items(version["uuid"]) if i["uuid"] in split["validation"]}
    meta = ctx.train(trainable(ctx, ONE, customer="Acme", held=locked), epochs=1, image_size=32)
    assert (meta["version"], meta["assurance"], meta["activated"]) == ("v1.1", "Validated", True)
    assert cast(dict[str, Any], ctx.validated_live(ONE))["version"] == "v1.1"
    assert ctx.audit_entries(action="model.activate")[0]["reason"] == FIRST_LIVE


def test_req_trn_012_a_trial_ai_model_never_replaces_a_validated_one(ctx: AppContext, tmp_path: Path) -> None:
    """With a Trial AI model live, a Validated one installs inactive, as any later version, and What is missing's
    Validated list offers to activate it; once it is live, the go-live gate refuses a Trial AI model with AOI-TRN-052,
    activated or rolled back to, naming the board model and view Start the Checks opens, and nothing changes. A model
    number a run left a file of is never taken, under either name: v1.1's file makes the next AI model v1.2 (Trial)."""
    version, _ = trial_trained(ctx, tmp_path / "boards")
    events = [r["event"] for r in log_rows(ctx.settings.root / "logs")]
    assert "training.first_not_live" not in events
    folder = Path(ctx.models(ONE)[0]["path"]).parent
    (folder / f"{ONE}_v1.1.pt").write_bytes(b"left by a run that stopped (#178)")
    again = ctx.train(version["uuid"], epochs=1, image_size=32)
    assert (again["version"], again["activated"]) == ("v1.2 (Trial)", False)
    split = cast(dict[str, Any], ctx.validation_split(version["uuid"]))
    locked = {i["sample_uuid"] for i in ctx.dataset_items(version["uuid"]) if i["uuid"] in split["validation"]}
    validated = ctx.train(trainable(ctx, ONE, customer="Acme", held=locked), epochs=1, image_size=32)
    assert (validated["version"], validated["assurance"], validated["activated"]) == ("v1.3", "Validated", False)
    assert cast(dict[str, Any], ctx.active_model(ONE))["version"] == "v1.0 (Trial)"
    waits = ctx.missing(ONE, trial=False)
    assert [n.key for n in waits.needs if not n.done][-1] == "active" and waits.model_id == ctx.models(ONE)[0]["id"]
    ctx.activate_model(int(ctx.models(ONE)[0]["id"]))
    assert cast(dict[str, Any], ctx.validated_live(ONE))["version"] == "v1.3"
    entries = len(ctx.audit_entries(action="model.activate"))
    trial = next(m for m in ctx.models(ONE) if m["version"] == "v1.2 (Trial)")
    for call, arg in ((ctx.activate_model, int(trial["id"])), (ctx.rollback_model, ONE)):
        e = refusal(call, arg)
        assert (e.code, e.params["board"], e.params["view"]) == ("AOI-TRN-052", ONE, "Top")
        assert e.params["dataset"] == version["name"]
        said = "of board model ONE-1 was not made active: a Validated AI model already judges the boards of ONE-1,"
        assert str(e.what).startswith(f"AI model {e.params['version']} {said} and a Trial AI model never replaces one.")
    assert cast(dict[str, Any], ctx.active_model(ONE))["version"] == "v1.3"
    assert len(ctx.audit_entries(action="model.activate")) == entries and not ctx.audit_entries(action="model.rollback")
    live = cast(dict[str, Any], ctx.active_model(ONE))
    meta = json.loads(live["metrics"])
    for metrics in (json.dumps({k: v for k, v in meta.items() if k != "assurance"}), "{not json"):
        ctx.db.execute("UPDATE models SET metrics=? WHERE uuid=?", (metrics, live["uuid"]))  # before 0027, or damaged
        assert ctx.validated_live(ONE) is not None and not ctx.is_trial(live)
        assert refusal(ctx.activate_model, int(trial["id"])).code == "AOI-TRN-052"
    ctx.db.execute("UPDATE models SET metrics=? WHERE uuid=?", (live["metrics"], live["uuid"]))
    later = ctx.train(version["uuid"], epochs=1, image_size=32)
    assert (later["version"], later["activated"], later["not_live"]) == ("v1.4 (Trial)", False, None)


def test_req_trn_012_screens_offer_activate_for_a_trial_ai_model_that_waits(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path
) -> None:
    """Where a screen names a Trial AI model that waits with none active, it offers Activate, as for any version, since
    no Validated one has gone live: Home's step card, AI Model Test's empty state and Compare's note on a board judged
    without it. AI Model Test's source list and history name a Trial version so, which its report and CSV then carry.
    Training's version line and the Freeze sheet say a Trial AI model can judge boards only while no Validated one has
    gone live."""
    version, _ = trial_trained(ctx, tmp_path / "boards")
    kept_inactive(ctx)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.set_user("admin")
    win._reload_board_models(ONE)
    assert win.navigate("Home")
    home = cast(Any, win.pages["Home"])
    home.guide.btn_cards.click()  # Show All Steps ›: the first-run guide's Train would make it active
    step = "AI model v1.0 (Trial) trained, not active. Activate it on Training."
    assert home.status_labels["Train AI model"].text() == step
    assert win.navigate("AI Model Test")
    test = cast(ModelTestPage, win.pages["AI Model Test"])
    assert test.empty.sentence.text().startswith("Activate it on Training.")
    assert test.source.itemText(0).startswith(f"{version['name']} (Trial): its locked validation set, ")
    judged = cast(explain.InspectionResult, type("Judged", (), {"notes": [explain.NO_AI_NOTE]})())
    [note] = explain.notes(judged, inactive="v1.0 (Trial)")
    assert note.template == explain.INACTIVE_AI_NOTE and note.values == {"version": "v1.0 (Trial)"}
    assert win.navigate("Training")
    page = cast(TrainingPage, win.pages["Training"])
    page.dataset_version.setCurrentIndex(page.dataset_version.findData(version["uuid"]))
    assert page.version_line.text().startswith(
        "Trial version: an AI model trained from it is marked Trial and can judge boards only while no Validated AI"
        " model has gone live."
    )
    assert page.working.sheet.trial_line.text() == (
        "A Trial version and every AI model trained from it are marked Trial: such an AI model can judge boards only"
        " while no Validated AI model has gone live, and never backs a customer validation report."
    )
