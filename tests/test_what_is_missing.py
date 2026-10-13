"""REQ-TRN-021 for B3 of the 2026-10 business-readiness brief (F6): one source of truth for how many images a board
model needs, `datasets.needs`, computed from the constants in aoi/core/datasets.py, and `AppContext.missing`, What is
missing, which Home and Training show. Each test walks a workspace through the stages of completeness and checks each
line's count against its requirement and the one action that fixes it, for a Validated and for a Trial version.
Results on synthetic boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

import dataclasses
import re
from collections import Counter
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from aoi.core import datasets, labels
from aoi.core.imaging import save_image
from aoi.core.labels import DefectBox
from aoi.core.services import FIXES, NEEDS_ORDER, TRIAL_NEEDS, AppContext, Missing, Need
from aoi.ui import theme
from aoi.ui.main_window import HomePage, MainWindow
from aoi.ui.pages.missing_list import CALLS, FIX_TEXT, MissingList
from aoi.ui.pages.training import TrainingPage
from tests.test_datasets import agree
from tests.test_i18n import _messages
from tests.test_labeller_agreement import CAL, calibration_workspace
from tests.test_trial_versions import ONE, one_person
from tools.update_translations import TS_FILE

ROOT = Path(__file__).resolve().parents[1]


def lines(missing: Missing) -> dict[str, tuple[int, int, str, str | None]]:
    """Each line of What is missing as (have, need, fix, after), by key."""
    return {n.key: (n.have, n.need, n.fix, n.after) for n in missing.needs}


def _boards(folder: Path, n: int, seed: int) -> list[str]:
    """`n` different images of 32 x 32 px in `folder`, new: their paths."""
    folder.mkdir()
    rng = np.random.default_rng(seed)
    for i in range(n):
        save_image(folder / f"more_{i:03d}.png", rng.integers(0, 256, (32, 32, 3), dtype=np.uint8))
    return [str(p) for p in sorted(folder.glob("*.png"))]


def test_req_trn_021_one_sentence_from_the_constants() -> None:
    """The counts the sentence states are the constants' own: 70 OK of one view, 20 to train and 50 held out, one or
    more NG images, and the 100 images of a calibration set; no other count of OK images is written in a screen."""
    assert datasets.OK_NEEDED == datasets.VALIDATION_OK + datasets.TRAIN_OK == 70
    assert datasets.NG_NEEDED == 1 and labels.CALIBRATION_IMAGES == 100
    assert str(datasets.needs()) == (
        "A board model needs at least 70 OK images of one view (20 to train, 50 held out to test) and 1 or more NG"
        " images with every defect boxed; a Validated version also needs 100 images labelled OK or NG for the"
        " agreement check."
    )
    stated = re.compile(r"\b(?:20|50|70) (?:OK|good)\b|\bat least (?:20|50|70)\b")
    own = [
        f"{p.relative_to(ROOT)}:{i}"
        for p in sorted((ROOT / "aoi" / "ui").rglob("*.py"))
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if stated.search(line)
    ]
    assert own == []


def test_req_trn_021_the_sentence_is_the_one_every_document_gives() -> None:
    """The manual, the README and the customer document say how many images a board model needs in the same sentence
    the screens show, so no document states counts of its own (F6); the Korean customer document in the sentence the
    Korean screens show."""
    sentence = str(datasets.needs())
    for doc in ("README.md", "docs/manual/engineer.md", "docs/demo/for-clients.md"):
        text = " ".join((ROOT / doc).read_text(encoding="utf-8").split())  # its line breaks as spaces
        assert sentence in text, doc
    needs = datasets.needs()
    korean = _messages(TS_FILE)[needs.context, needs.source].format(**needs.values)  # as the Korean screens say it
    assert korean and korean in " ".join((ROOT / "docs/demo/ko/for-clients.md").read_text(encoding="utf-8").split())


def test_req_trn_021_validated_stages(ctx: AppContext, tmp_path: Path) -> None:
    """A board model walked from nothing to an active AI model by a Validated version: at each stage each line counts
    what it holds against what it needs, its fix is the one action that gets it there, and a line whose action needs
    an earlier one waits for it; a line not reached yet counts against the requirement (10 % of 70 is 7 checks). An AI
    model whose registry row cannot be read, which Training says to train again (AOI-TRN-012), is not counted."""
    empty = ctx.missing(CAL)
    assert (empty.board_model, empty.view, empty.trial, empty.left) == (CAL, "Top", False, len(NEEDS_ORDER))
    assert tuple(n.key for n in empty.needs) == NEEDS_ORDER and set(FIXES) == set(FIX_TEXT) == set(CALLS)
    assert lines(empty) == {
        "ok": (0, 70, "add_ok", None),
        "ng": (0, 1, "add_ng", None),
        "ng_boxed": (0, 1, "draw_boxes", "ng"),
        "ng_checked": (0, 1, "show_unchecked", "ng_boxed"),
        "ok_checked": (0, 7, "draw_ok_checks", "ok"),
        "calibration": (0, 100, "add_ok", None),
        "agreement": (0, 1, "agreement", "ng"),
        "locked": (0, 1, "freeze", "ok"),
        "trained": (0, 1, "train", "locked"),
        "active": (0, 1, "activate", "trained"),
    }
    assert (empty.version_uuid, empty.model_id) == (None, None)

    samples = calibration_workspace(ctx, tmp_path / "boards")  # 80 OK and 20 NG, no box drawn, nothing checked
    some = lines(ctx.missing(CAL))
    assert some["ok"] == (80, 70, "add_ok", None) and some["ng"] == (20, 1, "add_ng", None)
    assert some["ng_boxed"] == (0, 20, "draw_boxes", None)
    assert some["ng_checked"] == (0, 20, "show_unchecked", "ng_boxed")
    assert some["ok_checked"] == (0, 8, "draw_ok_checks", None) and some["calibration"] == (100, 100, "add_ok", None)
    assert some["agreement"] == (0, 1, "agreement", None) and some["locked"][3] == "ng_boxed"

    ctx.set_user("admin")
    ctx.move_in(CAL, ctx.create_store("Acme")["uuid"])
    ctx.set_user("engineer")
    for s in ctx.samples(CAL, "NG"):
        ctx.set_boxes(s["uuid"], [DefectBox(1, 2, 8, 6, "Scratch")])
    ctx.set_user("kim")
    draw = ctx.draw_ok_checks(CAL, "Top", seed=5) or {}
    drawn = lines(ctx.missing(CAL))
    assert drawn["ng_boxed"] == (20, 20, "draw_boxes", None) and drawn["ok_checked"] == (0, 8, "show_unchecked", None)
    for uid in [s["uuid"] for s in ctx.samples(CAL, "NG")] + draw["sample_uuids"]:
        ctx.check_label(uid)
    cal = ctx.make_calibration_set(CAL, [str(s["uuid"]) for s in samples])
    ctx.set_user("engineer")
    checked = lines(ctx.missing(CAL))
    assert checked["ng_checked"] == (20, 20, "show_unchecked", None) and checked["ok_checked"][:2] == (8, 8)
    assert checked["agreement"] == (0, 1, "agreement", None) and checked["locked"] == (0, 1, "freeze", "agreement")

    agree(ctx, cal, ctx.samples(CAL))
    agreed = ctx.missing(CAL)
    assert lines(agreed)["agreement"][:2] == (1, 1) and lines(agreed)["locked"] == (0, 1, "freeze", None)
    assert agreed.left == 3

    version = ctx.freeze_dataset(CAL, "Top", "R1", "Acme", ("own", "shared")) or {}
    frozen = ctx.missing(CAL)
    assert lines(frozen)["locked"] == (0, 1, "split", None) and frozen.version_uuid == version["uuid"]
    assert lines(frozen)["trained"][3] == "locked"

    more = _boards(tmp_path / "more", 10, seed=17)  # images added after the freeze: lines of the next version only
    ctx.import_samples(CAL, more, "OK")
    added = lines(ctx.missing(CAL))
    assert added["ok_checked"] == (8, 9, "draw_ok_checks", None)  # 10 % of 90, one more to draw
    assert added["locked"] == (0, 1, "split", None)  # the version frozen before is split all the same

    ctx.lock_validation_set(version["uuid"], seed=1)
    locked = ctx.missing(CAL)
    assert lines(locked)["locked"] == (1, 1, "freeze", None) and lines(locked)["trained"] == (0, 1, "train", None)
    assert locked.version_uuid == version["uuid"] and locked.left == 3

    meta = ctx.train(version["uuid"], epochs=1, image_size=32, use="shared")  # installed inactive: another use
    trained = ctx.missing(CAL)
    assert not meta["activated"] and lines(trained)["trained"][:2] == (1, 1)
    assert lines(trained)["active"] == (0, 1, "activate", None) and trained.left == 2
    model = ctx.models(CAL)[0]
    assert trained.model_id == model["id"]

    second = ctx.freeze_dataset(CAL, "Top", "R1", "Acme", trial=True) or {}  # a newer Trial AI model, never live
    ctx.lock_validation_set(second["uuid"], seed=2)
    assert not ctx.train(second["uuid"], epochs=1, image_size=32)["activated"]
    assert ctx.missing(CAL).trial and ctx.missing(CAL, trial=False).model_id == model["id"]  # not the Trial one

    ctx.activate_model(model["id"])
    done = ctx.missing(CAL, trial=False)
    assert lines(done)["active"][:2] == (1, 1) and done.model_id is None
    assert [n.key for n in done.needs if not n.done] == ["ok_checked"]  # for a next version

    for damage in ("{not json", "[]"):  # the active AI model's registry row, changed by hand
        ctx.db.execute("UPDATE models SET metrics=? WHERE uuid=?", (damage, model["uuid"]))
        damaged = ctx.missing(CAL, trial=False)
        assert lines(damaged)["trained"][:2] == lines(damaged)["active"][:2] == (0, 1) and damaged.model_id is None
        assert lines(ctx.missing(CAL, trial=True))["trained"][:2] == (1, 1)  # the Trial AI model


def test_req_trn_021_trial_stages(ctx: AppContext, tmp_path: Path) -> None:
    """A Trial version needs only the images, the boxes, a locked validation set and an AI model trained from it: no
    second-user check, no agreement check and no active AI model, since a Trial AI model never goes live (ADR 0020).
    With no choice given, the list is for the newest version's kind, a Validated one before the first freeze; the
    Validated list never counts a Trial version or the AI model trained from it."""
    assert lines(ctx.missing(ONE, trial=True)) == {
        "ok": (0, 70, "add_ok", None),
        "ng": (0, 1, "add_ng", None),
        "ng_boxed": (0, 1, "draw_boxes", "ng"),
        "locked": (0, 1, "freeze", "ok"),
        "trained": (0, 1, "train", "locked"),
    }
    one_person(ctx, tmp_path / "boards")  # 80 OK and 20 NG, each NG one boxed, in Acme's store; nothing checked
    assert ctx.missing(ONE).trial is False
    trial = ctx.missing(ONE, trial=True)
    assert tuple(n.key for n in trial.needs) == TRIAL_NEEDS and trial.trial
    assert lines(trial) == {
        "ok": (80, 70, "add_ok", None),
        "ng": (20, 1, "add_ng", None),
        "ng_boxed": (20, 20, "draw_boxes", None),
        "locked": (0, 1, "freeze", None),
        "trained": (0, 1, "train", "locked"),
    }
    validated = lines(ctx.missing(ONE, trial=False))
    assert validated["ng_checked"] == (0, 20, "show_unchecked", None) and validated["locked"][3] == "ng_checked"

    version = ctx.freeze_dataset(ONE, "Top", "R1", "Acme", trial=True) or {}
    frozen = ctx.missing(ONE)  # the newest version is a Trial one
    assert frozen.trial and lines(frozen)["locked"] == (0, 1, "split", None) and frozen.version_uuid == version["uuid"]
    assert lines(ctx.missing(ONE, trial=False))["locked"][2] == "freeze"  # a Trial version is no Validated one

    ctx.lock_validation_set(version["uuid"], seed=1)
    assert lines(ctx.missing(ONE))["trained"] == (0, 1, "train", None)
    ctx.import_samples(ONE, _boards(tmp_path / "more", 3, seed=18), "NG", "Scratch")  # not boxed yet
    added = lines(ctx.missing(ONE))
    assert added["ng_boxed"] == (20, 23, "draw_boxes", None) and added["trained"] == (0, 1, "train", None)
    meta = ctx.train(version["uuid"], epochs=1, image_size=32)
    done = ctx.missing(ONE)
    assert not meta["activated"] and [n.key for n in done.needs if not n.done] == ["ng_boxed"]
    assert "active" not in lines(done)
    validated = lines(ctx.missing(ONE, trial=False))
    assert validated["locked"][:2] == validated["trained"][:2] == validated["active"][:2] == (0, 1)


def test_req_trn_021_the_view_counted(ctx: AppContext, tmp_path: Path) -> None:
    """Before any freeze, the view with the most images labelled OK or NG, Top first among equals; the counts are that
    view's alone, as a version holds one view."""
    assert ctx.missing(CAL).view == "Top"
    folder = tmp_path / "boards"
    folder.mkdir()
    for i in range(3):
        save_image(folder / f"board_{i}.png", np.full((32, 32, 3), 40 * i, np.uint8))
    paths = [str(p) for p in sorted(folder.glob("*.png"))]
    ctx.import_samples(CAL, paths[:1], "OK")
    ctx.import_samples(CAL, paths[1:], "OK", side="Side")
    missing = ctx.missing(CAL)
    assert missing.view == "Side" and lines(missing)["ok"][:2] == (2, 70)
    assert lines(missing)["calibration"][:2] == (3, 100)  # a calibration set draws from every view


