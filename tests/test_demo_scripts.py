"""The Stage 1 demo kit (REQ-SET-007, REQ-SET-008, REQ-SET-009; S58; Customers & Launch, "Demos"): the 5-minute script
must never fail, so its clicks run here as a presenter makes them, in the presenter theme, on a 1920 x 1080 and on a
1366 x 768 projector, as do the 45-minute script's, on a 1920 x 1080 one, and the 15-minute script's; a demo closed
mid-run, by a crash or by the presenter, starts again as the kit's README says; and the scripts name only controls the
app has, in the glossary's words, with a Korean draft beside each. A8 of the 2026-10 business-readiness brief (F14) asks
that no script shows a dialog: these tests list every dialog shown (tests/dialog_watch.py), every question the script
answers itself and every file, folder and user it picks, and fail on any but the script's. The demo's boards are drawn:
these tests prove the path, never accuracy."""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QTabBar,
    QTableWidget,
    QWidget,
)
from pytestqt.qtbot import QtBot

from aoi.core.jobs import Job
from aoi.ui import errors as ui_errors
from aoi.ui import main_window, theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import Page
from aoi.ui.pages.inspection import InspectionPage
from tests.budgets import LONG_TRIES, judged
from tests.dialog_watch import watched
from tests.test_demo_ui import (  # noqa: F401 (an autouse fixture)
    VERDICTS,
    _windows_closed,
    click,
    records,
    shown_window,
    station,
)
from tests.test_explain import not_words
from tools.make_demo_bundle import BOARD_MODEL
from tools.render_screens import settle
from tools.screen_sizes import cut_off, whole
from tools.update_translations import TS_FILE

ROOT = Path(__file__).resolve().parents[1]
DEMO_DOCS = ROOT / "docs" / "demo"
RESTART_BUDGET_S = 30  # docs/demo/README.md, "When something goes wrong": the demo open again in under 30 s
RUN_TIMEOUT_S = 180  # a start of the demo in a process of its own, run 4 boards in, as tests/test_start_user.py waits
BOLD = re.compile(r"\*\*(.+?)\*\*")
SOURCE = re.compile(r"<source>(.*?)</source>", re.S)
NOT_YET_TESTED = "**Not yet tested on a locked validation set: nothing on this card is a measure of accuracy.**"


