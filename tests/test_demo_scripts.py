"""The Stage 1 demo kit (REQ-SET-007, REQ-SET-008, REQ-SET-009; S58; Customers & Launch, "Demos"): the 5-minute script
must never fail, so its clicks run here as a presenter makes them, in the presenter theme; and the scripts name only
controls the app has, in the glossary's words, with a Korean draft beside each. The demo's boards are drawn: these
tests prove the path, never accuracy."""

from __future__ import annotations

import csv
import re
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton
from pytestqt.qtbot import QtBot

from aoi.ui import errors as ui_errors
from aoi.ui import main_window
from aoi.ui.pages.base import Page
from aoi.ui.pages.inspection import InspectionPage
from tests.budgets import LONG_TRIES, judged
from tests.test_demo_ui import VERDICTS, _windows_closed, click, records, station  # noqa: F401 (an autouse fixture)
from tests.test_explain import not_words
from tools.make_demo_bundle import BOARD_MODEL
from tools.update_translations import TS_FILE

DEMO_DOCS = Path(__file__).resolve().parents[1] / "docs" / "demo"
BOLD = re.compile(r"\*\*(.+?)\*\*")
SOURCE = re.compile(r"<source>(.*?)</source>", re.S)


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


def test_req_set_007_the_five_minute_script_runs_in_the_presenter_theme(
    qtbot: QtBot, bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/demo/stage1-5min.md as clicks: load the demo, switch the presenter theme on, Start, the pause at the NG
    board, Compare, Start again to the end, Logs & Export with both exports, then Exit presenter theme and Reset Demo
    in under 10 s, three resets judged by tests/budgets.py; no message on the way, and the run inside its five
    minutes at the default pace of 3 s."""
    shown: list[str] = []
    monkeypatch.setattr(ui_errors, "show_error", lambda _parent, report: shown.append(str(report)))
    monkeypatch.setattr(main_window, "show_error", lambda _parent, report: shown.append(str(report)))
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    win = click(qtbot, station(qtbot).pages["Settings"].demo.btn_load)  # type: ignore[attr-defined]
    assert win.in_demo and win.ctx.settings.demo_pace_s == 3  # 10 boards at 3 s: about 30 s of the five minutes
    win.pages["Settings"].demo.pace.setValue(1)  # type: ignore[attr-defined]  # the test's own pace
    win.pages["Settings"].presenter.click()  # type: ignore[attr-defined]
    assert win.stack.currentWidget() is win.pages["Home"] and not win.navigate("Settings")
    assert win.exit_presenter.isVisible()

    assert win.navigate("Inspection")
    page = win.pages["Inspection"]
    assert isinstance(page, InspectionPage) and len(page.queue) == 10
    qtbot.mouseClick(page.btn_start, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not page.running and page.worker is None, timeout=60000)
    assert page.last is not None and page.last.verdict == "NG" and "board_04.png" in page.summary.text()
    qtbot.mouseClick(page.btn_compare, Qt.MouseButton.LeftButton)
    compare = win.pages["Compare"]
    assert win.stack.currentWidget() is compare
    qtbot.waitUntil(lambda: "NG" in compare.verdict.text(), timeout=60000)  # type: ignore[attr-defined]
    assert win.navigate("Inspection")
    qtbot.mouseClick(page.btn_start, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not page.running and page.worker is None and page.queue_pos == 9, timeout=60000)
    assert records(win) == VERDICTS

    assert win.navigate("Logs & Export")
    logs = win.pages["Logs & Export"]
    qtbot.waitUntil(lambda: len(logs.rows) == 10, timeout=10000)  # type: ignore[attr-defined]
    usb = tmp_path / "usb"
    usb.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(usb / "demo.csv"), ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: str(usb))
    qtbot.mouseClick(logs.btn_csv, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
    qtbot.waitUntil(lambda: (usb / "demo_checks.csv").is_file() and logs._bg is None, timeout=30000)
    with (usb / "demo.csv").open(encoding="utf-8-sig", newline="") as f:
        assert sorted(r["result"] for r in csv.DictReader(f)) == sorted(VERDICTS)
    qtbot.mouseClick(logs.btn_img, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
    qtbot.waitUntil(lambda: len(list(usb.glob("*.png"))) == 10 and logs._bg is None, timeout=30000)

    qtbot.mouseClick(win.exit_presenter, Qt.MouseButton.LeftButton)
    assert win.navigate("Settings")
    resets: list[float] = []
    for _ in range(LONG_TRIES):  # judged by tests/budgets.py; the first puts back the run just played, the next two
        # the bundle as loaded (tests/test_demo.py plays the boards before each of its resets)
        started = time.monotonic()
        win = click(qtbot, win.pages["Settings"].demo.btn_reset)  # type: ignore[attr-defined]
        resets.append(time.monotonic() - started)
        assert win.in_demo and records(win) == [] and win.stack.currentWidget() is win.pages["Settings"]
    print("\nREQ-SET-007 Reset Demo, s:", [round(s, 2) for s in resets])
    assert judged(resets) < 10, resets
    assert shown == []


def test_req_set_007_the_fifteen_minute_script_checks_trains_and_tries_a_threshold(
    qtbot: QtBot, bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/demo/stage1-15min.md as clicks, in the presenter theme: AI Model Test runs on the demo version's locked
    validation set, the 20 OK and 11 NG boards its AI model never trained on, and gives counts; Start Training makes
    v1.1, whose AI Model Card says it is not yet tested and which judges nothing until Activate Selected, and Roll Back
    makes v1.0 active again; the NG record opened in Compare from Logs & Export, Allowed difference regions 2 and
    Re-evaluate still give NG, as the AI score check decides on its own, and the recipe is unchanged. Every page shown
    fits a 1920 px wide screen. The training run here is short; the script's run at the page's defaults is timed by hand
    (about 98 s on a 4-core PC)."""
    shown: list[str] = []
    monkeypatch.setattr(ui_errors, "show_error", lambda _parent, report: shown.append(str(report)))
    monkeypatch.setattr(main_window, "show_error", lambda _parent, report: shown.append(str(report)))
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
    assert test.source.currentData() and "31 images" in test.source.currentText()  # type: ignore[attr-defined]
    qtbot.mouseClick(test.btn_run, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
    qtbot.waitUntil(lambda: test.btn_run.isEnabled(), timeout=60000)  # type: ignore[attr-defined]
    tiles = {k: re.sub(r"<[^>]+>", " ", t.text()) for k, t in test.tiles.items()}  # type: ignore[attr-defined]
    assert " of 11" in tiles["missed_defects"] and " of 20" in tiles["false_calls"]
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
    assert "**Not yet tested on a locked validation set: nothing on this card is a measure of accuracy.**" in shown_card
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
    assert shown == []
