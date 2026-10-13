"""REQ-SET-004 (#104, A7 of the 2026-10 business-readiness brief): the splitters that let a page fit a 1366 x 768
projector (aoi/ui/widgets/reflow.py). A `ReflowSplitter` puts its panes one over the other below the width they need
side by side, and never holds a page wider than its widest pane; side by side again, it gives them the widths the page
set or the user dragged. A handler that asks again while it turns never turns it back (review of A7: Compare's need
changed with its arrangement, and turned it to and fro until Python's stack ran out). A `SideSplit` keeps its side
panel at the width the panel asks for wherever the picture keeps theme.IMAGE_MIN_W."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from aoi.ui import theme
from aoi.ui.widgets.reflow import ReflowSplitter, SideSplit


def _pane(least: int) -> QWidget:
    pane = QWidget()
    pane.setMinimumWidth(least)
    return pane


def _shown(qtbot: QtBot, splitter: QWidget, width: int, height: int = 400) -> QWidget:
    """`splitter` in a page `width` px wide, which the caller holds: a splitter that is a window of its own holds it
    at its panes' least widths, as no splitter on a page is held."""
    page = splitter.parentWidget()
    if page is None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        qtbot.addWidget(page)
        page.show()
        qtbot.waitExposed(page)
    _resized(splitter, width, height)
    return page


def _resized(splitter: QWidget, width: int, height: int = 400) -> None:
    page = splitter.parentWidget()
    assert page is not None
    page.resize(width, height)
    for _ in range(3):
        QApplication.processEvents()
    assert splitter.width() == width, (splitter.width(), width)


def test_req_set_004_panes_stack_below_their_need_and_take_their_widths_again_beside(qtbot: QtBot) -> None:
    splitter = ReflowSplitter()
    splitter.addWidget(_pane(300))
    splitter.addWidget(_pane(400))
    splitter.set_wide_sizes([450, 550])
    need = 700 + splitter.handleWidth()
    assert splitter.wide_need() == need and splitter.minimumSizeHint().width() == 400, "held wider than a pane"
    page = _shown(qtbot, splitter, 1000 + splitter.handleWidth())  # noqa: F841 (held while the test runs)
    assert splitter.wide() and splitter.sizes() == [450, 550]
    turns: list[bool] = []
    splitter.arranged.connect(turns.append)
    _resized(splitter, need - 1)
    assert not splitter.wide() and turns == [False]
    _resized(splitter, need)
    assert splitter.wide() and turns == [False, True]
    _resized(splitter, 1000 + splitter.handleWidth())
    assert splitter.sizes() == [450, 550], "side by side again, the panes kept the widths they had one over the other"
    splitter.moveSplitter(600, 1)  # as the user drags the handle, which says so (splitterMoved)
    _resized(splitter, need - 1)
    _resized(splitter, 1000 + splitter.handleWidth())
    assert splitter.sizes()[0] == 600, "the user's widths were lost"


def test_req_set_004_a_handler_asking_again_never_turns_the_panes_back(qtbot: QtBot) -> None:
    """A need 8 px larger side by side than one over the other, as Compare's was by its panel's margin, at a width
    between the two: each turn would ask for the other, without the guard."""
    splitter = ReflowSplitter(need=lambda: 500 + (8 if splitter.wide() else 0))
    splitter.addWidget(_pane(200))
    splitter.addWidget(_pane(200))
    turns: list[bool] = []
    splitter.arranged.connect(lambda wide: (turns.append(wide), splitter.reflow()))
    page = _shown(qtbot, splitter, 504)  # noqa: F841 (held while the test runs)
    for _ in range(3):
        before = len(turns)
        splitter.reflow()
        assert len(turns) - before <= 1, turns[before:]


def test_req_set_004_the_side_panel_keeps_its_width_while_the_picture_keeps_its_least(qtbot: QtBot) -> None:
    split = SideSplit(lambda side: 500)
    split.addWidget(QWidget())
    split.addWidget(QWidget())
    room = theme.IMAGE_MIN_W + 500 + split.handleWidth()
    page = _shown(qtbot, split, 1600)  # noqa: F841 (held while the test runs)
    for width in (1600, 1100, room):
        _resized(split, width)
        assert split.sizes()[1] == 500, (width, split.sizes())