@pytest.fixture
def bundle(demo_bundle: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The demo bundle as the build ships it, where Load Demo Workspace looks for it."""
    monkeypatch.setenv("AOI_DEMO_BUNDLE", str(demo_bundle))
    return demo_bundle


def ui_strings() -> set[str]:
    """Every text the app shows, as the translation file holds it, without the symbols a button draws before its
    word (▶, ■), and every page's title."""
    sources = {re.sub(r"^[▶■]\s+", "", s.strip()) for s in SOURCE.findall(TS_FILE.read_text("utf-8"))}
    unescaped = {s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") for s in sources}
    return unescaped | {cls.title for cls in Page.__subclasses__() if getattr(cls, "title", "")}


def english_docs() -> list[Path]:
    return sorted(DEMO_DOCS.glob("*.md"))


def answered(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The questions the script answers itself (an export's, Reset Demo's), by title, each answered Yes as the script
    says, and none shown as a dialog."""
    asked: list[str] = []

    def question(_parent: QWidget, title: str, *_args: object) -> QMessageBox.StandardButton:
        asked.append(title)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", question)
    return asked


def picked(monkeypatch: pytest.MonkeyPatch, usb: Path) -> list[str]:
    """The files, folders and users the script picks itself, by the picker's title: each export's file and folder on
    the USB stick, as the script says, and Switch User's pick (QInputDialog.getItem, patched where the script
    switches), none shown as a dialog."""
    picks: list[str] = []

    def save(_parent: QWidget, title: str, *_args: object) -> tuple[str, str]:
        picks.append(title)
        return str(usb / "demo.csv"), ""

    def folder(_parent: QWidget, title: str, *_args: object) -> str:
        picks.append(title)
        return str(usb)

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", folder)
    return picks


def errors_recorded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every coded message the app would show, in place of its dialog."""
    shown: list[str] = []
    monkeypatch.setattr(ui_errors, "show_error", lambda _parent, report: shown.append(str(report)))
    monkeypatch.setattr(main_window, "show_error", lambda _parent, report: shown.append(str(report)))
    return shown


def projector(monkeypatch: pytest.MonkeyPatch, size: QSize) -> None:
    """Each window the demo opens (Load Demo, Reset Demo) shown at `size`, as maximized on a projector of that size,
    whose room the screen gives too, so a window is built in the presenter theme's sizes for it (`MainWindow._small`)
    and not styled again as it is shown. Offscreen, Qt's one screen is 800 x 800 px, where a maximized window is held
    at its least size."""

    def show(win: MainWindow) -> None:
        win.resize(size)
        win.showNormal()

    monkeypatch.setattr(MainWindow, "showMaximized", show)
    monkeypatch.setattr(QScreen, "availableGeometry", lambda _screen: QRect(QPoint(0, 0), size))


def in_view(win: MainWindow, widget: QWidget) -> bool:
    """`widget` scrolled into view where the page is longer than the window, then whole and enabled there: a control a
    presenter can point at or use."""
    QApplication.processEvents()  # the page laid out at the window's size first: a window just opened takes it late
    area = win.findChild(QScrollArea, "pages")
    if area is not None and area.isAncestorOf(widget):
        area.ensureWidgetVisible(widget, 0, 0)
        QApplication.processEvents()
    return whole(widget) and widget.isEnabled()


def press(qtbot: QtBot, win: MainWindow, widget: QWidget) -> None:
    """Click `widget` as a presenter does, once it is in view (`in_view`); a control a presenter could not see or use
    fails here, not in a demo."""
    assert in_view(win, widget), widget
    spot = widget.rect().center()
    if isinstance(widget, QCheckBox):  # on its box and words: a tick wider than them takes no click past them
        option = QStyleOptionButton()
        widget.initStyleOption(option)
        spot = widget.style().subElementRect(QStyle.SubElement.SE_CheckBoxClickRect, option, widget).center()
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton, pos=spot)


def opened(qtbot: QtBot, win: MainWindow, widget: QWidget) -> MainWindow:
    """Press `widget` (`press`), which opens another window (Load Demo Workspace, Reset Demo), and return that one."""
    press(qtbot, win, widget)
    made = shown_window()
    qtbot.waitExposed(made)
    return made


def typed(qtbot: QtBot, win: MainWindow, field: QSpinBox, text: str) -> None:
    """Type `text` into `field` over what it holds, once it is in view (`in_view`), as a presenter does."""
    assert in_view(win, field), field
    field.setFocus(Qt.FocusReason.MouseFocusReason)
    field.selectAll()
    qtbot.keyClicks(field, text)
    assert field.text() == text, field.text()


def named(root: QWidget, text: str) -> QPushButton:
    """The one shown button under `root` that reads `text`."""
    (found,) = [b for b in root.findChildren(QPushButton) if b.text() == text and b.isVisible()]
    return found


def sidebar(qtbot: QtBot, win: MainWindow, title: str) -> None:
    """Click `title` in the sidebar, where it shows."""
    rect = win.nav.visualItemRect(win._items[title])
    assert not win._items[title].isHidden() and win.nav.viewport().rect().contains(rect), title
    qtbot.mouseClick(win.nav.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QApplication.processEvents()  # the page laid out, as it is by the presenter's next click: Settings, opened in the
    # window Reset Demo made, first took the height the page before had, Reset Demo then 4 px past the fold
    assert win.stack.currentWidget() is win.pages[title], title


def click_tab(qtbot: QtBot, bar: QTabBar, text: str) -> None:
    """Click the tab that reads `text`."""
    (i,) = [i for i in range(bar.count()) if bar.tabText(i) == text]
    assert whole(bar), text
    qtbot.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(i).center())
    assert bar.currentIndex() == i, text


def click_row(qtbot: QtBot, table: QTableWidget, row: int) -> None:
    """Click row `row` of `table`, on its first cell."""
    item = table.item(row, 0)
    assert item is not None
    table.scrollToItem(item)
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualItemRect(item).center())
    assert table.currentRow() == row


def test_req_set_007_the_demo_kit_names_real_controls_in_glossary_words_with_a_korean_draft() -> None:
    """In the kit's English files bold marks a control or page by its name in the app, and nothing else; the text
    uses the Charter's terms ("Windows", the system's name, aside); each picture it shows exists; each file has its
    Korean draft in ko/ (Customers & Launch, "Both languages")."""
    docs = english_docs()
    assert {d.name for d in docs} >= {"README.md", "stage1-5min.md", "stage1-15min.md", "stage1-45min.md"}
    names, problems = ui_strings(), []
    for doc in docs:
        text = doc.read_text("utf-8")
        problems += [f"{doc.name}: **{b}** is no control or page" for b in BOLD.findall(text) if b not in names]
        prose = re.sub(r"`[^`]*`|\]\([^)]*\)|\bWindows\b", " ", text)  # code, link targets, the OS's name
        problems += [f"{doc.name}: the word {w!r}" for w in not_words(prose)]
        for image in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
            if not (doc.parent / image).is_file():
                problems.append(f"{doc.name}: no picture {image}")
        if not (DEMO_DOCS / "ko" / doc.name).is_file():
            problems.append(f"{doc.name}: no Korean draft ko/{doc.name}")
    assert problems == []


