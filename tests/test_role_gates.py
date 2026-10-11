"""REQ-USR-001: a control the role signed in may not use stays on screen, greyed, never hidden (the presenter theme
aside), with the refusal its AppContext call would raise as its tooltip; a press on it says the same on the status bar,
as a touch screen shows no tooltip, and the page's empty state names what the role may not do there. Home's cards say
which role each step needs, and its Export card where the PDF reports are."""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core.services import REQUIRED_ROLE, ROLES, AppContext
from aoi.ui.main_window import NAV, HomePage, MainWindow
from aoi.ui.pages.compare import ComparePage
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.pages.logs import LogsPage
from aoi.ui.pages.model_test import ModelTestPage
from aoi.ui.pages.training import TrainingPage
from tests.conftest import listed

ROOT = Path(__file__).resolve().parents[1]
USERS = {"Operator": "operator", "Engineer": "engineer", "Admin": "admin"}


def _window(qtbot: QtBot, ctx: AppContext) -> MainWindow:
    ctx.ensure_board_model("B")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win


def _gated(win: MainWindow) -> dict[str, list[tuple[QWidget, str]]]:
    """Each page's controls a role may not use, with the AppContext call each makes; "" for the header's."""
    logs = cast(LogsPage, win.pages["Logs & Export"])
    test = cast(ModelTestPage, win.pages["AI Model Test"])
    training = cast(TrainingPage, win.pages["Training"])
    return {
        "": [(win.btn_new, "ensure_board_model")],
        "Logs & Export": [
            (logs.btn_csv, "export_csv_files"),
            (logs.btn_img, "export_overlays"),
            (logs.btn_arch, "archive_old"),
            (logs.btn_delete, "delete_inspections"),
            (logs.btn_train, "add_false_call_sample"),
        ],
        "Inspection": [(cast(InspectionPage, win.pages["Inspection"]).btn_save, "export_board_image")],
        "Compare": [
            (cast(ComparePage, win.pages["Compare"]).tryout, "re_evaluate"),
            (cast(ComparePage, win.pages["Compare"]).btn_try, "re_evaluate"),
            (cast(ComparePage, win.pages["Compare"]).btn_save, "save_recipe"),
        ],
        "AI Model Test": [
            (test.btn_csv, "export_csv"),
            (test.btn_img, "export_test_overlays"),
            (test.btn_report, "export_report"),
            (test.btn_validation, "export_report"),
        ],
        "Training": [(training.btn_remove, "delete_sample"), (training.versions.btn_export, "export_csv")],
    }


def _may(role: str, call: str) -> bool:
    return ROLES.index(role) >= ROLES.index(REQUIRED_ROLE[call])


