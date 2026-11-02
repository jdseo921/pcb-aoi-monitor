"""The workspace guard (REQ-SET-025): a folder on a network drive or in OneDrive is refused with AOI-SET-024, at start
and when picked on Settings, before a file is made in it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog

from aoi.config import Settings
from aoi.core.services import AppContext
from aoi.data import workspace_guard
from aoi.errors import AoiError
from aoi.ui import errors as ui_errors


@pytest.fixture
def one_drive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A OneDrive root as Windows names it in the environment, on any system."""
    root = tmp_path / "OneDrive - Acme"
    root.mkdir()
    for name in ("OneDrive", "OneDriveConsumer"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OneDriveCommercial", str(root))
    return root


def test_req_set_025_a_network_path_a_remote_drive_and_onedrive_are_refused_and_a_local_folder_is_not(
    tmp_path: Path, one_drive: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for unc in ("\\\\server\\share\\AOI", "//server/share/AOI", "\\\\?\\UNC\\server\\share\\AOI"):
        assert workspace_guard.refusal(unc) == workspace_guard.NETWORK, unc
    assert workspace_guard.refusal("\\\\?\\C:\\AOI_Workspace") is None  # C: is the PC's own drive
    assert workspace_guard.refusal(one_drive / "AOI_Workspace") == workspace_guard.ONE_DRIVE
    assert workspace_guard.refusal(tmp_path / "AOI_Workspace") is None
    asked: list[str] = []
    monkeypatch.setattr(
        workspace_guard, "drive_type", lambda anchor: asked.append(anchor) or workspace_guard.DRIVE_REMOTE
    )
    assert workspace_guard.refusal(tmp_path / "AOI_Workspace") == workspace_guard.NETWORK  # Z: mapped to a share
    assert set(asked) == {Path(tmp_path).anchor}
    monkeypatch.undo()


def test_req_set_025_a_link_into_onedrive_is_refused_and_an_empty_workspace_is_aoi_set_008_first(
    tmp_path: Path, one_drive: Path, ctx: AppContext
) -> None:
    link = tmp_path / "AOI"  # a junction or a link from a local folder into OneDrive, made by hand
    link.symlink_to(one_drive, target_is_directory=True)
    assert workspace_guard.refusal(link / "AOI_Workspace") == workspace_guard.ONE_DRIVE
    assert workspace_guard.refusal("//?/C:/AOI_Workspace") is None  # the long-path prefix with forward slashes
    ctx.set_user("admin")
    with pytest.raises(AoiError) as refused:
        ctx.save_settings({"workspace": ""})
    assert refused.value.code == "AOI-SET-008"


def test_req_set_025_a_start_on_onedrive_is_refused_before_a_file_is_made_and_offers_another_folder(
    tmp_path: Path, one_drive: Path, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    ws = one_drive / "AOI_Workspace"
    with pytest.raises(AoiError) as refused:
        AppContext(Settings(workspace=str(ws), device="cpu"))
    assert refused.value.code == "AOI-SET-024" and "OneDrive" in str(refused.value) and not ws.exists()
    Settings(workspace=str(ws), device="cpu").save()
    local = tmp_path / "local"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a: str(local)))
    ctx = ui_errors.open_workspace()  # the refusal is shown, then the folder picker; the folder picked opens
    try:
        assert [title for title, _ in dialogs] == ["AOI-SET-024 Workspace folder not allowed"]
        assert ctx is not None and ctx.settings.root == local and not ws.exists()
    finally:
        if ctx is not None:
            ctx.close()


def test_req_set_025_settings_refuses_a_onedrive_workspace_and_keeps_settings_json(
    ctx: AppContext, one_drive: Path
) -> None:
    ctx.set_user("admin")
    held = ctx.settings._file().read_bytes() if ctx.settings._file().exists() else None
    with pytest.raises(AoiError) as refused:
        ctx.save_settings({"workspace": str(one_drive / "AOI_Workspace")})
    assert refused.value.code == "AOI-SET-024"
    after = ctx.settings._file().read_bytes() if ctx.settings._file().exists() else None
    assert after == held and ctx.audit_entries(action="settings.change") == []
    assert json.loads(after or b"{}").get("workspace") != str(one_drive / "AOI_Workspace")