@pytest.mark.parametrize("size", [QSize(1920, 1080), QSize(1366, 768)], ids=["1920x1080", "1366x768"])
def test_req_set_007_the_five_minute_script_runs_in_the_presenter_theme(
    qtbot: QtBot,
    bundle: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
    size: QSize,
) -> None:
    """docs/demo/stage1-5min.md as clicks, each on a control shown whole and enabled: load the demo, switch the
    presenter theme on, Inspection in the sidebar, Start, the pause at the NG board, Compare with Golden board ›,
    Inspection and Start again to the end, Logs & Export with the NG row selected and both exports, then Reset Demo in
    the presenter theme, which stays on, at Home, in under 10 s, three resets judged by tests/budgets.py; the run inside
    its five minutes at the default pace of 3 s. On a 1920 x 1080 and on a 1366 x 768 projector (A8 of the 2026-10
    business-readiness brief, F14), each window the demo opens filling it, where the verdict area is whole with nothing
    scrolled at the pause, on Compare and on Logs & Export (tools/screen_sizes.py). No dialog on the way, no message, no
    question but the ones the script answers (each export's and Reset Demo's) and nothing picked but each export's file
    and folder."""
    shown = errors_recorded(monkeypatch)
    asked = answered(monkeypatch)
    usb = tmp_path / "usb"
    usb.mkdir()
    picks = picked(monkeypatch, usb)
    projector(monkeypatch, size)
    with watched() as other:
        first = station(qtbot)
        win = opened(qtbot, first, first.pages["Settings"].demo.btn_load)  # type: ignore[attr-defined]
        qtbot.waitUntil(lambda: win.size() == size)
        assert win.in_demo and win.ctx.settings.demo_pace_s == 3  # 10 boards at 3 s: about 30 s of the five minutes
        settings: Any = win.pages["Settings"]
        settings.demo.pace.setValue(1)  # the test's own pace
        press(qtbot, win, settings.presenter)
        assert win.stack.currentWidget() is settings and not win._items["Settings"].isHidden()
        assert win.exit_presenter.isVisible() and not settings.hardware.isVisible()

        sidebar(qtbot, win, "Inspection")
        page = win.pages["Inspection"]
        assert isinstance(page, InspectionPage) and len(page.queue) == 10
        press(qtbot, win, page.btn_start)
        qtbot.waitUntil(lambda: not page.running and page.worker is None, timeout=60000)
        assert page.last is not None and page.last.verdict == "NG" and "board_04.png" in page.summary.text()
        settle()  # as the presenter sees it: laid out, a line of the board's summary added at the pause
        assert cut_off(win, "Inspection") == []
        press(qtbot, win, page.btn_compare)
        compare: Any = win.pages["Compare"]
        assert win.stack.currentWidget() is compare
        qtbot.waitUntil(lambda: "NG" in compare.verdict.text() and bool(compare.test_view.box_rects()), timeout=60000)
        settle()
        assert cut_off(win, "Compare") == []
        sidebar(qtbot, win, "Inspection")
        press(qtbot, win, page.btn_start)
        qtbot.waitUntil(lambda: not page.running and page.worker is None and page.queue_pos == 9, timeout=60000)
        assert records(win) == VERDICTS

        sidebar(qtbot, win, "Logs & Export")
        logs: Any = win.pages["Logs & Export"]
        qtbot.waitUntil(lambda: len(logs.rows) == 10 and logs.listing is None, timeout=10000)
        click_row(qtbot, logs.table, next(i for i, r in enumerate(logs.rows) if r["result"] == "NG"))
        settle()
        assert cut_off(win, "Logs & Export") == []
        press(qtbot, win, logs.btn_csv)
        qtbot.waitUntil(lambda: (usb / "demo_checks.csv").is_file() and logs._bg is None, timeout=30000)
        with (usb / "demo.csv").open(encoding="utf-8-sig", newline="") as f:
            assert sorted(r["result"] for r in csv.DictReader(f)) == sorted(VERDICTS)
        press(qtbot, win, logs.btn_img)
        qtbot.waitUntil(lambda: len(list(usb.glob("*.png"))) == 10 and logs._bg is None, timeout=30000)

        resets: list[float] = []
        for _ in range(LONG_TRIES):  # judged by tests/budgets.py; the first puts back the run just played, the next
            # two the bundle as loaded (tests/test_demo.py plays the boards before each of its resets)
            sidebar(qtbot, win, "Settings")
            reset = win.pages["Settings"].demo.btn_reset  # type: ignore[attr-defined]
            assert whole(reset) and reset.isEnabled()
            started = time.monotonic()
            win = click(qtbot, reset)
            resets.append(time.monotonic() - started)
            qtbot.waitUntil(lambda made=win: made.size() == size)
            assert win.in_demo and records(win) == [] and win.stack.currentWidget() is win.pages["Home"]
            assert theme.presenter() and win.exit_presenter.isVisible()  # at Home: never left on Settings
    print("\nREQ-SET-007 Reset Demo, s:", [round(s, 2) for s in resets])
    assert judged(resets) < 10, resets
    assert (shown, dialogs, other) == ([], [], [])
    assert asked == ["Confirm export", "Confirm export", *["Reset Demo"] * LONG_TRIES], asked
    assert picks == ["Export CSV", "Export overlays to"], picks


