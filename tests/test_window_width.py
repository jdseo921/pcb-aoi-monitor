"""Training's line over the samples table and Compare's file names never make the window wider than a 1920 px screen,
however long the file names of the samples and boards are, and a file name in a message on a Compare pane stays within
the pane (REQ-SET-004, #245).

The window is as wide as its widest page asks, shown or not, so one label that grows with a file name widens every page.
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from aoi.core.imaging import list_images
from aoi.core.services import AppContext
from aoi.ui.pages.compare import ComparePage
from aoi.ui.pages.training import TrainingPage
from tests.conftest import ZWSP, wrapped
from tests.test_req_done_in_v01 import _window

LINE_NAME = "20261003_143012_SN000123_TOP"  # 28 characters: date, time, serial and side, as a line names its photos


def _import(ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, stem: str, n: int) -> None:
    """`n` OK samples, each imported from SNxxxx/<stem>.png, a folder of its own serial number."""
    sources = []
    for i, p in enumerate(list_images(synthetic_dataset / "train" / "ok")[:n]):
        folder = tmp_path / "in" / f"SN{i:04d}"
        folder.mkdir(parents=True)
        sources.append(str(shutil.copy(p, folder / f"{stem}.png")))
    ctx.import_samples("TINY", sources, "OK")


def _digits_after_hyphens(monkeypatch: pytest.MonkeyPatch) -> None:
    """uuid.uuid4 drawn so that a digit follows hyphens 1, 3 and 4 (the version digit 4 follows hyphen 2): Qt then
    breaks the UUID nowhere, as for about 1 UUID in 5."""
    real = uuid.uuid4

    def drawn() -> uuid.UUID:
        h = list(real().hex)
        h[8], h[16], h[20] = "1", "9", "1"  # 9: a digit that keeps the variant
        return uuid.UUID(hex="".join(h))

    monkeypatch.setattr(uuid, "uuid4", drawn)


@pytest.mark.parametrize(("chars", "n"), [(len(LINE_NAME), 20), (100, 20), (len(LINE_NAME), 3)])
def test_req_set_004_a_long_reference_name_never_widens_the_window(
    qtbot: QtBot, ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, chars: int, n: int
) -> None:
    """Training's line over the samples table names the reference image, the first OK sample until training sets the
    Golden board. A long sample file name made that line, and so every page, wider than a 1920 px screen: from a source
    file name of about 12 to 14 characters before its extension while fewer than 20 OK samples were imported (the line
    then also carried the 20-image tip), and of about 50 with 20 or more; from about 20 with 20 samples once a sample's
    file name carries its 36-character UUID (#245). The name is now cut at its end to the line's width, so the source
    file's name shows first, and the tooltip shows the whole line. The tip has a line of its own, under 20 OK samples:
    beside the counts it left the name no room at 1920 px, and the line read "reference: …"."""
    stem = (LINE_NAME + "_PANEL" * 40)[:chars]
    _import(ctx, synthetic_dataset, tmp_path, stem, n)
    win = _window(qtbot, ctx, "Engineer")
    win.resize(1920, 1080)
    win.navigate("Training")
    page = win.pages["Training"]
    assert isinstance(page, TrainingPage)
    qtbot.waitUntil(lambda: page.counts.isVisible() and page.counts.width() > 0)
    qtbot.wait(50)  # the layout settles
    assert win.minimumSizeHint().width() <= 1920, "a page asks for more than a 1920 px screen"
    assert win.width() == 1920

    name = Path(ctx.reference_image("TINY") or "").name
    head = f"{n} OK · 0 NG · reference: "
    label = page.counts
    shown = label.text()
    assert label.fontMetrics().horizontalAdvance(shown) + 2 * label.margin() <= label.width(), "the line is clipped"
    assert shown.startswith(head)
    cut = shown[len(head) :]
    assert cut.startswith(LINE_NAME), "the source file's name shows"
    assert page.tip.isVisible() == (n < 20), "the 20-image tip has a line of its own"
    if chars > len(LINE_NAME):  # too long for the line at any width a 1920 px window gives it
        assert cut != name
    if cut == name:
        assert label.toolTip() == ""
    else:
        assert cut.endswith("…") and name.startswith(cut[:-1]) and label.toolTip() == head + name


@pytest.mark.parametrize(("chars", "maps"), [(len(LINE_NAME), True), (100, True), (100, False)])
def test_req_set_004_compare_names_never_widen_the_window(
    qtbot: QtBot,
    ctx: AppContext,
    synthetic_dataset: Path,
    ng_board: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chars: int,
    maps: bool,
) -> None:
    """Compare names the test board, the Golden board a stored result was judged against and, in the note, the board
    model's Golden board today and, once the result's maps are gone (as after the OK-map retention period), the board
    again in AOI-CMP-001, in labels that wrap only where a line may break. Qt breaks a UUID only at a hyphen that no
    digit follows, so for about 1 UUID in 5, drawn here every time, `<stem>_<sample UUID>.png` was one word, and a stem
    of 10 characters made the window 1781 px wide, 28 characters 2245 px. A long source file name did the same through
    the test board's label and AOI-CMP-001, before #245 too. The names now break after each _ and -, and show whole."""
    _digits_after_hyphens(monkeypatch)
    stem = (LINE_NAME + "_PANEL" * 40)[:chars]
    _import(ctx, synthetic_dataset, tmp_path, stem, 3)
    board = tmp_path / "SN9999" / f"{stem}.png"
    board.parent.mkdir()
    shutil.copy(ng_board, board)
    ctx.inspect_file("TINY", str(board))  # judged against the first sample
    ctx.set_reference("TINY", ctx.samples("TINY", "OK")[1]["id"])
    (rec,) = ctx.inspections(board_model="TINY")
    for gone in [p for p in (rec["diff_map_path"], rec["ai_map_path"]) if p and not maps]:  # no AI model: no AI map
        Path(gone).unlink()  # as after the retention period: the note adds AOI-CMP-001
    win = _window(qtbot, ctx, "Engineer")
    win.resize(1920, 1080)
    win.navigate("Compare")
    page = win.pages["Compare"]
    assert isinstance(page, ComparePage)
    page.show_stored(rec["id"])
    qtbot.waitUntil(lambda: page._bg is None and "as judged" in page.ref_label.text(), timeout=30000)
    qtbot.wait(50)  # the layout settles
    assert win.minimumSizeHint().width() <= 1920, "a page asks for more than a 1920 px screen"
    judged, today = (Path(str(r["path"])).name for r in ctx.samples("TINY", "OK")[:2])
    assert page.ref_label.text().replace(ZWSP, "") == f"Golden board as judged: {judged}"
    assert page.test_label.text().replace(ZWSP, "") == f"Test board: {board.name} (stored result)"
    note = page.note.text().replace(ZWSP, "")
    assert f"Golden board is now {today}." in note
    assert (f"AOI-CMP-001 The result of {board.name} was saved without" in note) != maps, note


def _named_within(label: QLabel, path: Path) -> None:
    """`label`, a message on a picture's pane, names the whole `path`, and its text from the file's name on wraps within
    the label, the name breaking after each _ and -. The measure starts at the name: Qt never breaks a Windows path
    after a backslash, and the workspace's folders before the name are not #245's."""
    text = label.text()
    assert str(path) in text.replace(ZWSP, ""), text
    shown = re.search(f"{ZWSP}?".join(map(re.escape, path.name)), text)
    assert shown is not None
    rect = QRect(0, 0, label.width(), 100000)
    needs = label.fontMetrics().boundingRect(rect, Qt.TextFlag.TextWordWrap, text[shown.start() :]).width()
    assert needs <= label.width(), f"the name runs past the pane's edge: {path.name}"
    assert shown.group() == wrapped(path.name), "the name breaks after each _ and -"


@pytest.mark.parametrize(("stem", "role"), [("ok_000", "Engineer"), (LINE_NAME, "Operator")])
def test_req_set_004_a_golden_board_that_cannot_be_opened_is_named_within_its_pane(
    qtbot: QtBot,
    ctx: AppContext,
    synthetic_dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stem: str,
    role: str,
) -> None:
    """When the board model's Golden board cannot be opened, Compare's Golden board pane says so with the error's code
    and what happened, which names the file, and the next step for the role (an Operator asks an Engineer). The name
    ran past the pane's edge and was cut off: a sample's copy now ends in its UUID, so for about 1 UUID in 5, drawn
    here every time, even ok_000.png's copy was one word of about 520 px in the 357 px label (351 px before #245); a
    28-character line name ran past the edge before #245 too (452 px in 400). The name now breaks after each _ and -."""
    _digits_after_hyphens(monkeypatch)
    _import(ctx, synthetic_dataset, tmp_path, stem, 3)
    golden = Path(str(ctx.reference_image("TINY")))
    golden.unlink()  # the board model's Golden board, the first OK sample until training sets one, is gone
    win = _window(qtbot, ctx, role)
    win.resize(1920, 1080)
    win.navigate("Compare")
    page = win.pages["Compare"]
    assert isinstance(page, ComparePage)
    label = page.ref_empty.sentence
    qtbot.waitUntil(lambda: page._bg is None and label.isVisible() and label.width() > 0, timeout=30000)
    qtbot.wait(50)  # the layout settles
    assert label.text().startswith("AOI-INSP-001 The file ")
    assert ("Ask an Engineer" in label.text()) == (role == "Operator"), "the step of the role signed in"
    _named_within(label, golden)


def test_req_set_004_a_test_board_that_cannot_be_read_is_named_within_its_pane(
    qtbot: QtBot, ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, dialogs: list[tuple[str, str]]
) -> None:
    """Compare's test board pane says why the board was not inspected with the error's code and what happened, which
    names the file. A line's 28-character name, 32 with .png, was one word of about 370 px in the 357 px label and ran
    past the pane's edge, before #245 too. It now breaks after each _ and -."""
    _import(ctx, synthetic_dataset, tmp_path, "ok", 3)
    bad = tmp_path / "SN9999" / f"{LINE_NAME}.png"
    bad.parent.mkdir()
    bad.write_bytes(b"not an image at all")
    win = _window(qtbot, ctx, "Engineer")
    win.resize(1920, 1080)
    win.navigate("Compare")
    page = win.pages["Compare"]
    assert isinstance(page, ComparePage)
    page.set_test(str(bad))
    label = page.test_empty.sentence
    qtbot.waitUntil(lambda: page._bg is None and bool(dialogs) and label.isVisible(), timeout=30000)
    qtbot.wait(50)  # the layout settles
    assert dialogs[0][0].startswith("AOI-INSP-004") and label.text().startswith("AOI-INSP-004 The file ")
    _named_within(label, bad)
