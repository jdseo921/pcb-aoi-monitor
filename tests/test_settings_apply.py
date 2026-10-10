"""A value saved on the Settings page reaches the running app at once, everywhere it shows (#201).

The save docstring and ARCHITECTURE.md say the running app follows every saved value but the workspace. The AI device
was resolved once at start-up and the Logs & Export archive button formatted its day count once at start-up, so both
kept the start-up value after a save that said "Saved.".
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
import torch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGraphicsSimpleTextItem, QLabel, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import Settings
from aoi.core import anomaly, services
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui import theme
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.logs import LogsPage
from aoi.ui.pages.settings import SettingsPage
from aoi.ui.pages.training import TrainingPage
from aoi.ui.workers import Worker
from tests.test_req_done_in_v01 import BOARD, _inspect_one, _window
from tools.trainable import trainable


def _probed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The devices a run times its first training step and map on (anomaly.probe, REQ-TRN-008), recorded and timed
    at nothing: the container has no GPU."""
    devices: list[str] = []

    def probe(image: anomaly.Prepared, cfg: anomaly.TrainConfig) -> tuple[float, float]:
        devices.append(cfg.device)
        return 0.0, 0.0

    monkeypatch.setattr(anomaly, "probe", probe)
    return devices


def _shown_device(win: MainWindow) -> list[str]:
    """The device the Training page shows, read from its labels as the user sees them."""
    win.navigate("Training")
    return [w.text() for w in win.pages["Training"].findChildren(QLabel) if w.text() in ("CPU", "CUDA")]


@pytest.mark.parametrize(
    ("at_start", "saved", "before", "after"), [("auto", "cpu", "cuda", "cpu"), ("cpu", "cuda", "cpu", "cuda")]
)
def test_req_set_002_a_saved_ai_device_is_used_at_once(
    qtbot: QtBot,
    trained_ctx: AppContext,
    monkeypatch: pytest.MonkeyPatch,
    at_start: str,
    saved: str,
    before: str,
    after: str,
) -> None:
    """#201: on a GPU station, the device saved on Settings was written and reported "Saved.", but `ctx.device` was
    resolved only at start-up and the weights stayed cached, so training and inference kept the old device, and the
    Training page showed it, until a restart. Saving now resolves the device again, drops the cached weights and the
    Training page shows the device in use."""
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)  # a GPU station
    loaded_on: list[str] = []
    real_load = anomaly.AnomalyModel.load

    def load(path: str | Path, device: str = "cpu") -> anomaly.AnomalyModel:
        loaded_on.append(device)
        return real_load(path, "cpu")  # the container has no GPU: the weights load on the CPU whatever was asked

    monkeypatch.setattr(anomaly.AnomalyModel, "load", staticmethod(load))
    trained_on: list[str] = []

    def train(*args: Any, **kwargs: Any) -> anomaly.AnomalyModel:
        trained_on.append(args[2].device)  # TrainConfig, the third argument
        raise RuntimeError("stopped by the test once the device is known")

    monkeypatch.setattr(anomaly, "train", train)
    probed_on = _probed(monkeypatch)
    said: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda _p, _t, text: said.append(text)))
    trained_ctx.close()
    ctx = AppContext(Settings(workspace=trained_ctx.settings.workspace, device=at_start))  # the start, on `at_start`
    win = _window(qtbot, ctx, "Admin")
    assert ctx.device == before and _shown_device(win) == [before.upper()]
    ctx.load_model(BOARD)
    page = cast(SettingsPage, win.pages["Settings"])
    win.navigate("Settings")
    page.device.setCurrentText(saved)
    page.save()
    assert said == ["Saved."]
    assert ctx.settings.device == saved
    assert ctx.device == after, f"device saved as {saved} but the app still uses {ctx.device}"
    ctx.load_model(BOARD)
    assert loaded_on == [before, after]  # the weights cached on the old device were loaded again
    with pytest.raises(RuntimeError, match="stopped by the test"):
        ctx.train(trainable(ctx, BOARD), epochs=5, image_size=64)
    assert trained_on == probed_on == [after]
    assert _shown_device(win) == [after.upper()]