def test_req_trn_021_each_kind_counts_its_own_versions(ctx: AppContext, tmp_path: Path) -> None:
    """A Trial version of the Side view, the newest: the Trial list counts Side, its view; the Validated list counts
    no Trial version, so the view with the most images, Top."""
    one_person(ctx, tmp_path / "boards")  # 80 OK and 20 NG of Top
    ctx.import_samples(ONE, _boards(tmp_path / "side", 5, seed=19), "OK", side="Side")
    ctx.freeze_dataset(ONE, "Side", "R1", "Acme", trial=True)
    trial = ctx.missing(ONE)
    assert trial.trial and trial.view == "Side" and lines(trial)["ok"][:2] == (5, 70)
    validated = ctx.missing(ONE, trial=False)
    assert validated.view == "Top" and lines(validated)["ok"][:2] == (80, 70)
    assert lines(validated)["locked"][2] == "freeze" and validated.version_uuid is None


def test_req_trn_021_a_version_training_cannot_use_is_not_counted(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path
) -> None:
    """A version with 60 OK images may be split, its validation set taking 50, but its training set would hold 10 of
    the 20 training needs: the list offers no Split for it, the Split sheet says so, and once locked it does not count
    as the locked validation set; the line waits for the OK images, Freeze Dataset… its fix (ADR 0022, Decision 6)."""
    one_person(ctx, tmp_path / "boards", n_ok=60)
    version = ctx.freeze_dataset(ONE, "Top", "R1", "Acme", trial=True) or {}
    assert ctx.train_ok_after_split(version["uuid"]) == 10
    frozen = ctx.missing(ONE)
    assert lines(frozen)["locked"] == (0, 1, "freeze", "ok") and frozen.version_uuid is None

    win = _window(qtbot, ctx, ONE)
    assert win.navigate("Training")
    page = cast(TrainingPage, win.pages["Training"])
    page.versions.split.open_for(version, page.versions.counts[version["uuid"]])
    said = page.versions.split.what.text()
    assert "training set the rest: 10 OK, fewer than the 20 training needs" in said and "70 OK images" in said
    page.versions.split.close_sheet()

    ctx.lock_validation_set(version["uuid"], seed=1)  # 50 OK files: the lock allows it
    locked = ctx.missing(ONE)
    assert lines(locked)["locked"] == (0, 1, "freeze", "ok") and lines(locked)["trained"][3] == "locked"
    assert locked.version_uuid is None


