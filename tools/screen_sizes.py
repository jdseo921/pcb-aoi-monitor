"""Measure the smallest window each demo page fits, in each theme, and check a page's verdict area (REQ-SET-008, #104).

    python tools/screen_sizes.py [--bundle demo-bundle]

It loads the demo bundle (tools/make_demo_bundle.py; built into a temporary folder when none is given) into a
temporary workspace, signed in as the Admin, and puts each page in the state a demo shows it in: the 5-minute script's
run paused at its NG board, that board on Compare and selected on Logs & Export, and AI Model Test run once. Then it
measures every page the three demo scripts visit (DEMO_PAGES), in the presenter theme at its 18 pt and at its 16 pt (the
size it takes where the app has under theme.SMALL_H px of height or theme.SMALL_W px of width) and in the production
theme:

- narrowest: the narrowest window 768 px tall in which the page does not scroll across;
- nothing cut off at 1366: the shortest window 1366 px wide in which `cut_off` finds nothing: on Inspection, Compare
  and Logs & Export the verdict area (VERDICT_AREA) whole with nothing scrolled, and on every page no text cut off,
  across or down, and no scroll bar across, on the page or on a panel of fields in it;
- no scrolling at 1366: the shortest window 1366 px wide in which the page needs no scroll bar at all.

Each page is measured on the tab it opens on and on each tab the scripts open there (DEMO_TABS). It prints a Markdown
table, which docs/tests/2026-10-screen-sizes.md holds. The window is measured inside its frame: Windows takes the title
bar and the taskbar off a screen, so a window maximized on a 1366 x 768 screen measures about 1366 x 697 px.
tests/test_demo_fit.py checks the same pages and tabs at 1366 x 768. Fonts change the numbers by a few pixels: on Linux
the measurement pins DejaVu Sans, as the approved screenshots do.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script: the repository root holds the ``aoi`` and ``tools`` packages
    sys.path.insert(0, str(ROOT))

if TYPE_CHECKING:
    from aoi.ui.main_window import MainWindow

DEMO_PAGES = (  # every page the 5-, 15- and 45-minute scripts open, in sidebar order (docs/demo/)
    "Home", "Inspection", "Compare", "Training", "AI Model Test", "Recipe Editor", "Logs & Export", "Settings",
)  # fmt: skip
DEMO_TABS: dict[str, tuple[str, ...]] = {  # the tabs the scripts open beyond the one a page opens on (stage1-45min.md)
    "Training": ("Datasets", "What is missing"),
    "AI Model Test": ("History",),
    "Recipe Editor": ("Thresholds", "AOI checks", "Revisions"),
}
VERDICT_AREA: dict[str, tuple[str, ...]] = {  # the widgets a presenter shows the verdict with, by attribute (A7)
    # the verdict, the board with its defect boxes, the line under the verdict, the defect list, the review buttons,
    # and the two buttons the script presses there
    "Inspection": ("verdict", "view", "summary", "table", "review", "btn_compare", "btn_start"),
    "Compare": ("ref_view", "test_view", "verdict", "metrics"),  # the pair, the verdict and every check in its table
    "Logs & Export": ("summary",),  # the summary line under the records
}
THEMES = {  # name: (presenter theme, at its small size whatever the window's size)
    "presenter 18 pt": (True, False),
    "presenter 16 pt": (True, True),
    "production": (False, False),
}
WIDTH = 1366  # the projector width A7 fits (Charter principle 1, #104)
SMALL = (1366, 768)  # the projector A7 fits
TALLEST, WIDEST = 2400, 2560  # the largest window searched
# A window maximized on a 1366 x 768 Windows 10 screen at 100 % scaling: the taskbar (40 px) and the title bar (31 px)
# are off the screen's height (Windows 11's taskbar is 48 px, which leaves 689)
MAXIMIZED = (1366, 697)


def demo_views() -> list[tuple[str, str | None]]:
    """Every page the scripts open, each with the tab it opens on (None) and then each tab of DEMO_TABS."""
    return [(title, tab) for title in DEMO_PAGES for tab in (None, *DEMO_TABS.get(title, ()))]


def view_name(title: str, tab: str | None) -> str:
    return f"{title}, {tab} tab" if tab else title


def show_tab(win: MainWindow, title: str, tab: str | None) -> None:
    """`title` with its tab `tab` shown, as a click on it shows it; None: each of its tab bars on its first tab, where
    the page opens. A tab bar of its own (Training's) or a QTabWidget's, which follows its bar."""
    from PySide6.QtWidgets import QTabBar

    for tabs in win.pages[title].findChildren(QTabBar):
        names = [tabs.tabText(i).replace("&&", "&") for i in range(tabs.count())]
        if tab is None:
            tabs.setCurrentIndex(0)
        elif tab in names:
            tabs.setCurrentIndex(names.index(tab))
            return
    assert tab is None, f"{title} has no tab {tab}"


def whole(widget: Any) -> bool:
    """Shown whole where it is, nothing scrolled away or cut off: a click lands on it."""
    return bool(widget.isVisible() and widget.visibleRegion().boundingRect() == widget.rect())


def cut_off(win: MainWindow, title: str) -> list[str]:
    """What of `title`'s verdict area (VERDICT_AREA) is not whole in the window with the page scrolled to its top: a
    widget scrolled away or cut off, a table with a scroll bar, a defect box outside its picture's view; and anywhere
    on the page, a scroll bar across, on the page or on a panel of fields in it, or a label shorter or narrower than its
    text. Empty: the page fits."""
    from PySide6.QtWidgets import QAbstractScrollArea, QLabel, QScrollArea

    from aoi.ui.widgets.image_view import ImageView

    page = win.pages[title]
    area = win.findChild(QScrollArea, "pages")
    assert area is not None
    area.verticalScrollBar().setValue(0)
    area.horizontalScrollBar().setValue(0)
    problems = ["the page scrolls across"] if area.horizontalScrollBar().isVisible() else []
    for name in VERDICT_AREA.get(title, ()):
        widget = getattr(page, name)
        if not whole(widget):
            problems.append(f"{name} is not whole")
        if isinstance(widget, ImageView):
            view = widget.viewport().rect()
            problems += [f"a box on {name} is out of view" for r in widget.box_rects() if not view.contains(r)]
        elif isinstance(widget, QAbstractScrollArea):
            bars = {"across": widget.horizontalScrollBar(), "down": widget.verticalScrollBar()}
            problems += [f"{name} scrolls {way}" for way, bar in bars.items() if bar.isVisible()]
    for panel in page.findChildren(QScrollArea):  # a panel of fields, as the Recipe Editor's Thresholds tab
        if panel.isVisible() and panel.horizontalScrollBar().isVisible():
            problems.append(f"the panel {panel.objectName() or type(panel.widget()).__name__} scrolls across")
    for label in page.findChildren(QLabel):
        if not (label.isVisible() and label.text()):
            continue
        if label.width() < label.minimumSizeHint().width():  # a line's text, or a wrapped line's longest word
            problems.append(f"the label {label.text()[:40]!r} is cut across")
        elif label.wordWrap() and label.height() < label.heightForWidth(label.width()):
            problems.append(f"the label {label.text()[:40]!r} is cut off")
    return problems


def scrolls(win: MainWindow, down: bool = True) -> bool:
    """The page shown needs a scroll bar: across, or with `down` also down."""
    from PySide6.QtWidgets import QScrollArea

    area = win.findChild(QScrollArea, "pages")
    assert area is not None
    return area.horizontalScrollBar().isVisible() or (down and area.verticalScrollBar().isVisible())


@contextmanager
def theme_held(win: MainWindow, name: str) -> Iterator[None]:
    """The window in THEMES[name] whatever its height, as an Admin switches it on Settings; put back after."""
    from aoi.ui import theme

    presenter, small = THEMES[name]
    before = win.ctx.settings.presenter_theme
    small_below = 1 << 20 if small else 0  # every window is smaller, or none is
    with mock.patch.object(theme, "SMALL_H", small_below), mock.patch.object(theme, "SMALL_W", small_below):
        win.ctx.settings.presenter_theme = presenter
        win.apply_theme()
        try:
            yield
        finally:
            win.ctx.settings.presenter_theme = before
    win.apply_theme()


def shortest(win: MainWindow, fits: Callable[[], bool], width: int = WIDTH) -> int | None:
    """The shortest window `width` px wide in which `fits()`, to the pixel; None when not even TALLEST px fits.
    Assumes a page that fits a window fits every taller one."""
    low, high = win.minimumSizeHint().height(), TALLEST
    if not at(win, width, high, fits):
        return None
    while low < high:
        mid = (low + high) // 2
        if at(win, width, mid, fits):
            high = mid
        else:
            low = mid + 1
    return high


def narrowest(win: MainWindow, fits: Callable[[], bool], low: int = WIDTH, height: int = TALLEST) -> int | None:
    """The narrowest window `height` px tall in which `fits()`, to the pixel, from `low` up to WIDEST; None when not
    even WIDEST px fits. A window is never narrower than its minimum width, which a smaller `low` stands for."""
    low, high = max(low, win.minimumSizeHint().width()), WIDEST
    if not at(win, high, height, fits):
        return None
    while low < high:
        mid = (low + high) // 2
        if at(win, mid, height, fits):
            high = mid
        else:
            low = mid + 1
    return high


def at(win: MainWindow, width: int, height: int, fits: Callable[[], bool]) -> bool:
    """`fits()` in a window of `width` x `height` px, laid out."""
    from tools.render_screens import settle

    win.resize(width, height)
    settle()
    return fits()


def demo_window(bundle: Path, workspace: Path) -> MainWindow:
    """The demo loaded from `bundle` into `workspace`, signed in as the Admin, each page as a demo shows it (module
    docstring), in the production theme."""
    from PySide6.QtTest import QTest

    from aoi.ui import main_window
    from aoi.ui.demo_workspace import open_demo
    from tools.render_screens import wait_until

    os.environ["AOI_DEMO_BUNDLE"] = str(bundle)
    os.environ["AOI_WORKSPACE"] = str(workspace)
    ctx = open_demo()
    assert ctx is not None, "the demo bundle did not load"
    win = main_window.build_window(ctx)
    assert win is not None
    win.resize(1920, 1080)
    win.show()
    QTest.qWaitForWindowExposed(win)
    win.set_user("admin")
    page: Any = win.pages["Settings"]
    page.demo.pace.setValue(1)
    inspection: Any = win.pages["Inspection"]
    win.navigate("Inspection")
    inspection.btn_start.click()
    wait_until(lambda: not inspection.running and inspection.worker is None)
    inspection.btn_compare.click()
    compare: Any = win.pages["Compare"]
    wait_until(lambda: "NG" in compare.verdict.text())
    win.navigate("Logs & Export")
    logs: Any = win.pages["Logs & Export"]
    wait_until(lambda: len(logs.rows) == 4 and logs.listing is None)
    logs.table.selectRow(next(i for i, r in enumerate(logs.rows) if r["result"] == "NG"))
    win.navigate("AI Model Test")
    test: Any = win.pages["AI Model Test"]
    test.btn_run.click()
    wait_until(lambda: test.btn_run.isEnabled())
    return win


class Size(NamedTuple):
    """What one page, on one tab, needs in one theme (module docstring)."""

    narrowest: int | None  # the narrowest window 768 px tall in which the page does not scroll across
    verdict: int | None  # the shortest window 1366 px wide with nothing cut off (`cut_off`); None: none is
    verdict_across: int | None  # where `verdict` is None, the narrowest window in which nothing is
    whole: int | None  # the shortest window 1366 px wide with no scroll bar
    maximized: list[str]  # what `cut_off` finds at MAXIMIZED


def measure(win: MainWindow) -> dict[tuple[str, str], Size]:
    """What each view of `demo_views` needs in each of THEMES (module docstring), by (view_name, theme)."""
    sizes = {}
    win.showNormal()
    for name in THEMES:
        with theme_held(win, name):
            for title, tab in demo_views():
                print(f"{time.strftime('%H:%M:%S')} measuring {view_name(title, tab)}, {name}", file=sys.stderr)
                assert win.navigate(title), title
                show_tab(win, title, tab)

                def fits(title: str = title) -> bool:
                    return not cut_off(win, title)

                least = narrowest(win, lambda: not scrolls(win, down=False), low=0, height=SMALL[1])
                verdict = shortest(win, fits)
                across = narrowest(win, fits) if verdict is None else None
                full = shortest(win, lambda: not scrolls(win))
                at(win, *MAXIMIZED, fits)
                sizes[view_name(title, tab), name] = Size(least, verdict, across, full, cut_off(win, title))
                show_tab(win, title, None)
    return sizes


def table(sizes: dict[tuple[str, str], Size]) -> str:
    """The measurements as docs/tests/2026-10-screen-sizes.md shows them: a table for each theme."""

    def px(value: int | None, wider: int | None = None) -> str:
        if value is not None:
            return str(value)
        return f"none; {wider} px across at least" if wider is not None else f"none up to {TALLEST}"

    out = []
    for name in THEMES:
        out += [
            f"### {name[0].upper()}{name[1:]}",
            "",
            f"| Page | Narrowest, {SMALL[1]} px tall | Nothing cut off, {WIDTH} px wide "
            f"| No scrolling, {WIDTH} px wide | At {MAXIMIZED[0]} x {MAXIMIZED[1]} (maximized) |",
            "|---|---|---|---|---|",
        ]
        for title, tab in demo_views():
            size = sizes[view_name(title, tab), name]
            maximized = "; ".join(size.maximized) or "fits"
            out.append(
                f"| {view_name(title, tab)} | {px(size.narrowest)} | {px(size.verdict, size.verdict_across)} "
                f"| {px(size.whole)} | {maximized} |"
            )
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bundle", type=Path, help="the demo bundle (default: build one in a temporary folder)")
    parser.add_argument("--font", default='"DejaVu Sans"' if sys.platform == "linux" else "", help="font to pin")
    args = parser.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from aoi.ui import errors, main_window, theme
    from aoi.ui.workers import collect_on_ui_thread
    from tools import render_screens

    def refused(_parent: object, report: object) -> None:  # a message box would wait for a click no one makes
        raise SystemExit(f"the demo showed a message, so its pages are not as a demo shows them: {report}")

    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    collect_on_ui_thread()  # as main.py: no pool thread runs Python's cycle collector
    app.setStyleSheet(theme.stylesheet())
    with (
        tempfile.TemporaryDirectory(prefix="aoi-sizes-") as tmp,
        render_screens.pinned_rendering(app, args.font),
        mock.patch.object(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes),
        mock.patch.object(errors, "show_error", refused),
        mock.patch.object(main_window, "show_error", refused),
    ):
        bundle = args.bundle
        if bundle is None:
            from tools.make_demo_bundle import build

            bundle = Path(tmp) / "demo-bundle"
            build(bundle)
        win = demo_window(bundle, Path(tmp) / "default_workspace")
        try:
            print(table(measure(win)))
        finally:
            win.close()
            win.ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
