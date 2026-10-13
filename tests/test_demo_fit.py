"""A7 of the 2026-10 business-readiness brief (#104, Charter principle 1): every page and tab the three demo scripts
visit fits a 1366 x 768 projector in the presenter theme, its verdict area whole with nothing scrolled (the verdict,
the defect boxes, the Compare pair and its table, the Logs summary line), and the production theme fits it too. Below
the fold a page may scroll; across, none does, and no text is cut off. tools/screen_sizes.py measures what each page
needs (docs/tests/2026-10-screen-sizes.md).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.ui import errors as ui_errors
from aoi.ui import main_window, theme
from tests.test_demo_ui import _windows_closed, click, station  # noqa: F401 (an autouse fixture)
from tools.render_screens import TEST_FONT, pinned_rendering, settle
from tools.screen_sizes import VERDICT_AREA, at, cut_off, demo_views, demo_window, show_tab, theme_held, view_name


@pytest.fixture
def bundle(demo_bundle: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The demo bundle as the build ships it, where Load Demo Workspace looks for it."""
    monkeypatch.setenv("AOI_DEMO_BUNDLE", str(demo_bundle))
    return demo_bundle


@pytest.fixture(autouse=True)
def pinned(qapp: QApplication) -> Iterator[None]:
    """Text drawn as the approved screenshots and tools/screen_sizes.py draw it, hinting off: on Linux in DejaVu Sans,
    on Windows in the theme's own fonts. Hinted, a line may wrap where the record's does not, and a cut line pass."""
    with pinned_rendering(qapp, TEST_FONT if sys.platform == "linux" else ""):
        yield


@pytest.mark.parametrize("presenter", [True, False], ids=["presenter", "production"])
def test_req_set_008_every_demo_page_fits_1366_by_768_with_its_verdict_area_whole(
    qtbot: QtBot, bundle: Path, monkeypatch: pytest.MonkeyPatch, presenter: bool
) -> None:
    """In a 1366 x 768 window, each page as the 5-minute script leaves it (the run paused at its NG board, that board
    on Compare and selected on Logs & Export), on the tab it opens on and on each tab the 45-minute script opens
    (tools/screen_sizes.py, DEMO_TABS): no page scrolls across, no text is cut off across or down, and on Inspection,
    Compare and Logs & Export the verdict area (VERDICT_AREA) is whole with nothing scrolled, every defect box in its
    picture's view and no scroll bar on a table in it. The presenter theme takes its 16 pt size there. The window then
    grows to 1500 x 1000 and 1920 x 1080, where the presenter theme takes its 18 pt again, and the verdict areas are
    whole there too: Compare's table keeps the height its rows need at the new text size and width (review of A7).
    Then, each view shown at 1920 x 1080 first, as on a laptop's screen before the projector, every view fits at
    1366 x 768 again: Training's Labeller agreement, laid out wide first, had its lines cut short there. No message on
    the way."""
    shown: list[str] = []
    monkeypatch.setattr(ui_errors, "show_error", lambda _parent, report: shown.append(str(report)))
    monkeypatch.setattr(main_window, "show_error", lambda _parent, report: shown.append(str(report)))
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    win = click(qtbot, station(qtbot).pages["Settings"].demo.btn_load)  # type: ignore[attr-defined]
    settings: Any = win.pages["Settings"]
    settings.demo.pace.setValue(1)  # the test's own pace
    if presenter:
        settings.presenter.click()
    win.showNormal()  # it opens maximized, and full screen once the presenter theme is on
    win.resize(1366, 768)
    qtbot.waitUntil(lambda: win.size() == QSize(1366, 768))
    assert theme.presenter() is presenter and theme.small() is presenter

    page: Any = win.pages["Inspection"]
    assert win.navigate("Inspection")
    page.btn_start.click()
    qtbot.waitUntil(lambda: not page.running and page.worker is None, timeout=60000)
    assert page.last is not None and page.last.verdict == "NG" and page.view.box_rects()
    page.btn_compare.click()
    compare: Any = win.pages["Compare"]
    qtbot.waitUntil(lambda: "NG" in compare.verdict.text() and bool(compare.test_view.box_rects()), timeout=60000)
    assert compare.metrics.rowCount() >= 5
    assert win.navigate("Logs & Export")
    logs: Any = win.pages["Logs & Export"]
    qtbot.waitUntil(lambda: len(logs.rows) == 4 and logs.listing is None, timeout=10000)
    logs.table.selectRow(next(i for i, r in enumerate(logs.rows) if r["result"] == "NG"))

    problems = {}
    for title, tab in demo_views():
        assert win.navigate(title), title
        show_tab(win, title, tab)
        settle()
        problems[view_name(title, tab)] = cut_off(win, title)
        show_tab(win, title, None)
    assert problems == dict.fromkeys(problems, []), problems
    assert set(VERDICT_AREA) <= {title for title, _tab in demo_views()} and len(problems) == 14

    for width, height in ((1500, 1000), (1920, 1080)):
        win.resize(width, height)
        qtbot.waitUntil(lambda: win.size() == QSize(width, height))  # noqa: B023 (waited on here, in the loop)
        assert theme.presenter() is presenter and not theme.small()
        assert theme.FONT_PT == (18 if presenter else 14)
        for title in VERDICT_AREA:
            assert win.navigate(title), title
            settle()
            problems[f"{title} at {width} x {height}"] = cut_off(win, title)
    assert problems == dict.fromkeys(problems, []), problems

    for title, tab in demo_views():  # each view laid out at 1920 px, then back at 1366, as on the projector
        assert win.navigate(title), title
        show_tab(win, title, tab)
        settle()
    win.resize(1366, 768)
    qtbot.waitUntil(lambda: win.size() == QSize(1366, 768))
    for title, tab in demo_views():
        assert win.navigate(title), title
        show_tab(win, title, tab)
        settle()
        problems[f"{view_name(title, tab)}, back at 1366 x 768"] = cut_off(win, title)
        show_tab(win, title, None)
    assert problems == dict.fromkeys(problems, []), problems
    assert shown == []


