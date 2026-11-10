"""The Inspection page runs the line (REQ-INSP-020): Watch Input Folder, Start and Stop as resume and pause, the line's
state and its queue depth, and every board that arrives inspected while it runs, by an Operator."""

from __future__ import annotations

import time
from pathlib import Path

from pytestqt.qtbot import QtBot

from aoi.core.imaging import list_images
from aoi.core.services import AppContext
from tests.test_folder_watch import NAMES, arrive
from tests.test_req_done_in_v01 import BOARD, _window


def test_req_insp_020_an_operator_runs_pauses_and_resumes_the_line(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    inbox = tmp_path / "in"
    inbox.mkdir()
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    assert not page.act_watch.isEnabled()  # no input folder set: greyed, with what turns it on
    trained_ctx.settings.input_folder = str(inbox)
    page.on_show()
    assert page.act_watch.isEnabled() and not page.act_start.isEnabled()
    page.act_watch.trigger()  # the folder is opened off the UI thread
    qtbot.waitUntil(lambda: page.watch is not None, timeout=10000)
    assert page.watch is not None and page.act_start.isEnabled() and not page.act_next.isEnabled()
    assert "Line paused" in page.queue_label.text()
    srcs = sorted(list_images(synthetic_dataset / "test"))[:4]
    page.act_start.trigger()
    assert "Line running" in page.queue_label.text()
    for src, name in zip(srcs[:2], NAMES[:2], strict=True):
        arrive(src, inbox, name)
    arrive(srcs[2], inbox, "board3.png")  # breaks the contract: failed/, with its alarm in the list
    qtbot.waitUntil(lambda: len(trained_ctx.inspections(board_model=BOARD)) == 2, timeout=60000)
    qtbot.waitUntil(lambda: (inbox / "failed" / "board3.png").is_file(), timeout=10000)
    page.act_stop.trigger()
    qtbot.waitUntil(lambda: page.worker is None, timeout=10000)
    assert "Line paused" in page.queue_label.text() and not page.running
    arrive(srcs[3], inbox, NAMES[3])
    time.sleep(1.0)
    qtbot.wait(300)  # paused: nothing is taken
    assert len(trained_ctx.inspections(board_model=BOARD)) == 2 and (inbox / NAMES[3]).is_file()
    page.act_start.trigger()
    qtbot.waitUntil(lambda: page.worker is None and len(list((inbox / "done").iterdir())) == 3, timeout=60000)
    assert len(trained_ctx.inspections(board_model=BOARD)) == 3 and sorted(
        p.name for p in (inbox / "done").iterdir()
    ) == sorted([NAMES[0], NAMES[1], NAMES[3]])
    page._refresh_alarms()
    assert any("AOI-INSP-025" in page.alarms.item(i).text() for i in range(page.alarms.count()))
    page.act_stop.trigger()
    qtbot.waitUntil(lambda: page.worker is None, timeout=10000)
