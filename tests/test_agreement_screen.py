"""REQ-TRN-016 on screen (Datasets stage, 2 of 4): Training's Datasets tab holds the labels sketch's Labeller agreement
panel. New Set makes a calibration set of 100 labelled images, the panel says who has labelled how many blind, Label
Blind… shows the set's images one by one with nothing that names their labels, and Run Agreement Check compares two
users who have labelled every image, the newest check shown against its targets. Under ADR 0002, until sign-in ships,
each labeller is a name picked in the header."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.times import to_local
from aoi.ui.pages.training import TrainingPage
from tests.test_label_editor import _page, _select, _wait
from tests.test_labeller_agreement import CAL, calibration_workspace, label_blind
from tests.test_req_done_in_v01 import BOARD

EMPTY = "No agreement check yet. Pick a set of 100 labelled images and two labellers."


def _shown_again(page: TrainingPage) -> None:
    """Training shown again, as after labelling elsewhere: it reads what changed meanwhile."""
    page.shell.navigate("Home")
    page.shell.navigate("Training")


def test_req_trn_016_new_set_and_agreement_check(qtbot: QtBot, trained_ctx: AppContext, tmp_path: Path) -> None:
    """Below 100 images labelled OK or NG, New Set is off and says so. On CAL it makes a set of all 100, which nobody
    has labelled blind yet; once kim and lee have labelled every image, Run Agreement Check compares them and shows 98
    of 100 and 18 of 20 reaching the targets; one labeller twice is refused before it runs; kim and park, 97 of 100,
    fall short. The Samples tab's keys act only while it is shown."""
    ctx = trained_ctx
    page = _page(qtbot, ctx)
    samples = calibration_workspace(ctx, tmp_path / "boards")  # after the window, which shows the first board model
    panel = page.agreement
    ref = Path(str(ctx.reference_image(BOARD))).name
    tiny = [s for s in ctx.samples(BOARD) if Path(s["path"]).name != ref]  # the reference cannot be marked UNSURE
    _select(page, tiny[0]["id"])
    _wait(page)
    page.tabs.setCurrentIndex(1)
    assert (
        not panel.btn_new.isEnabled()
        and panel.btn_new.toolTip() == f"Needs 100 images labelled OK or NG; {len(ctx.samples(BOARD))} are"
    )
    assert panel.progress.text() == "No calibration set yet: New Set draws 100 images labelled OK or NG."
    page.tabs.setFocus()  # on the Datasets tab, where nothing takes a typed letter
    QTest.keyClick(page.tabs, Qt.Key.Key_U)  # Mark UNSURE's key, the Samples tab's
    _wait(page)
    assert {s["uuid"]: s["label"] for s in ctx.samples(BOARD)}[tiny[0]["uuid"]] == tiny[0]["label"], "no key acts"
    page.shell._reload_board_models(CAL)
    assert panel.btn_new.isEnabled() and panel.ok_ng_line.text() == EMPTY
    panel.btn_new.click()
    cal = ctx.calibration_sets(CAL)[0]
    assert sorted(cal["sample_uuids"]) == sorted(s["uuid"] for s in samples) and panel.sets.currentData() == cal["uuid"]
    assert panel.sets.currentText() == f"{to_local(cal['at_utc'])} · made by engineer"
    assert panel.progress.text() == "Nobody has labelled this set blind yet."
    assert not panel.btn_run.isEnabled() and panel.btn_run.toolTip() == (
        "Two users must each label every image of the set blind first"
    )
    for user, n in (("kim", 0), ("lee", 2)):
        label_blind(ctx, user, cal["uuid"], samples, n, n)
    _shown_again(page)
    assert panel.progress.text() == "Labelled blind: kim 100 of 100 · lee 100 of 100"
    assert (panel.labeller_a.currentText(), panel.labeller_b.currentText()) == ("kim", "lee")
    panel.btn_run.click()
    assert panel.ok_ng_line.text() == "OK/NG agreement 98 of 100 (98 %) ✓ target 98 %"
    assert panel.type_line.text() == "Defect type 18 of 20 (90 %) ✓ target 90 %"
    check = ctx.agreement_checks(CAL)[0]
    assert panel.by_line.text() == f"kim and lee, checked {to_local(check['at_utc'])} by engineer"
    assert page.shell.statusBar().currentMessage() == "The labellers agree"
    panel.labeller_b.setCurrentIndex(0)
    assert not panel.btn_run.isEnabled() and panel.btn_run.toolTip() == "Pick two different labellers"
    label_blind(ctx, "park", cal["uuid"], samples, 3, 3)
    _shown_again(page)
    panel.labeller_b.setCurrentIndex(panel.labeller_b.findText("park"))
    panel.btn_run.click()
    assert panel.ok_ng_line.text() == "OK/NG agreement 97 of 100 (97 %) ✗ target 98 %"
    assert panel.type_line.text() == "Defect type 17 of 20 (85 %) ✗ target 90 %"
    assert page.shell.statusBar().currentMessage() == "The labellers fall short of the targets"
    assert len(ctx.agreement_checks(CAL)) == 2
    page.tabs.setCurrentIndex(0)
    page.shell._reload_board_models(BOARD)
    _select(page, tiny[1]["id"])
    _wait(page)
    page.samples.setFocus()
    QTest.keyClick(page.samples, Qt.Key.Key_U)
    _wait(page)
    assert {s["uuid"]: s["label"] for s in ctx.samples(BOARD)}[tiny[1]["uuid"]] == "UNSURE", "shown, its keys act"


