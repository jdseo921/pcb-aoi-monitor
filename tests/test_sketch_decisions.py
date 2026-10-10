"""The sketch decisions of the S01-S10 audit (#144) built after it: black text on the green, red and blue fills (Q53,
#150), exports for an Admin alone (Q58, #151), the severity word and shape on a defect box's label (Q57, #152), the
map retention and the two image limits on Settings (Q56, #153) and Home's "Train AI model" card (Q6, #154)."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QGraphicsSimpleTextItem, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core.inspector import _severity_shape
from aoi.core.services import AppContext
from aoi.ui import theme
from aoi.ui.pages.settings import SettingsPage
from tests.test_req_done_in_v01 import _inspect_one, _window


def test_req_set_004_text_on_the_green_red_and_blue_fills_is_black() -> None:
    """Q53: black on OK green, NG red and accent blue, at 4.5:1 or more; the primary, Start, Stop and danger buttons
    take it from the stylesheet."""
    for fill in (theme.OK_COLOR, theme.NG_COLOR, theme.ACCENT):
        assert theme.on_color(fill) == theme.ON_FILL == "#000000", fill
    assert "QPushButton#danger { color: #000000;" in theme.stylesheet()


def test_req_usr_001_only_an_admin_sees_the_exports(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Q58: Export CSV and Export Image Overlays on Logs & Export, Export CSV, Export Report and Validation Report… on
    AI Model Test, and Export Manifest… on Training show for an Admin alone; the services refuse the rest (see
    test_roles_and_audit)."""
    win = _window(qtbot, trained_ctx)
    logs, test, training = (win.pages[p] for p in ("Logs & Export", "AI Model Test", "Training"))

    def exports() -> list[bool]:
        for name in ("Logs & Export", "AI Model Test", "Training"):
            win.navigate(name)
        buttons = (logs.btn_csv, logs.btn_img, test.btn_csv, test.btn_report, test.btn_validation)
        return [not b.isHidden() for b in (*buttons, training.versions.btn_export)]

    assert exports() == [False] * 6
    win.set_user("admin")
    assert exports() == [True] * 6


def test_req_insp_002_a_box_label_carries_the_severity_word_and_shape(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path
) -> None:
    """Q57: "1 Polarity Error ◆ Critical" on Inspection; the saved overlay draws the shape OpenCV's fonts lack."""
    win = _window(qtbot, trained_ctx)
    page = _inspect_one(qtbot, win, ng_board)
    labels = [i.text() for i in page.view.scene().items() if isinstance(i, QGraphicsSimpleTextItem) and i.text()]
    assert labels and page.last is not None
    for label in labels:
        assert any(f"{s} {w}" in label for w, s in theme.SEVERITY_SHAPES.items()), label
    shapes = {}
    for severity in ("Critical", "Major", "Minor"):
        img = np.zeros((40, 40, 3), np.uint8)
        assert _severity_shape(img, severity, (10, 30), 20, (255, 255, 255)) == 20
        shapes[severity] = int(cv2.countNonZero(img[..., 0]))
    assert shapes["Minor"] < shapes["Major"] and shapes["Critical"] < shapes["Major"] and min(shapes.values()) > 100


def test_req_insp_012_settings_shows_the_map_retention_and_the_image_limits(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q56: an Admin sets them on Settings, in Settings.check's bounds; the save writes settings.json and is audited."""
    win = _window(qtbot, trained_ctx, "Admin")
    win.navigate("Settings")
    page = win.pages["Settings"]
    assert isinstance(page, SettingsPage)
    s = trained_ctx.settings
    assert (page.map_ret.value(), page.max_mp.value(), page.max_mb.value()) == (
        s.map_retention_days_ok,
        s.max_image_megapixels,
        s.max_image_megabytes,
    )
    assert (page.map_ret.minimum(), page.max_mp.minimum(), page.max_mb.minimum()) == (0, 1, 1)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    page.map_ret.setValue(3)
    page.max_mp.setValue(40)
    page.max_mb.setValue(150)
    page.save()
    stored = json.loads(Settings._file().read_text(encoding="utf-8"))
    want = {"map_retention_days_ok": 3, "max_image_megapixels": 40, "max_image_megabytes": 150}
    assert {k: stored[k] for k in want} == want
    assert (s.map_retention_days_ok, s.max_image_megapixels, s.max_image_megabytes) == (3, 40, 150)
    after = trained_ctx.audit_entries(action="settings.change")[0]["after"]
    assert {k: after[k] for k in want} == want


def test_req_insp_016_home_card_2_reads_train_ai_model(qtbot: QtBot, trained_ctx: AppContext) -> None:
    """Q6: the Charter's words, not "Self-train"."""
    win = _window(qtbot, trained_ctx)
    home = win.pages["Home"]
    assert "Train AI model" in home.status_labels and "Self-train" not in home.status_labels