def test_req_set_008_in_the_presenter_theme_an_admin_resets_the_demo_or_leaves_the_theme_in_three_clicks(
    qtbot: QtBot, bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A4 of the 2026-10 business-readiness brief (D7, F10). In the presenter theme, in a 1366 x 768 window, the
    smallest the demo kit names (docs/demo/README.md, #104), an Admin reaches Reset Demo from every page the sidebar
    shows in three clicks, each where a presenter makes it with nothing scrolled: Settings in the sidebar, Reset Demo,
    then Yes to its question. From a run paused at its NG board, with work still running (a stand-in job that stops
    when asked, as a board's inspection or an export does), Yes to that one question stops the work and the demo comes
    back in the presenter theme, at Home, with no records; so does work that starts while the question is open (a
    scripted run's next board), with no second question. Exit presenter theme is one click, in the header of every
    page. Settings shows no hardware table there (its Stage 2 to 4 rows read "Not connected"); an Operator has no
    Settings in the sidebar and cannot open it. No message on the way."""
    shown: list[str] = []
    monkeypatch.setattr(ui_errors, "show_error", lambda _parent, report: shown.append(str(report)))
    monkeypatch.setattr(main_window, "show_error", lambda _parent, report: shown.append(str(report)))
    answers: list[QMessageBox.StandardButton] = []  # the third click, on the question's button
    asked: list[str] = []
    meanwhile: list[Callable[[], object]] = []  # what starts while the question is open

    def question(_parent: QWidget, title: str, *_args: object) -> QMessageBox.StandardButton:
        asked.append(title)
        while meanwhile:
            meanwhile.pop(0)()
        # One the test did not plan, as on closing the window after a failed step with work still running: Yes stops
        # the work, so the window closes and no job outlives the test (the steps check `asked` for extra questions).
        return answers.pop(0) if answers else QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", question)
    win = click(qtbot, station(qtbot).pages["Settings"].demo.btn_load)  # type: ignore[attr-defined]
    win.pages["Settings"].demo.pace.setValue(1)  # type: ignore[attr-defined]  # the test's own pace
    win.pages["Settings"].presenter.click()  # type: ignore[attr-defined]

    def smallest(win: MainWindow) -> None:
        win.showNormal()  # it opens maximized, and maximized it went back to the test screen's 1461 x 796 mid-run
        win.resize(1366, 768)
        qtbot.waitUntil(lambda: win.size() == QSize(1366, 768))

    smallest(win)
    settings = win.pages["Settings"]
    reset = settings.demo.btn_reset  # type: ignore[attr-defined]
    titles = [title for title, item in win._items.items() if not item.isHidden()]
    assert "Settings" in titles and "3D Profile" not in titles and not win.navigate("3D Profile")
    for title in titles:
        assert win.navigate(title)
        assert whole(win.exit_presenter), title
        sidebar(qtbot, win, "Settings")  # 1
        assert win.stack.currentWidget() is settings and whole(reset) and reset.isEnabled(), title
        assert not settings.hardware.isVisible(), title  # type: ignore[attr-defined]
        answers.append(QMessageBox.StandardButton.No)
        qtbot.mouseClick(reset, Qt.MouseButton.LeftButton)  # 2, and its question: 3
        assert asked.pop() == "Reset Demo" and theme.presenter() and win.isVisible(), title

    assert win.navigate("Inspection")
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage)
    qtbot.mouseClick(page.btn_start, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not page.running and page.worker is None, timeout=60000)
    assert page.last is not None and page.last.verdict == "NG" and records(win) == VERDICTS[:4]

    def held(progress: Callable[..., None], should_stop: Callable[[], bool]) -> None:
        while not should_stop():
            time.sleep(0.01)

    work = win.ctx.jobs.submit(Job("held", held, with_progress=True))
    sidebar(qtbot, win, "Settings")  # 1
    answers.append(QMessageBox.StandardButton.Yes)
    win = click(qtbot, reset)  # 2, and Yes: 3, the one question
    assert asked == ["Reset Demo"] and answers == [] and work.done
    assert win.in_demo and records(win) == [] and win.stack.currentWidget() is win.pages["Home"]
    assert theme.presenter() and win.ctx.settings.presenter_theme and not win._items["Settings"].isHidden()
    assert not win.pages["Settings"].hardware.isVisible()  # type: ignore[attr-defined]
    smallest(win)
    assert whole(win.exit_presenter)

    asked.clear()
    assert win.ctx.jobs.idle()
    jobs = win.ctx.jobs
    later: list[Job[None]] = []
    meanwhile.append(lambda: later.append(jobs.submit(Job("held", held, with_progress=True))))
    sidebar(qtbot, win, "Settings")  # 1
    reset = win.pages["Settings"].demo.btn_reset  # type: ignore[attr-defined]
    assert whole(reset)
    answers.append(QMessageBox.StandardButton.Yes)
    win = click(qtbot, reset)  # 2, and Yes: 3, though work started while it was asked
    assert asked == ["Reset Demo"] and answers == [] and len(later) == 1 and later[0].done
    assert win.in_demo and records(win) == [] and win.stack.currentWidget() is win.pages["Home"]

    win.set_user("operator")
    assert win.stack.currentWidget() is win.pages["Home"] and win._items["Settings"].isHidden()
    assert not win.navigate("Settings") and not win.exit_presenter.isVisible()
    win.set_user("admin")
    qtbot.mouseClick(win.exit_presenter, Qt.MouseButton.LeftButton)  # 1
    assert not theme.presenter() and not win.ctx.settings.presenter_theme and win.navigate("Settings")
    assert win.pages["Settings"].hardware.isVisible()  # type: ignore[attr-defined]
    assert shown == []


def test_req_set_007_the_fifteen_minute_script_checks_trains_and_tries_a_threshold(
    qtbot: QtBot, bundle: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """docs/demo/stage1-15min.md as clicks, in the presenter theme: AI Model Test runs on the demo version's locked
    validation set, the 50 OK and 11 NG boards its AI model never trained on, and gives counts; Start Training makes
    v1.1, whose AI Model Card says it is not yet tested and which judges nothing until Activate Selected, and Roll Back
    makes v1.0 active again; the NG record opened in Compare from Logs & Export, Allowed difference regions 2 and
    Re-evaluate still give NG, as the AI score check decides on its own, and the recipe is unchanged. Every page shown
    fits a 1920 px wide screen. The training run here is short; the script's run at the page's defaults is timed by hand
    (about 98 s on a 4-core PC). No dialog on the way, no message and no question (A8 of the 2026-10
    business-readiness brief, F14)."""
    shown = errors_recorded(monkeypatch)
    asked = answered(monkeypatch)
    with watched() as other:
        win = click(qtbot, station(qtbot).pages["Settings"].demo.btn_load)  # type: ignore[attr-defined]
        bm = BOARD_MODEL
        revision = win.ctx.recipe(bm)
        win.pages["Settings"].demo.pace.setValue(1)  # type: ignore[attr-defined]  # the test's own pace
        win.pages["Settings"].presenter.click()  # type: ignore[attr-defined]
        widths = {}
        assert win.navigate("Inspection")
        page = win.pages["Inspection"]
        assert isinstance(page, InspectionPage)
        for _ in range(2):  # to the NG board, then to the end of the queue
            qtbot.mouseClick(page.btn_start, Qt.MouseButton.LeftButton)
            qtbot.waitUntil(lambda: not page.running and page.worker is None, timeout=60000)
        assert records(win) == VERDICTS

        assert win.navigate("AI Model Test")
        test = win.pages["AI Model Test"]
        assert test.source.currentData() and "61 images" in test.source.currentText()  # type: ignore[attr-defined]
        qtbot.mouseClick(test.btn_run, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
        qtbot.waitUntil(lambda: test.btn_run.isEnabled(), timeout=60000)  # type: ignore[attr-defined]
        tiles = {k: re.sub(r"<[^>]+>", " ", t.text()) for k, t in test.tiles.items()}  # type: ignore[attr-defined]
        assert " of 11" in tiles["missed_defects"] and " of 50" in tiles["false_calls"]
        widths["AI Model Test"] = win.minimumSizeHint().width()

        assert win.navigate("Training")
        training = win.pages["Training"]
        training.epochs.setValue(2)  # type: ignore[attr-defined]
        training.input_size.setCurrentText("128")  # type: ignore[attr-defined]
        qtbot.mouseClick(training.btn_train, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
        qtbot.waitUntil(lambda: training.worker is None and win.ctx.training.done, timeout=120000)  # type: ignore
        versions = training.models  # type: ignore[attr-defined]
        assert [versions.item(r, 1).text() for r in range(versions.rowCount())] == ["v1.1", "v1.0"]
        assert (win.ctx.active_model(bm) or {}).get("version") == "v1.0"  # trained, not yet judging
        versions.selectRow(0)
        card = next(b for b in training.findChildren(QPushButton) if b.text() == "AI Model Card")
        qtbot.mouseClick(card, Qt.MouseButton.LeftButton)  # the script reads out its first line: no result claimed yet
        shown_card = training.card_view.toPlainText()  # type: ignore[attr-defined]
        assert shown_card.startswith(f"# Model card: {bm} v1.1")
        assert NOT_YET_TESTED in shown_card
        activate = next(b for b in training.findChildren(QPushButton) if b.text() == "Activate Selected")
        qtbot.mouseClick(activate, Qt.MouseButton.LeftButton)
        assert (win.ctx.active_model(bm) or {}).get("version") == "v1.1"
        qtbot.mouseClick(training.btn_rollback, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
        assert (win.ctx.active_model(bm) or {}).get("version") == "v1.0"
        widths["Training"] = win.minimumSizeHint().width()

        assert win.navigate("Logs & Export")
        logs = win.pages["Logs & Export"]
        qtbot.waitUntil(lambda: len(logs.rows) == 10, timeout=10000)  # type: ignore[attr-defined]
        logs.table.selectRow(next(i for i, r in enumerate(logs.rows) if r["result"] == "NG"))  # type: ignore[attr-defined]
        qtbot.mouseClick(logs.btn_compare, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
        compare = win.pages["Compare"]
        assert win.stack.currentWidget() is compare
        qtbot.waitUntil(lambda: "NG" in compare.verdict.text(), timeout=60000)  # type: ignore[attr-defined]
        compare.max_regions.setValue(2)  # type: ignore[attr-defined]
        qtbot.waitUntil(lambda: compare.btn_try.isEnabled(), timeout=10000)  # type: ignore[attr-defined]
        qtbot.mouseClick(compare.btn_try, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
        qtbot.waitUntil(lambda: "Would be" in compare.would_be.text(), timeout=60000)  # type: ignore[attr-defined]
        assert "NG" in compare.would_be.text() and win.ctx.recipe(bm) == revision  # type: ignore[attr-defined]
        widths["Compare"] = win.minimumSizeHint().width()
        assert max(widths.values()) <= 1920, widths
    assert (shown, dialogs, other, asked) == ([], [], [], [])


def test_req_set_007_the_forty_five_minute_script_clicked_through(
    qtbot: QtBot, bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """docs/demo/stage1-45min.md as clicks, in the presenter theme on a 1920 x 1080 projector, each on a control shown
    whole and enabled (A8 of the 2026-10 business-readiness brief, F14). 0:00 to 12:30, the 15-minute script up to the
    report: the run to its NG board and on to the end, Run Test on the locked boards and a red row selected, its picture
    shown, a short training run that makes v1.1 while v1.0 still judges (its AI Model Card, not yet tested, Activate
    Selected, Roll Back), and the NG record opened in Compare from Logs & Export, its reasons shown, 2 typed into
    Allowed difference regions, Re-evaluate still NG, and Save to Recipe in view, not pressed. Recipes: the Recipe
    Editor's Thresholds tab with Learn From Labelled Boards… in view and not pressed, then ROIs, AOI checks and
    Revisions with the revisions listed. AI model versions: v1.0 active, v1.1's row, AI Model Card, Activate Selected,
    Run Test again and both runs on History, a run selected, then Roll Back. Their data: Training's Datasets tab with
    the frozen versions, Include archived ticked and Filter on Logs & Export, and the settings as the script shows them
    when asked: Exit presenter theme, Settings with its dataset stores, Presenter theme on again. Who may do what:
    Switch User to the Operator, whose Training, AI Model Test and Recipe Editor are greyed and who sees no Exit
    presenter theme, Inspection, and back to the Admin. The report: the NG row selected and both exports. After they
    leave, Reset Demo in the presenter theme opens at Home without v1.1, the runs and the records, and the recipe is as
    before. No dialog on the way, no message, no question but the ones the script answers (each export's and Reset
    Demo's) and nothing picked but what the script picks (each export's file and folder, and the user, twice)."""
    shown = errors_recorded(monkeypatch)
    asked = answered(monkeypatch)
    usb = tmp_path / "usb"
    usb.mkdir()
    picks = picked(monkeypatch, usb)
    projector(monkeypatch, QSize(1920, 1080))
    with watched() as other:
        first = station(qtbot)
        win = opened(qtbot, first, first.pages["Settings"].demo.btn_load)  # type: ignore[attr-defined]
        qtbot.waitUntil(lambda: win.size() == QSize(1920, 1080))
        bm = BOARD_MODEL
        revision = win.ctx.recipe(bm)
        settings: Any = win.pages["Settings"]
        settings.demo.pace.setValue(1)  # the test's own pace
        press(qtbot, win, settings.presenter)

        # 0:00 to 12:30, the 15-minute script up to the report
        sidebar(qtbot, win, "Inspection")
        page = win.pages["Inspection"]
        assert isinstance(page, InspectionPage)
        press(qtbot, win, page.btn_start)  # to the NG board
        qtbot.waitUntil(lambda: not page.running and page.worker is None, timeout=60000)
        press(qtbot, win, page.btn_compare)
        compare: Any = win.pages["Compare"]
        qtbot.waitUntil(lambda: "NG" in compare.verdict.text(), timeout=60000)
        sidebar(qtbot, win, "Inspection")
        press(qtbot, win, page.btn_start)  # to the end of the queue
        qtbot.waitUntil(lambda: not page.running and page.worker is None and page.queue_pos == 9, timeout=60000)
        assert records(win) == VERDICTS
        sidebar(qtbot, win, "AI Model Test")
        test: Any = win.pages["AI Model Test"]
        press(qtbot, win, test.btn_run)
        qtbot.waitUntil(lambda: test.btn_run.isEnabled(), timeout=60000)
        tiles = {k: re.sub(r"<[^>]+>", " ", t.text()) for k, t in test.tiles.items()}
        assert " of 11" in tiles["missed_defects"] and " of 50" in tiles["false_calls"]
        red = {r["image"] for r in test.rows if r["pass_fail"] == "FAIL"}  # a board the AI model called wrong
        click_row(
            qtbot, test.table, next(i for i in range(test.table.rowCount()) if test.table.item(i, 0).toolTip() in red)
        )
        qtbot.waitUntil(lambda: test.preview_verdict.text() != "—", timeout=30000)  # its picture beside the table
        sidebar(qtbot, win, "Training")
        training: Any = win.pages["Training"]
        training.epochs.setValue(2)  # a short run: the script's 60 epochs at 256 px are timed by hand
        training.input_size.setCurrentText("128")
        press(qtbot, win, training.btn_train)
        qtbot.waitUntil(lambda: training.worker is None and win.ctx.training.done, timeout=120000)
        versions = training.models
        assert [versions.item(r, 1).text() for r in range(versions.rowCount())] == ["v1.1", "v1.0"]
        assert (win.ctx.active_model(bm) or {}).get("version") == "v1.0"  # trained, not yet judging
        click_row(qtbot, versions, 0)
        press(qtbot, win, named(training, "AI Model Card"))
        assert NOT_YET_TESTED in training.card_view.toPlainText()  # the line the script reads out
        press(qtbot, win, named(training, "Activate Selected"))
        assert (win.ctx.active_model(bm) or {}).get("version") == "v1.1"
        press(qtbot, win, training.btn_rollback)
        assert (win.ctx.active_model(bm) or {}).get("version") == "v1.0"
        sidebar(qtbot, win, "Logs & Export")
        logs: Any = win.pages["Logs & Export"]
        qtbot.waitUntil(lambda: len(logs.rows) == 10 and logs.listing is None, timeout=10000)
        click_row(qtbot, logs.table, next(i for i, r in enumerate(logs.rows) if r["result"] == "NG"))
        press(qtbot, win, logs.btn_compare)
        assert win.stack.currentWidget() is compare
        qtbot.waitUntil(lambda: "NG" in compare.verdict.text(), timeout=60000)
        assert compare.why.isVisible()  # "Why this board is NG:"
        typed(qtbot, win, compare.max_regions, "2")  # Allowed difference regions
        qtbot.waitUntil(lambda: compare.btn_try.isEnabled(), timeout=10000)
        press(qtbot, win, compare.btn_try)
        qtbot.waitUntil(lambda: "Would be" in compare.would_be.text(), timeout=60000)
        assert "NG" in compare.would_be.text() and win.ctx.recipe(bm) == revision
        assert in_view(win, compare.btn_save)  # pointed at, not pressed

        # 12:30 to 20:00, recipes
        sidebar(qtbot, win, "Recipe Editor")
        recipe: Any = win.pages["Recipe Editor"]
        bar = recipe.tabs.tabBar()
        assert [bar.tabText(i) for i in range(bar.count())] == ["ROIs", "Thresholds", "AOI checks", "Revisions"]
        click_tab(qtbot, bar, "Thresholds")
        learn = named(recipe, "Learn From Labelled Boards…")
        assert whole(learn) and learn.isEnabled()  # pointed at, not pressed
        for name in ("ROIs", "AOI checks", "Revisions"):
            click_tab(qtbot, bar, name)
        assert recipe.history.isVisible() and recipe.history.rowCount() >= 1

        # 20:00 to 28:00, AI model versions
        sidebar(qtbot, win, "Training")
        assert [versions.item(r, 1).text() for r in range(versions.rowCount())] == ["v1.1", "v1.0"]
        assert (win.ctx.active_model(bm) or {}).get("version") == "v1.0"
        click_row(qtbot, versions, 0)
        press(qtbot, win, named(training, "AI Model Card"))
        assert training.card_view.toPlainText().startswith(f"# Model card: {bm} v1.1")
        press(qtbot, win, named(training, "Activate Selected"))
        assert (win.ctx.active_model(bm) or {}).get("version") == "v1.1"
        sidebar(qtbot, win, "AI Model Test")
        press(qtbot, win, test.btn_run)
        qtbot.waitUntil(lambda: test.btn_run.isEnabled(), timeout=60000)
        click_tab(qtbot, test.tabs.tabBar(), "History")  # both runs, newest first
        qtbot.waitUntil(lambda: test.history.rowCount() == 2, timeout=10000)
        click_row(qtbot, test.history, 0)
        sidebar(qtbot, win, "Training")
        assert training.btn_rollback.text() == "Roll Back to v1.0"
        press(qtbot, win, training.btn_rollback)
        assert (win.ctx.active_model(bm) or {}).get("version") == "v1.0"

        # 28:00 to 36:00, their data
        click_tab(qtbot, training.tabs, "Datasets")  # the frozen dataset versions
        assert training.versions.table.isVisible() and training.versions.table.rowCount() >= 1
        sidebar(qtbot, win, "Logs & Export")
        press(qtbot, win, logs.archived)
        assert logs.archived.isChecked()
        press(qtbot, win, named(logs, "Filter"))
        qtbot.waitUntil(lambda: logs.listing is None and len(logs.rows) == 10, timeout=10000)
        press(qtbot, win, win.exit_presenter)  # the settings, if they ask to see them
        assert not theme.presenter()
        sidebar(qtbot, win, "Settings")
        assert settings.stores.isVisible() and settings.hardware.isVisible()
        press(qtbot, win, settings.presenter)
        assert theme.presenter() and not settings.hardware.isVisible()

        # 36:00 to 40:00, who may do what
        def switch(title: str, pick: str) -> tuple[str, bool]:
            picks.append(title)
            return pick, True

        for pick in ("operator (Operator)", "admin (Admin)"):
            monkeypatch.setattr(
                QInputDialog, "getItem", staticmethod(lambda _p, title, *_a, pick=pick: switch(title, pick))
            )
            press(qtbot, win, named(win, "Switch User"))
            operator = pick.startswith("operator")
            assert win.ctx.role == ("Operator" if operator else "Admin")
            greyed = [t for t in ("Training", "AI Model Test", "Recipe Editor") if not win._items[t].flags()]
            assert greyed == (["Training", "AI Model Test", "Recipe Editor"] if operator else [])
            assert win.exit_presenter.isVisible() is not operator
            if operator:
                sidebar(qtbot, win, "Inspection")

        # 40:00 to 43:00, the report they keep
        sidebar(qtbot, win, "Logs & Export")
        click_row(qtbot, logs.table, next(i for i, r in enumerate(logs.rows) if r["result"] == "NG"))
        press(qtbot, win, logs.btn_csv)
        qtbot.waitUntil(lambda: (usb / "demo_checks.csv").is_file() and logs._bg is None, timeout=30000)
        press(qtbot, win, logs.btn_img)
        qtbot.waitUntil(lambda: len(list(usb.glob("*.png"))) == 10 and logs._bg is None, timeout=30000)

        # After they leave
        sidebar(qtbot, win, "Settings")
        win = opened(qtbot, win, settings.demo.btn_reset)
        assert theme.presenter() and win.exit_presenter.isVisible() and win.stack.currentWidget() is win.pages["Home"]
        assert [m["version"] for m in win.ctx.models(bm)] == ["v1.0"]
        assert win.ctx.test_runs(bm) == [] and records(win) == []
        assert win.ctx.recipe(bm) == revision
    assert (shown, dialogs, other) == ([], [], [])
    assert asked == ["Confirm export", "Confirm export", "Reset Demo"], asked
    assert picks == ["Switch user", "Switch user", "Export CSV", "Export overlays to"], picks


def run_demo(env: dict[str, str], then: str = "") -> list[dict[str, Any]]:
    """`main.py --demo` in a process of its own (tests/startup_worker.py), going on as AOI_STARTUP_THEN says: every line
    of JSON it printed, the start's first, then what `then` ended on, and last, unless it crashed, the line main.main()
    returned on, with every dialog shown on the way out. Each line must list no dialog."""
    launched = {"AOI_STARTUP_LAUNCHED": repr(time.time())} | ({"AOI_STARTUP_THEN": then} if then else {})
    cmd = [sys.executable, "-m", "tests.startup_worker", "--demo"]
    done = subprocess.run(cmd, cwd=ROOT, env=env | launched, capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    assert done.returncode == (3 if then == "crash" else 0), done.stderr  # os._exit(3): the crash
    lines = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    assert lines and all(line["dialogs"] == [] for line in lines), (lines, done.stderr)
    assert then == "crash" or lines[-1].get("exit") == 0, lines  # main.main() returned, the window closed
    return lines


@pytest.mark.parametrize("then", ["crash", "close"])
def test_req_set_007_a_demo_closed_mid_run_opens_again_as_the_demo_kit_says(
    demo_bundle: Path, tmp_path: Path, then: str
) -> None:
    """docs/demo/README.md, "When something goes wrong", "The app closes by itself" (A8 of the 2026-10
    business-readiness brief, F14): the demo started with `main.py --demo` (the Start menu's Demo entry), in the
    production theme, as the demo is loaded; the presenter theme switched on, Inspection, Start; then the app ends
    mid-run, by a crash while a board after the first is inspected (the process ended, nothing saved on the way out),
    or closed by the presenter while the run waits at its NG board, 4 of its 10 boards done (closed while a board is
    inspected, the app asks whether to stop the work first, #171). Started again the same way, it opens the demo
    workspace signed in as admin, in the presenter theme it was left in, on the page it showed after the crash and at
    Home after the close, usable within the README's 30 s of the process starting. Each start in a process of its own
    through main.main(); no dialog in either, closing included."""
    folder = tmp_path / "AOI_Workspace"
    folder.mkdir()
    env = {**os.environ, "AOI_WORKSPACE": str(folder), "AOI_DEMO_BUNDLE": str(demo_bundle), "AOI_MEMORY_KEYS": "1"}
    started, ended, *_ = run_demo(env, then)
    assert started["demo"] and started["presenter"] is False, started  # the theme the presenter then switches on
    assert ended["then"] == then and ended["page"] == "Inspection" and ended["records"] >= 1, ended
    assert ended["inspecting"] if then == "crash" else ended["records"] == 4, ended  # mid-board; or at the NG board
    again = run_demo(env)[-1]
    print(f"\nREQ-SET-007 the demo started again after a {then}, s:", round(again["usable"], 2))
    assert again["exposed"] and again["demo"], again
    assert (again["user"], again["role"], again["presenter"]) == ("admin", "Admin", True), again
    assert again["page"] == ("Inspection" if then == "crash" else "Home"), again
    assert again["usable"] < RESTART_BUDGET_S, again