def test_req_trn_016_label_blind(qtbot: QtBot, trained_ctx: AppContext, tmp_path: Path) -> None:
    """Label Blind… swaps the tabs for the set's images one by one, "Image 1 of 100", with no file name of the image
    anywhere in the window; O labels it OK and N, once a defect type is picked, NG, each stored as the user's blind
    label, the image's own label untouched, and the next image shown; the Samples tab's O, N and Esc act on nothing
    meanwhile, an image selected there keeping its label. Stop (Esc) keeps what was labelled and Label Blind… goes on
    from the next image; a sign-in closes the panel; the last image closes it and says so, and Label Blind… is then off
    for that user, saying why."""
    ctx = trained_ctx
    page = _page(qtbot, ctx)
    samples = calibration_workspace(ctx, tmp_path / "boards")
    page.shell._reload_board_models(CAL)
    ng = next(s for s in ctx.samples(CAL) if s["label"] == "NG")
    _select(page, ng["id"])  # O typed on the Samples tab would mark it OK
    _wait(page)
    page.tabs.setCurrentIndex(1)
    panel, blind = page.agreement, page.blind
    assert not panel.btn_blind.isEnabled(), "no set yet"
    panel.btn_new.click()
    cal = ctx.calibration_sets(CAL)[0]
    images = cal["sample_uuids"]
    by_uuid = {s["uuid"]: s for s in samples}
    assert panel.btn_blind.isEnabled() and panel.btn_blind.text() == "Label Blind…"
    panel.btn_blind.click()
    assert page.stack.currentWidget() is blind and not page.tabs.isVisible()
    qtbot.waitUntil(blind.act_ok.isEnabled, timeout=10000)
    assert blind.heading.text() == "Image 1 of 100" and blind.shown == images[0]
    texts = " ".join(w.text() for w in page.shell.findChildren(QLabel) if w.isVisible())
    assert Path(by_uuid[images[0]]["path"]).name not in texts, "the file name can name its label"
    assert not blind.act_ng.isEnabled() and blind.btn_ng.toolTip() == "Pick its defect type first"
    QTest.keyClick(blind.view, Qt.Key.Key_O)
    qtbot.waitUntil(lambda: blind.shown == images[1], timeout=10000)
    assert blind.heading.text() == "Image 2 of 100" and blind.type_box.currentData() is None
    blind.type_box.setCurrentIndex(blind.type_box.findData("Scratch"))
    assert blind.act_ng.isEnabled() and blind.btn_ng.toolTip() == "N"
    blind.view.setFocus()
    QTest.keyClick(blind.view, Qt.Key.Key_N)
    qtbot.waitUntil(lambda: blind.shown == images[2], timeout=10000)
    me = str(ctx.user_uuid)
    assert ctx.db.blind_labels(cal["uuid"], me) == {images[0]: ("OK", None), images[1]: ("NG", "Scratch")}
    assert len(ctx.audit_entries(action="label.blind")) == 2
    assert {s["uuid"]: s["label"] for s in ctx.samples(CAL)} == {s["uuid"]: s["label"] for s in samples}
    QTest.keyClick(blind.view, Qt.Key.Key_Escape)
    assert page.stack.currentIndex() == page.tabs.currentIndex() == 1 and page.tabs.isVisible()
    assert page.shell.statusBar().currentMessage() == "Stopped with 2 of 100 images labelled blind"
    assert panel.progress.text() == "Labelled blind: engineer 2 of 100"
    panel.btn_blind.click()
    qtbot.waitUntil(blind.act_ok.isEnabled, timeout=10000)
    assert blind.heading.text() == "Image 3 of 100" and blind.shown == images[2]
    page.shell.set_user("kim")
    assert page.stack.currentIndex() == 1 and page.tabs.isVisible() and blind.set_uuid is None
    assert page.shell.statusBar().currentMessage() == "Stopped with 2 of 100 images labelled blind"
    ctx.set_user("engineer")
    for uuid in images[2:-1]:
        s = by_uuid[uuid]
        ctx.label_blind(cal["uuid"], uuid, str(s["label"]), s["defect_type"])  # type: ignore[arg-type]
    page.shell.set_user("engineer")
    panel.btn_blind.click()
    qtbot.waitUntil(blind.act_ok.isEnabled, timeout=10000)
    assert blind.heading.text() == "Image 100 of 100"
    blind.act_ok.trigger()
    assert page.stack.currentIndex() == 1 and page.tabs.isVisible()
    assert page.shell.statusBar().currentMessage() == "You have labelled all 100 images of the set blind"
    assert panel.progress.text() == "Labelled blind: engineer 100 of 100"
    assert not panel.btn_blind.isEnabled()
    assert panel.btn_blind.toolTip() == "You have labelled every image of this set blind"
    assert {s["uuid"]: s["label"] for s in ctx.samples(CAL)} == {s["uuid"]: s["label"] for s in samples}
    assert len(ctx.audit_entries(action="label.blind")) == 100