def _window(qtbot: QtBot, ctx: AppContext, board_model: str, user: str = "engineer") -> MainWindow:
    """The main window at 1366 x 768 with `board_model` in the header, `user` signed in, Home shown."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1366, 768)
    win.show()
    qtbot.waitExposed(win)
    win.set_user(user)
    win._on_board_model(board_model)
    assert win.navigate("Home")
    return win


def shown(missing: MissingList) -> dict[str, tuple[str, str, str, str, bool]]:
    """Each line the list shows, by key: its mark, its count (after its name), the line under it, its button's text
    (none once done) and whether that button is on."""
    return {
        key: (w.mark.text(), w.name.text().rsplit(": ", 1)[1].replace("\xa0", " "),
              w.first.text() if w.first.isVisibleTo(missing) else "",
              w.fix.text() if w.fix.isVisibleTo(missing) else "", w.fix.isEnabled())
        for key, w in missing.lines.items()
        if w.name.isVisibleTo(missing)
    }  # fmt: skip


def test_req_trn_021_home_and_training_show_what_is_missing(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Home, under its cards, and Training's What is missing tab show the list for the board model in the header: the
    sentence, the board model and view, each line's count against its requirement and the button that fixes it, greyed
    with the line it waits for named under it. Validated is the list before any freeze; Trial shows only what a Trial
    version needs. Each button takes its step on Training: Show Unchecked, Freeze Dataset… for a Trial version, Split
    and Lock Validation Set…, Start Training from the locked version. The list follows each step."""
    one_person(ctx, tmp_path / "boards")  # 80 OK and 20 NG, each NG one boxed, in Acme's store; nothing checked
    win = _window(qtbot, ctx, ONE)
    home = cast(HomePage, win.pages["Home"])
    listed = home.missing_list
    assert listed.isVisible() and listed.sentence.text() == str(datasets.needs())
    assert listed.validated.isChecked() and listed.view_line.text() == "ONE-1, Top view: 6 of 10 still missing"
    first = "First: NG labels checked by a second user"
    assert shown(listed) == {
        "ok": ("✓", "80 of 70", "", "", False),
        "ng": ("✓", "20 of 1", "", "", False),
        "ng_boxed": ("✓", "20 of 20", "", "", False),
        "ng_checked": ("○", "0 of 20", "", "Show Unchecked ›", True),
        "ok_checked": ("○", "0 of 8", "", "Draw OK Labels to Check", True),
        "calibration": ("✓", "100 of 100", "", "", False),
        "agreement": ("○", "0 of 1", "", "Open Labeller Agreement ›", True),
        "locked": ("○", "0 of 1", first, "Freeze Dataset…", False),
        "trained": ("○", "0 of 1", "First: Locked validation set", "Start Training", False),
        "active": ("○", "0 of 1", "First: Trained AI model", "Activate AI Model", False),
    }
    assert listed.lines["locked"].fix.toolTip() == first  # and on a press, as the line under it says
    listed.lines["ng_checked"].fix.click()  # Home's button: Training, where the step is taken
    page = cast(TrainingPage, win.pages["Training"])
    assert win.stack.currentWidget() is page and page.tabs.currentIndex() == 0
    assert page.filter.currentData() == "Unchecked"

    page.tabs.setCurrentIndex(2)
    trial = page.missing_list
    assert trial.isVisible() and trial is not listed
    shot = page.stack.currentWidget().grab().toImage()  # the tab scrolls: on the page's background, not Qt's grey
    every = range(0, shot.width(), 7)
    colours = Counter(shot.pixelColor(x, y).name() for x in every for y in range(0, shot.height(), 7))
    assert colours.most_common(1)[0][0] == theme.BG.lower(), colours.most_common(3)
    trial.trial.click()
    assert shown(trial) == {
        "ok": ("✓", "80 of 70", "", "", False),
        "ng": ("✓", "20 of 1", "", "", False),
        "ng_boxed": ("✓", "20 of 20", "", "", False),
        "locked": ("○", "0 of 1", "", "Freeze Dataset…", True),
        "trained": ("○", "0 of 1", "First: Locked validation set", "Start Training", False),
    }
    trial.lines["locked"].fix.click()
    sheet = page.working.sheet
    assert page.tabs.currentIndex() == 1 and sheet.isVisible() and sheet.trial.isChecked()
    sheet.close_sheet()

    version = ctx.freeze_dataset(ONE, "Top", "R1", "Acme", trial=True) or {}
    page.tabs.setCurrentIndex(2)  # the list is read as its tab is shown
    assert trial.trial.isChecked() and shown(trial)["locked"][3:] == ("Split and Lock Validation Set…", True)
    trial.lines["locked"].fix.click()
    assert page.versions.split.isVisible() and page.versions.split.version is not None
    assert page.versions.split.version["uuid"] == version["uuid"]
    page.versions.split.close_sheet()

    ctx.lock_validation_set(version["uuid"], seed=1)
    page.tabs.setCurrentIndex(2)
    page.refresh()  # and on every refresh while it is shown
    assert shown(trial)["locked"][:2] == ("✓", "1 of 1") and shown(trial)["trained"][3:] == ("Start Training", True)
    started: list[str] = []
    monkeypatch.setattr(ctx, "start_training", lambda uuid, *_a, **_k: started.append(uuid))
    trial.lines["trained"].fix.click()
    assert started == [version["uuid"]] and page.dataset_version.currentData() == version["uuid"]

    assert win.navigate("Home")
    assert listed.trial.isChecked() and listed.view_line.text() == "ONE-1, Top view: 1 of 5 still missing"