def test_req_set_004_trainings_wrapped_lines_stay_whole_at_1366_by_768(
    qtbot: QtBot, demo_bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Training, on the tab it opens on and on Datasets, in a 1366 x 768 window and in one maximized on a 1366 x 768
    Windows screen, the demo as tools/screen_sizes.py measures it (the window shown at 1920 x 1080 first), and again
    after a window 2560 px wide: every wrapped line whole, in the production theme and the presenter theme's 16 pt.
    A box layout gave a group its form's preferred height for its width, short of what its wrapped lines need, and the
    Labeller agreement's "No calibration set yet" and "No agreement check yet" were cut short; and after 2560 px the
    form laid its rows out at that width's heights, and the line under the dataset version kept two lines' height
    where it wraps to three (docs/tests/2026-10-screen-sizes.md, A7). A `WrappedGroup` holds both."""
    monkeypatch.setattr(ui_errors, "show_error", lambda _parent, report: pytest.fail(str(report)))
    monkeypatch.setattr(main_window, "show_error", lambda _parent, report: pytest.fail(str(report)))
    win = demo_window(demo_bundle, tmp_path / "ws")
    qtbot.addWidget(win)
    win.showNormal()
    problems = {}
    for name in ("production", "presenter 16 pt"):
        with theme_held(win, name):
            assert win.navigate("Training")
            for tab in (None, "Datasets"):
                show_tab(win, "Training", tab)
                for size in ((1366, 768), (1366, 697), (2560, 768), (1366, 768), (1366, 697)):
                    at(win, *size, lambda: True)
                    if size[0] == 1366:
                        problems[name, tab, size, len(problems)] = cut_off(win, "Training")
            show_tab(win, "Training", None)
    assert problems == dict.fromkeys(problems, []), problems