def test_req_set_002_a_load_running_during_the_save_does_not_keep_the_old_device(
    trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#201 review: a model load already running on the pool thread (the first board of a run, or AI Model Test) when
    the device is saved must not leave weights on the old device in the cache, or every later board uses them until a
    restart. The load finishes after the save, so a cache that compared only the version kept CUDA weights."""
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)  # a GPU station
    loaded_on: list[str] = []
    entered, release = threading.Event(), threading.Event()
    real_load = anomaly.AnomalyModel.load

    def load(path: str | Path, device: str = "cpu") -> anomaly.AnomalyModel:
        loaded_on.append(device)
        if len(loaded_on) == 1:  # the first load is still running when the Admin saves
            entered.set()
            assert release.wait(30)
        return real_load(path, "cpu")  # the container has no GPU

    monkeypatch.setattr(anomaly.AnomalyModel, "load", staticmethod(load))
    trained_ctx.close()
    ctx = AppContext(Settings(workspace=trained_ctx.settings.workspace, device="auto"))
    try:
        assert ctx.device == "cuda"
        running = threading.Thread(target=ctx.load_model, args=(BOARD,))
        running.start()
        assert entered.wait(30)
        ctx.set_user("admin")
        ctx.save_settings({"device": "cpu"})
        release.set()
        running.join(30)
        assert ctx.device == "cpu"
        ctx.load_model(BOARD)
        ctx.load_model(BOARD)
        assert loaded_on == ["cuda", "cpu"], "the weights loaded on cuda during the save are used for every later board"
    finally:
        release.set()
        ctx.close()


def test_req_set_002_saved_training_defaults_reach_the_training_page(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#201 review: Default epochs and Default input size saved on Settings did not reach the Training page, whose boxes
    were filled once at start-up, so Start Training ran with the start-up values. The boxes now follow a change of the
    saved defaults; a value chosen for the next run stays while the defaults are unchanged. While a run goes on, the
    Device label keeps the run's device."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: QMessageBox.StandardButton.Ok))
    win = _window(qtbot, trained_ctx, "Admin")
    training = cast(TrainingPage, win.pages["Training"])
    win.navigate("Training")
    training.epochs.setValue(77)  # a per-run choice
    win.navigate("Settings")
    win.navigate("Training")
    assert training.epochs.value() == 77  # the saved defaults did not change: the user's choice stays
    settings = cast(SettingsPage, win.pages["Settings"])
    win.navigate("Settings")
    settings.epochs.setValue(50)
    settings.input_size.setCurrentText("128")
    settings.save()
    win.navigate("Training")
    assert (training.epochs.value(), training.input_size.currentText()) == (50, "128")
    training.worker = cast(Worker, object())  # a run in progress, on the device it started with
    shown = training.device_label.text()
    win.navigate("Settings")
    settings.device.setCurrentText("cuda" if shown == "CPU" else "cpu")
    settings.save()
    win.navigate("Training")
    assert training.device_label.text() == shown
    training.worker = None


def test_req_set_002_a_run_keeps_the_device_it_started_with(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#201 review: a run read the device only when it built its TrainConfig, after loading and aligning its samples
    (minutes on a real dataset), so a device saved in that time changed the run's device while the Training page kept
    showing the one it started with. The run now reads the device once, before it loads anything."""
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)  # a GPU station
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: QMessageBox.StandardButton.Ok))
    aligning, release = threading.Event(), threading.Event()
    real_align = services.registration

    def align(*args: Any) -> Any:
        if not aligning.is_set():  # the run is still aligning its samples when the Admin saves
            aligning.set()
            assert release.wait(30)
        return real_align(*args)

    monkeypatch.setattr(services, "registration", align)
    trained_on: list[str] = []

    def train(ok: Any, ng: Any, cfg: anomaly.TrainConfig, progress: Any, should_stop: Callable[[], bool]) -> None:
        trained_on.append(cfg.device)
        while not should_stop():  # the run goes on until Stop
            time.sleep(0.01)

    monkeypatch.setattr(anomaly, "train", train)
    probed_on = _probed(monkeypatch)
    trained_ctx.close()
    ctx = AppContext(Settings(workspace=trained_ctx.settings.workspace, device="auto"))
    win = _window(qtbot, ctx, "Admin")
    training, settings = cast(TrainingPage, win.pages["Training"]), cast(SettingsPage, win.pages["Settings"])
    try:
        assert _shown_device(win) == ["CUDA"]
        training.btn_train.click()
        assert aligning.wait(30)
        win.navigate("Settings")
        settings.device.setCurrentText("cpu")
        settings.save()
        assert ctx.device == "cpu"
        release.set()
        qtbot.waitUntil(lambda: bool(trained_on))
        shown = (trained_on, probed_on, _shown_device(win))
        assert shown == (["cuda"], ["cuda"], ["CUDA"]), "the run trains on another device than shown"
    finally:
        release.set()
        training.stop()
        qtbot.waitUntil(lambda: training.worker is None)
    assert _shown_device(win) == ["CPU"]  # the run is over: the device in use


