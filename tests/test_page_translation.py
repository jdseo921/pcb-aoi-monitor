"""The Training log, Training's samples table and Settings' Hardware interfaces table show in the UI language
(REQ-SET-005, #199).

The translator here is built from the committed aoi/i18n/aoi_ko.ts with every message translated as "§" + its source,
so a string shows marked only when it reaches translate() and is in the translation file a translator fills.
"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QTranslator
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.ui.pages.settings import SettingsPage
from aoi.ui.pages.training import TrainingPage
from tests.test_req_done_in_v01 import _window
from tools.update_translations import TS_FILE, qt_tool


@pytest.fixture
def marked(tmp_path: Path) -> Iterator[None]:
    """A translator from aoi_ko.ts with every message translated as "§" + source, installed for the test."""
    tree = ET.parse(TS_FILE)
    for message in tree.getroot().iter("message"):
        translation = message.find("translation")
        assert translation is not None
        translation.text = "§" + (message.findtext("source") or "")
        translation.attrib.pop("type", None)  # no longer "unfinished"
    tree.write(tmp_path / "marked.ts", encoding="utf-8", xml_declaration=True)
    qm = tmp_path / "marked.qm"
    subprocess.run([qt_tool("pyside6-lrelease"), "-silent", str(tmp_path / "marked.ts"), "-qm", str(qm)], check=True)
    translator = QTranslator()
    assert translator.load(str(qm)) and QCoreApplication.installTranslator(translator)
    try:
        yield
    finally:
        QCoreApplication.removeTranslator(translator)


def test_req_set_005_every_training_log_line_is_translated(qtbot: QtBot, trained_ctx: AppContext, marked: None) -> None:
    """#199 defect 1: a training run stopped after its first epoch fills the log with the engine's progress lines
    (aligning, training on, stopped, calibrated with its rule) and the page's own; every line, and the calibration
    rule inside it, is in the UI language. Before, only the epoch and "Stopped:" lines were."""
    win = _window(qtbot, trained_ctx, "Engineer")
    win.navigate("Training")
    page = win.pages["Training"]
    assert isinstance(page, TrainingPage)
    page.epochs.setValue(page.epochs.minimum())
    page.input_size.setCurrentIndex(0)
    page.train()
    assert page.worker is not None
    job = page.worker.job  # Stop once the first epoch is done, on the training thread, so the engine sees it there
    job.on_progress(lambda a: job.cancel() if a[0] >= 1 else None)
    qtbot.waitUntil(lambda: page.worker is None, timeout=120000)
    lines = page.log.toPlainText().splitlines()
    assert len(lines) >= 5, lines
    assert [line for line in lines if not line.startswith("§")] == []
    calibrated = next(line for line in lines if line.startswith("§Calibrated image threshold"))
    assert "(§" in calibrated, calibrated  # the rule is a phrase of its own
    assert "§Stopped by user; calibrating current weights" in lines and lines[0].startswith("§Aligning")
    assert lines[-1] == "§Stopped: no AI model was saved; the active AI model is unchanged."


def test_req_set_005_the_training_samples_table_shows_the_view_translated(
    qtbot: QtBot, trained_ctx: AppContext, marked: None
) -> None:
    """#199 defect 3: the View column of Training's samples table shows the camera view in the UI language, as
    Inspection, Logs and Compare do; before, it showed the stored key ("Top")."""
    win = _window(qtbot, trained_ctx, "Engineer")
    win.navigate("Training")
    table = win.pages["Training"].samples
    views = [table.item(r, 3).text() for r in range(table.rowCount())]
    assert views and all(v == "§Top" for v in views), sorted(set(views))


def test_req_set_005_the_hardware_table_shows_its_stages_translated(
    qtbot: QtBot, trained_ctx: AppContext, marked: None
) -> None:
    """#199 defect 2: every cell of Settings' Hardware interfaces table, the Stage column included, is in the
    translation file and shows in the UI language; before, "Stage 1" to "Stage 4" were never extracted."""
    win = _window(qtbot, trained_ctx, "Admin")
    win.navigate("Settings")
    page = win.pages["Settings"]
    assert isinstance(page, SettingsPage)
    cells = [page.hw.item(r, c).text() for r in range(page.hw.rowCount()) for c in range(page.hw.columnCount())]
    assert len(cells) == 15 and [c for c in cells if not c.startswith("§")] == []
    assert {"§Stage 1", "§Stage 2", "§Stage 3", "§Stage 4"} <= set(cells)
