"""Error dialogs, the alarm list and the error sentences on pages show in the UI language (REQ-SET-005, #198).

A translator that marks every string it translates ("§" + source) stands in for a filled aoi_ko.ts: whatever reaches
the screen without that mark never went through translation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QRectF, QTranslator
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core.services import AppContext, ErrorReport
from aoi.errors import AoiError
from aoi.ui.errors import dialog_text
from tests.test_req_done_in_v01 import _inspect_one, _window

SIGN_IN = "§Sign in as a user with that role, or ask one to do it."


class Marking(QTranslator):
    def translate(self, context: str, source: str, disambiguation: str | None = None, n: int = -1) -> str:
        return "§" + source


def test_req_set_005_error_dialogs_alarms_and_notes_show_in_the_ui_language(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, dialogs: list[tuple[str, str]]
) -> None:
    """#198: an Operator's Save to Recipe on Compare, a role refusal from the services, an unexpected error on a page,
    the Recipe Editor's limits, the NG and ERROR alarms (after a restart too), Compare's AOI-CMP-001 note, the
    Golden board pane and the empty state of a file that is no image on Inspection and on Compare's test pane come out
    translated: each template first, then filled with values that are translated too. The stored alarm message and the
    log keep the English."""
    translator = Marking()
    assert QCoreApplication.installTranslator(translator)
    try:
        win = _window(qtbot, trained_ctx, "Operator")
        page = _inspect_one(qtbot, win, ng_board)
        assert page.last is not None and page.last.verdict == "NG" and page.last_id is not None
        compare = win.pages["Compare"]
        compare.save_recipe()
        refused = "§§Changing recipes needs the §Engineer or Admin role."
        assert dialogs == [("AOI-USR-001 §Not allowed for this role", f"{refused}\n\n{SIGN_IN}")]
        with pytest.raises(AoiError) as e:
            trained_ctx.import_samples("B", [], "OK")
        assert dialog_text(ErrorReport.of(e.value))[1].startswith("§§Importing samples needs the §Engineer or Admin")
        restarted = _window(qtbot, AppContext(Settings(workspace=trained_ctx.settings.workspace, device="cpu")))
        restarted.navigate("Inspection")
        alarms = restarted.pages["Inspection"].alarms
        lines = [alarms.item(i).text().split("  ", 3)[1:] for i in range(alarms.count())]
        assert lines == [
            ["[ERROR]", "AOI-USR-001", refused],
            ["[NG]", "AOI-INSP-003", f"§{ng_board.name}: {len(page.last.defects)} defect(s)"],
        ]
        english = [a["message"] for a in trained_ctx.alarms()]
        assert english == [
            "Changing recipes needs the Engineer or Admin role.",
            f"{ng_board.name}: {len(page.last.defects)} defect(s)",
        ]
        unexpected = dialog_text(trained_ctx.report_error(ValueError("x"), compare.title))
        assert unexpected[1].startswith("§An unexpected error (ValueError) stopped the last action§ (§Compare).")
        for path in trained_ctx.db.map_paths(page.last_id):
            Path(str(path)).unlink()
        compare.show_stored(page.last_id)
        qtbot.waitUntil(trained_ctx.jobs.idle, timeout=20000)
        assert f"AOI-CMP-001 §The result of {ng_board.name} was saved without" in compare.note.text()
        _, pane, _, _ = compare.golden_board_unreadable(AoiError("AOI-INSP-001", path="gone.png"))
        assert pane.startswith("§AOI-INSP-001 §The file gone.png could not be opened as an image. ")
        bad = Path(trained_ctx.settings.workspace).with_name("board_0042.png")
        bad.write_bytes(b"not an image at all")
        shown = len(dialogs)
        page._set_queue([bad])
        page.next_board()
        qtbot.waitUntil(lambda: len(dialogs) > shown and page.worker is None, timeout=30000)
        compare.set_test(str(bad))
        qtbot.waitUntil(lambda: len(dialogs) > shown + 1 and compare._bg is None, timeout=30000)
        what = f"AOI-INSP-004 §The file {bad} does not hold a PNG, JPG, BMP or TIFF image; the format is read from"
        assert page.empty.sentence.text().startswith(what), page.empty.sentence.text()
        assert page.empty.sentence.text().endswith(
            " §No board is left in the queue. Load Images… or Load Folder… to queue more boards."
        )  # the last board in the queue (#182)
        assert compare.test_empty.sentence.text().startswith(what), compare.test_empty.sentence.text()
        win.set_user("engineer")
        win.navigate("Recipe Editor")
        editor = win.pages["Recipe Editor"]
        editor.view.roiDrawn.emit(QRectF(20, 30, 40, 50))
        editor.r_hmin.setValue(5)
        editor.r_hmax.setValue(1)
        editor.apply_roi()
        assert dialogs[-1][1].startswith("§ROI R1: §Height min 5 and max 1 cannot be stored"), dialogs[-1]
    finally:
        QCoreApplication.removeTranslator(translator)
