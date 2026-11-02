"""About from the header for every role (REQ-SET-011), the station's ID (migration 0028), and Settings' Support Bundle…
for an Admin (REQ-LOG-007)."""

from __future__ import annotations

import re
import uuid
import zipfile
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from aoi.config import APP_LABEL, Settings
from aoi.core.services import AppContext
from aoi.ui.about import AboutDialog
from aoi.ui.pages.settings import SettingsPage
from tests.test_req_done_in_v01 import BOARD, _button, _window


def test_req_set_011_the_station_has_one_id_kept_with_its_workspace(ctx: AppContext) -> None:
    station = ctx.db.station_id()
    assert station is not None and uuid.UUID(station).version == 4
    ctx.close()
    again = AppContext(Settings(workspace=ctx.settings.workspace, device="cpu"))
    try:
        assert again.db.station_id() == station and again.db.schema_number() >= 28
    finally:
        again.close()


@pytest.mark.parametrize("role", ["Operator", "Admin"])
def test_req_set_011_about_from_the_header_names_the_build_models_schema_and_station_and_copies_it(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    shown: list[AboutDialog] = []
    monkeypatch.setattr(AboutDialog, "exec", lambda self: shown.append(self) or 0)
    win = _window(qtbot, trained_ctx, role)
    qtbot.mouseClick(_button(win.header, "About"), Qt.MouseButton.LeftButton)
    about = shown[0]
    qtbot.addWidget(about)
    rows = dict(about.rows)
    model, rev = trained_ctx.active_model(BOARD), trained_ctx.db.latest_recipe(BOARD)
    assert model is not None and rev is not None
    assert rows["App"].endswith(APP_LABEL) and rows["Commit"] == "none (from source)" and rows["Board model"] == BOARD
    assert rows["AI model"] == model["version"] and rows["Recipe revision"] == str(rev[0])
    assert rows["Database schema"] == str(trained_ctx.db.schema_number()) and rows["Licence"] == "none yet"
    assert rows["Station ID"] == trained_ctx.db.station_id()
    _button(about, "Copy").click()
    copied = QGuiApplication.clipboard().text()
    assert copied == about.text() and re.search(r"^Station ID: [0-9a-f-]{36}$", copied, re.MULTILINE)


def test_req_log_007_settings_writes_the_support_bundle_where_the_admin_chooses(
    qtbot: QtBot, trained_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    win = _window(qtbot, trained_ctx, "Engineer")
    page = cast(SettingsPage, win.pages["Settings"])
    page.update_actions()
    assert not page.bundle.isEnabled()  # greyed below Admin, saying who may
    win.set_user("admin")
    page.update_actions()
    assert page.bundle.isEnabled()
    target = tmp_path / "usb" / "bundle.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    page.with_images.setChecked(True)
    qtbot.mouseClick(page.bundle, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(target.exists, timeout=30_000)
    names = zipfile.ZipFile(target).namelist()
    assert "station.csv" in names  # the overlays asked for are tests/test_support_bundle.py's
    assert trained_ctx.audit_entries(action="support.bundle")[0]["after"]["images"] is True