def test_req_trn_021_the_other_buttons_and_roles(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Draw Boxes › puts the first NG image of the view with no box in the label editor; Activate AI Model activates
    the version the list names. An Operator sees the list on Home with every button greyed, its tooltip naming the role
    the step needs. With no board model the list is gone, and another board model's list is of its own kind."""
    calibration_workspace(ctx, tmp_path / "boards")  # 80 OK and 20 NG, no box drawn
    win = _window(qtbot, ctx, CAL)
    home = cast(HomePage, win.pages["Home"])
    assert shown(home.missing_list)["ng_boxed"] == ("○", "0 of 20", "", "Draw Boxes ›", True)
    home.missing_list.lines["ng_boxed"].fix.click()
    page = cast(TrainingPage, win.pages["Training"])
    first = sorted((s for s in ctx.samples(CAL, "NG")), key=lambda s: s["id"])[0]
    assert page.tabs.currentIndex() == 0 and page.filter.currentData() == "NG"
    assert [s["uuid"] for s in page._picked()] == [first["uuid"]]

    activated: list[int] = []
    monkeypatch.setattr(ctx, "activate_model", activated.append)
    real = ctx.missing
    met = [dataclasses.replace(n, have=n.need, after=None) for n in real(CAL).needs if n.key != "active"]
    ready = [*met, Need("active", 0, 1, "activate")]  # only the AI model's activation left, as after a training
    monkeypatch.setattr(ctx, "missing", lambda bm, trial=None: dataclasses.replace(real(bm, trial), needs=tuple(ready),
                                                                                   model_id=7))  # fmt: skip
    assert win.navigate("Home")
    assert shown(home.missing_list)["active"] == ("○", "0 of 1", "", "Activate AI Model", True)
    home.missing_list.lines["active"].fix.click()
    assert activated == [7] and win.stack.currentWidget() is page
    monkeypatch.setattr(ctx, "missing", real)

    page.tabs.setCurrentIndex(2)  # with the tab shown, no board model, then one again: the list is read again
    win._on_board_model("")
    assert not page.missing_list.isVisible()
    win._on_board_model(CAL)
    assert page.missing_list.isVisible() and page.missing_list.view_line.text().startswith(CAL)

    win.set_user("operator")
    assert win.navigate("Home")
    buttons = [w.fix for w in home.missing_list.lines.values() if w.fix.isVisibleTo(home.missing_list)]
    assert len(buttons) >= 5  # every line not met, Freeze Dataset… to Activate AI Model among them
    for b in buttons:
        assert not b.isEnabled() and "needs the Engineer or Admin role" in b.toolTip(), b.text()
    win._on_board_model("")
    assert not home.missing_list.isVisible()


def test_req_trn_021_training_states_the_sentence(qtbot: QtBot, ctx: AppContext) -> None:
    """Training's tip and its empty Samples table say how many images a board model needs in the one sentence."""
    ctx.ensure_board_model("EMPTY-1")
    win = _window(qtbot, ctx, "EMPTY-1")
    assert win.navigate("Training")
    page = cast(TrainingPage, win.pages["Training"])
    assert page.tip.text() == str(datasets.needs())
    assert page.samples_empty.sentence.text().startswith(f"{datasets.needs()} Add them with Add OK Images…")