def _press(win: MainWindow, control: QWidget) -> None:
    """A press as a finger or the mouse makes it, through the window, so a greyed control's parent sees it too."""
    at = control.mapTo(win, control.rect().center() if control.width() < 200 else QPoint(20, 20))
    QTest.mouseClick(win.windowHandle(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)


def test_req_usr_001_a_control_the_role_may_not_use_is_greyed_with_why_never_hidden(
    qtbot: QtBot, ctx: AppContext
) -> None:
    """For each role, on each page it may open: every role-gated control is there, greyed with the refusal its call
    raises as its tooltip for a role below the call's, which a press shows on the status bar; for a role that may, its
    own tooltip, no line on a press."""
    win = _window(qtbot, ctx)
    for role, user in USERS.items():
        win.set_user(user)
        for title, controls in _gated(win).items():
            if title:
                assert win.navigate(title) == (role in win.pages[title].roles), (role, title)
                if role not in win.pages[title].roles:
                    continue
                listed(qtbot, win.pages[title])
            gates = win.pages[title].gates if title else win.gates
            for control, call in controls:
                name = f"{role} {title or 'header'} {call}"
                assert not control.isHidden() and control in gates.own, name
                if _may(role, call):
                    assert control.toolTip() == gates.own[control] and control not in gates.why, name
                    continue
                why = f"needs the {'Admin' if REQUIRED_ROLE[call] == 'Admin' else 'Engineer or Admin'} role."
                assert not control.isEnabled() and control.toolTip().endswith(why), name
                if control.isVisible():  # Export Manifest…'s tab may be another
                    win.statusBar().clearMessage()
                    _press(win, control)
                    assert win.statusBar().currentMessage() == control.toolTip(), name


def test_req_usr_001_a_field_of_compares_greyed_panel_says_who_may_on_a_press(qtbot: QtBot, ctx: AppContext) -> None:
    """Compare's Try other thresholds, greyed for an Operator: a press on a field of it, on its tick, or on Re-evaluate
    or Save to Recipe, which take a press for themselves, says why on the status bar, and each button's tooltip says
    it in place of its key, which does nothing for an Operator."""
    win = _window(qtbot, ctx)
    win.set_user("operator")
    assert win.navigate("Compare")
    compare = cast(ComparePage, win.pages["Compare"])
    assert compare.tryout.isVisible() and not compare.diff_thr.isEnabled() and not compare.btn_try.isEnabled()
    re_evaluate = "Re-evaluating a result needs the Engineer or Admin role."
    for control, said in (
        (compare.diff_thr, re_evaluate),
        (compare.ai_thr.tick, re_evaluate),
        (compare.btn_try, re_evaluate),
        (compare.btn_save, "Saving a recipe needs the Engineer or Admin role."),
    ):
        win.statusBar().clearMessage()
        _press(win, control)
        assert win.statusBar().currentMessage() == said, control
    assert (compare.btn_try.toolTip(), compare.btn_save.toolTip()) == (re_evaluate, compare.gates.why[compare.btn_save])
    assert not compare.act_try.isEnabled() and not compare.act_save.isEnabled()  # Ctrl+R and Ctrl+S with them
    win.set_user("engineer")
    assert (compare.btn_try.toolTip(), compare.btn_save.toolTip()) == ("Ctrl+R", "Ctrl+S")


def test_req_usr_001_a_press_on_a_greyed_sidebar_entry_says_who_may_open_it(qtbot: QtBot, ctx: AppContext) -> None:
    """A greyed sidebar entry takes no click; a press on it says on the status bar which role opens its page, as its
    tooltip does, for a touch screen, and the page shown stays."""
    win = _window(qtbot, ctx)
    win.set_user("operator")
    assert win.navigate("Home")
    it = next(
        i for i in (win.nav.item(n) for n in range(win.nav.count())) if i.data(Qt.ItemDataRole.UserRole) == "Training"
    )
    win.statusBar().clearMessage()
    at = win.nav.viewport().mapTo(win, win.nav.visualItemRect(it).center())
    QTest.mouseClick(win.windowHandle(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    assert win.statusBar().currentMessage() == it.toolTip() == "Training needs the Engineer / Admin role"
    assert win.stack.currentWidget() is win.pages["Home"]


def test_req_usr_001_an_empty_state_names_what_the_role_may_not_do_and_follows_a_sign_in(
    qtbot: QtBot, ctx: AppContext
) -> None:
    """Logs & Export with no records: the Operator is told the exports and Delete Records… are the Admin's and Archive
    and Add to Training as OK the Engineer's; after Switch User to the Engineer, only the first; the Admin, neither.
    Inspection's and Compare's empty states say theirs the same way."""
    win = _window(qtbot, ctx)
    logs = cast(LogsPage, win.pages["Logs & Export"])
    admin = "Exports and Delete Records… need the Admin role."
    engineer = "Archive and Add to Training as OK need the Engineer or Admin role."
    win.set_user("operator")
    assert win.navigate("Logs & Export")
    listed(qtbot, logs)
    assert logs.empty.sentence.text() == f"Run boards on Inspection. {admin} {engineer}"
    for user, notes in (("engineer", admin), ("admin", "")):
        win.set_user(user)
        listed(qtbot, logs)
        said = logs.empty.sentence.text()
        assert said == f"Run boards on Inspection. {notes}".strip(), (user, said)
    win.set_user("operator")
    assert win.navigate("Inspection")
    inspection = cast(InspectionPage, win.pages["Inspection"])
    assert inspection.empty.sentence.text().endswith("Save Image… needs the Admin role.")
    assert win.navigate("Compare")
    compare = cast(ComparePage, win.pages["Compare"])
    said = compare.test_empty.sentence.text()
    assert said.endswith("Trying other thresholds and Save to Recipe need the Engineer or Admin role."), said
    win.set_user("engineer")  # the page shown follows the sign-in
    assert "need the" not in compare.test_empty.sentence.text()


def test_req_usr_001_every_empty_state_of_a_page_names_its_limits(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path
) -> None:
    """The no-board-model state names what the role may not do on the page too, and so do the empty states of the tabs
    that hold a greyed control: AI Model Test's History (Validation Report…) and Training's Datasets (Export
    Manifest…), for an Engineer. Training's samples and AI Model Test's run say theirs the same way."""
    win = MainWindow(AppContext(Settings(workspace=str(tmp_path / "empty"), device="cpu")))  # no board model
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.set_user("operator")
    assert win.navigate("Inspection")
    said = cast(InspectionPage, win.pages["Inspection"]).empty.sentence.text()
    assert said == "Ask an Engineer to create one. Save Image… needs the Admin role.", said
    win.close()
    win = _window(qtbot, ctx)
    win.set_user("engineer")
    test = cast(ModelTestPage, win.pages["AI Model Test"])
    training = cast(TrainingPage, win.pages["Training"])
    assert win.navigate("AI Model Test")
    exports = "Exports and Validation Report… need the Admin role."
    assert test.empty.sentence.text().endswith(exports) and test.history_empty.sentence.text().endswith(exports)
    assert win.navigate("Training")
    listed(qtbot, training)
    manifest = "Remove and Export Manifest… need the Admin role."
    assert training.samples_empty.sentence.text().endswith(manifest)
    assert training.versions.empty.sentence.text().endswith(manifest)


def test_req_usr_001_each_role_note_names_one_role() -> None:
    """A page's note on its empty state names the role of the calls it covers, so each note's calls share one."""
    pages = [page for _, page in NAV]
    noted = [p for p in pages if p.role_notes]
    assert {p.__name__ for p in noted} == {"InspectionPage", "ComparePage", "TrainingPage", "ModelTestPage", "LogsPage"}
    for page in noted:
        for sentence, calls in page.role_notes:
            assert "{roles}" in sentence and len({REQUIRED_ROLE[c] for c in calls}) == 1, (page.__name__, sentence)


def test_req_usr_001_home_cards_name_the_role_of_each_step_and_where_the_pdf_reports_are(
    qtbot: QtBot, ctx: AppContext
) -> None:
    """Every role reads which role each step needs on Home's cards, and the Export card names AI Model Test as where
    the PDF reports are (Export Report, Validation Report…)."""
    win = _window(qtbot, ctx)
    home = cast(HomePage, win.pages["Home"])
    needs = ["Needs the Engineer or Admin role."] * 4 + ["Open to every role.", "Needs the Admin role."]
    for user in USERS.values():
        win.set_user(user)
        assert win.navigate("Home")
        assert [home.who[name].text() for _, name, *_ in HomePage.STEPS] == needs, user
        assert all(home.who[name].isVisible() for _, name, *_ in HomePage.STEPS)
    export = next(desc for _, name, desc, *_ in HomePage.STEPS if name == "Export")
    assert "PDF reports on AI Model Test (Export Report, Validation Report…)" in export


def test_req_usr_001_no_screen_hides_a_control_for_a_role() -> None:
    """A scan of aoi/ui: no control is shown or hidden by the role; it is greyed through `role_gate` instead. The
    lines left, each with its reason, hide no control a role may not use."""
    allowed = {
        "self._badges[title].setVisible(allowed)": "a badge, not a control: a greyed sidebar entry names its roles",
        "self.exit_presenter.setVisible(theme.presenter() and role in SettingsPage.roles)": "the presenter theme",
        "self.sheet.setVisible(engineer and self._asking)": "Save to Recipe's sheet, open once an Engineer pressed it",
    }
    found = []
    for path in sorted((ROOT / "aoi" / "ui").rglob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#")[0].strip()
            if re.search(r"\.(setVisible|setHidden)\(.*\b(role|admin|engineer|operator|allowed|may\w*)\b", code, re.I):
                if not any(code.startswith(a) for a in allowed):
                    found.append(f"{path.relative_to(ROOT)}:{n}: {code}")
    assert found == []