def test_req_log_003_the_archive_button_follows_the_saved_retention(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#201: the Logs & Export button formatted "Archive older than {days} days" once at start-up, while pressing it
    archived by the retention in effect, so after retention was saved as 7 it read 30 days and archived by 7. The button
    now reads the retention each time the page is shown and archives by the day count it shows: of a record 10 days old
    and one 2 days old, only the first (review: the test had no record, so the count was never checked)."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: QMessageBox.StandardButton.Ok))
    ctx = trained_ctx
    for sample in ctx.samples(BOARD, "OK")[:2]:
        ctx.inspect_file(BOARD, sample["path"])
    old, recent = (r["id"] for r in ctx.inspections())
    for record, days in ((old, 10), (recent, 2)):  # one record outside the new cutoff, one inside it
        then = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
        ctx.db.execute("UPDATE inspections SET time=? WHERE id=?", (then, record))
    win = _window(qtbot, ctx, "Admin")
    logs = cast(LogsPage, win.pages["Logs & Export"])
    assert logs.btn_arch.text() == "Archive older than 30 days"
    settings = cast(SettingsPage, win.pages["Settings"])
    win.navigate("Settings")
    settings.ret.setValue(7)
    settings.save()
    assert ctx.settings.log_retention_days == 7
    win.navigate("Logs & Export")
    assert logs.btn_arch.text() == "Archive older than 7 days"
    archived_with: list[int] = []
    real_archive = ctx.db.archive_old

    def archive_old(days: int) -> int:
        archived_with.append(days)
        return real_archive(days)

    monkeypatch.setattr(ctx.db, "archive_old", archive_old)
    logs.btn_arch.click()
    assert archived_with == [7]
    (entry,) = ctx.audit_entries(action="inspection.archive")
    assert entry["after"] == {"days": 7, "archived": 1}
    assert win.statusBar().currentMessage() == "Archived 1 record(s)"
    assert {r["id"]: r["archived"] for r in ctx.inspections(include_archived=True)} == {old: 1, recent: 0}


def test_req_set_008_the_presenter_theme_applies_at_once_saved_and_audited(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path
) -> None:
    """An Admin ticks Presenter theme on Settings: it is saved in settings.json, audited as `settings.change` with the
    value before, and applies at once, with no restart: the light stylesheet, Settings and 3D Profile out of the
    sidebar and Home shown, and what the pages drew before in the presenter theme's colours and sizes: the verdict
    banner of the board inspected before (48 pt, black on its fill), the text on its image (18 pt), the Home card
    numbers and Training's NG rows (their own tint, black, 18 pt). Exit presenter theme in the header, shown to an
    Admin, turns it off the same way, saved and audited, and puts back what the production theme drew."""
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Admin")
    win.resize(1920, 1080)
    inspection = _inspect_one(qtbot, win, next(synthetic_dataset.glob("test/ng/*missing_component*.png")))
    verdict = inspection.last.verdict
    training, home = cast(TrainingPage, win.pages["Training"]), win.pages["Home"]
    win.navigate("Training")  # its samples, NG rows tinted, drawn before the switch
    settings = cast(SettingsPage, win.pages["Settings"])
    win.navigate("Settings")
    assert not settings.presenter.isChecked() and not win.exit_presenter.isVisible()

    def drawn() -> dict[str, object]:
        """What the pages drew, read as a user sees it."""
        labels = [i for i in inspection.view.scene().items() if isinstance(i, QGraphicsSimpleTextItem) and i.text()]
        rows = [training.samples.item(r, 1) for r in range(training.samples.rowCount())]
        tinted = [it for it in rows if it.background().style() != Qt.BrushStyle.NoBrush]
        return {
            "banner": inspection.verdict.styleSheet(),
            "image": inspection.view.backgroundBrush().color().name(),
            "labels": {(i.font().pointSize(), i.brush().color().name()) for i in labels},
            "numbers": [w.text() for w in home.findChildren(QLabel) if theme.ACCENT_TEXT in w.text()],
            "rows": {
                (i.background().color().name(), i.foreground().color().name(), i.font().pointSize()) for i in tinted
            },
        }

    before = drawn()
    assert before["labels"] and before["rows"] == {(theme.NG_TINT, theme.ON_DARK, theme.FONT_PT)}, before
    settings.presenter.click()
    assert json.loads(Settings._file().read_text(encoding="utf-8"))["presenter_theme"] is True
    entry = ctx.audit_entries(action="settings.change")[0]
    assert (entry["before"], entry["after"]) == ({"presenter_theme": False}, {"presenter_theme": True})
    assert ctx.settings.presenter_theme and theme.presenter()
    assert cast(QApplication, QApplication.instance()).styleSheet() == theme.stylesheet()
    assert "QMainWindow, QWidget#page, QDialog { background: #fafafa;" in theme.stylesheet()
    assert (
        win.stack.currentWidget() is home and win._items["Settings"].isHidden() and win._items["3D Profile"].isHidden()
    )
    assert win.exit_presenter.isVisible()
    assert win.statusBar().currentMessage() == "Presenter theme on. An Admin turns it off with Exit presenter theme."
    shown = drawn()
    assert shown["banner"] == theme.verdict_style(verdict) and "font-size:48pt" in str(shown["banner"])
    assert shown["image"] == theme.BG_IMAGE and shown["labels"] == {(18, theme.TEXT)}, shown
    assert len(cast(list, shown["numbers"])) == 6 and all("26pt" in t for t in cast(list, shown["numbers"]))
    assert shown["rows"] == {(theme.NG_TINT, "#000000", 18)}, shown

    win.exit_presenter.click()
    assert json.loads(Settings._file().read_text(encoding="utf-8"))["presenter_theme"] is False
    entry = ctx.audit_entries(action="settings.change")[0]
    assert (entry["before"], entry["after"]) == ({"presenter_theme": True}, {"presenter_theme": False})
    assert not theme.presenter() and cast(QApplication, QApplication.instance()).styleSheet() == theme.QSS
    assert not win.exit_presenter.isVisible() and not win._items["Settings"].isHidden()
    assert drawn() == before


def test_req_set_008_a_restart_keeps_the_presenter_theme_and_only_an_admin_leaves_it(
    qtbot: QtBot, trained_ctx: AppContext
) -> None:
    """The presenter theme saved on, the app starts in it: the light stylesheet, Settings and 3D Profile hidden. An
    Operator or Engineer cannot leave it (Q49): the header has no Exit presenter theme for them, and the service layer
    refuses the setting below the Admin role (AOI-USR-001), so nothing changes; for an Admin the header has it.
    settings.json with a value that is not true or false for it is refused at start-up with AOI-SET-008."""
    ctx = trained_ctx
    ctx.set_user("admin")
    ctx.save_settings({"presenter_theme": True})  # as the Settings tick saves it
    assert Settings.load().presenter_theme is True
    win = _window(qtbot, ctx, "Operator")
    assert theme.presenter() and cast(QApplication, QApplication.instance()).styleSheet() == theme.stylesheet()
    assert win._items["Settings"].isHidden() and win._items["3D Profile"].isHidden()
    for role in ("operator", "engineer"):
        win.set_user(role)
        assert not win.exit_presenter.isVisible(), role
        with pytest.raises(AoiError) as e:
            ctx.save_settings({"presenter_theme": False})
        assert e.value.code == "AOI-USR-001", role
    assert ctx.settings.presenter_theme and theme.presenter() and Settings.load().presenter_theme is True
    win.set_user("admin")
    assert win.exit_presenter.isVisible()
    Settings._file().write_text('{"presenter_theme": "yes"}', encoding="utf-8")
    with pytest.raises(AoiError) as e:
        Settings.load()
    assert e.value.code == "AOI-SET-008" and 'presenter_theme is "yes"; it must be true or false' in e.value.what
