"""#177 (REQ-USR-001, REQ-LOG-004): a background job acts as the user who started it. Switch User while training, an
AI model test, a folder import or an inspection runs changes who is signed in, not who the job's audit entries and
records name, and does not refuse the rest of the job. Each test holds the job at the step the issue names, switches
the user there, then lets it finish."""

from __future__ import annotations

import dataclasses
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtWidgets import QInputDialog
from pytestqt.qtbot import QtBot

from aoi.core import anomaly, services
from aoi.core.jobs import Job
from aoi.core.services import AppContext
from aoi.ui.pages.inspection import InspectionPage
from aoi.ui.pages.model_test import ModelTestPage
from aoi.ui.pages.training import TrainingPage
from tests.conftest import distinct_copies
from tests.test_req_done_in_v01 import BOARD, _window

Held = tuple[threading.Event, threading.Event]


def _hold(monkeypatch: pytest.MonkeyPatch, owner: object, name: str, call: int = 1) -> Held:
    """Replace `owner.name` so that its `call`-th call sets the first event, then waits for the second before it runs
    the real one: the test switches the user in between, while the job is at that step."""
    real: Callable[..., Any] = getattr(owner, name)
    reached, release = threading.Event(), threading.Event()
    calls = 0

    def held(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == call:
            reached.set()
            assert release.wait(30)
        return real(*args, **kwargs)

    monkeypatch.setattr(owner, name, held)
    return reached, release


def _who(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    """The role and user UUID an audit entry names."""
    return entry["role"], entry["user_uuid"]


def test_req_log_004_training_is_audited_as_the_engineer_who_started_it(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Engineer")
    active = cast(dict[str, Any], ctx.active_model(BOARD))["version"]
    reached, release = _hold(monkeypatch, anomaly, "train")
    page = cast(TrainingPage, win.pages["Training"])
    assert win.navigate("Training")
    page.epochs.setValue(1)
    page.input_size.setCurrentText("128")
    page.train()
    assert reached.wait(30)
    win.set_user("operator")  # the next person signs in while the run trains
    release.set()
    qtbot.waitUntil(lambda: page.worker is None, timeout=60000)
    entry = ctx.audit_entries(action="model.train")[0]
    assert _who(entry) == ("Engineer", ctx.db.user_uuid("engineer"))
    assert cast(dict[str, Any], ctx.active_model(BOARD))["version"] == entry["after"]["version"] != active
    assert dialogs == [] and ctx.role == "Operator"


def test_req_log_004_an_ai_model_test_is_audited_as_the_engineer_who_started_it(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Engineer")
    reached, release = _hold(monkeypatch, services, "list_images")  # after the role check, before the first board
    page = cast(ModelTestPage, win.pages["AI Model Test"])
    assert win.navigate("AI Model Test")
    page.folder = str(synthetic_dataset / "test")
    page.run()
    assert reached.wait(30)
    win.set_user("operator")
    release.set()
    qtbot.waitUntil(lambda: page.btn_run.isEnabled(), timeout=60000)
    (entry,) = ctx.audit_entries(action="test.run")
    assert _who(entry) == ("Engineer", ctx.db.user_uuid("engineer"))
    assert dialogs == []


def test_req_usr_001_a_folder_import_finishes_as_the_engineer_who_started_it(
    qtbot: QtBot,
    trained_ctx: AppContext,
    synthetic_dataset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dialogs: list[tuple[str, str]],
) -> None:
    """Before, the import called the role-checked import_samples once per file as whoever was signed in at that file:
    after a switch to an Operator the next file was refused with AOI-USR-001 and the import stopped part-way."""
    ctx = trained_ctx
    folder = tmp_path / "imp"
    (folder / "ok").mkdir(parents=True)
    for i, board in enumerate(distinct_copies(synthetic_dataset / "golden.png", tmp_path / "boards", 4)):
        shutil.copy(board, folder / "ok" / f"board_{i}.png")  # four images: one is imported once (Q31)
    win = _window(qtbot, ctx, "Engineer")
    before = len(ctx.samples(BOARD, "OK"))
    reached, release = _hold(monkeypatch, ctx, "import_samples", call=2)
    page = cast(TrainingPage, win.pages["Training"])
    assert win.navigate("Training")
    page.import_from(str(folder))
    page.sheet.btn_import.click()
    assert reached.wait(30)
    win.set_user("operator")  # the import goes on on its own; the Operator lands on Home
    release.set()
    qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    assert dialogs == [] and len(ctx.samples(BOARD, "OK")) == before + 4
    entries = ctx.audit_entries(action="sample.import")[:4]
    assert {_who(e) for e in entries} == {("Engineer", ctx.db.user_uuid("engineer"))}


def test_req_usr_001_a_board_is_recorded_under_the_operator_who_inspected_it(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Operator")
    reached, release = _hold(monkeypatch, ctx, "log_result")  # the board is judged; its record is not saved yet
    page = cast(InspectionPage, win.pages["Inspection"])
    assert win.navigate("Inspection")
    page._set_queue([Path(ctx.samples(BOARD, "OK")[0]["path"])])
    page.next_board()
    assert reached.wait(30)
    win.set_user("engineer")
    release.set()
    qtbot.waitUntil(lambda: page.worker is None and page.last is not None, timeout=30000)
    (record,) = ctx.inspections()
    assert record["operator"] == "operator" and dialogs == []


def test_req_usr_001_a_run_stops_at_switch_user_so_every_board_names_who_pressed_start(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """Before, a run chained its next board as whoever was signed in, so after a Switch User the rest of the queue was
    recorded under the new user, who pressed nothing. Now the run stops after the board in hand, which is recorded
    under the user who pressed Start; the new user presses Start to carry on, as themselves."""
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Operator")
    reached, release = _hold(monkeypatch, ctx, "log_result")  # the first board is judged; its record is not saved yet
    page = cast(InspectionPage, win.pages["Inspection"])
    assert win.navigate("Inspection")
    page._set_queue([Path(s["path"]) for s in ctx.samples(BOARD, "OK")[:3]])
    page.start_run()
    assert reached.wait(30)
    pick = staticmethod(lambda *a: (next(n for n in a[3] if n.startswith("engineer ")), True))
    monkeypatch.setattr(QInputDialog, "getItem", pick)
    win.switch_user()  # an Engineer signs in, on the Inspection page too, while the Operator's run is at board 1
    release.set()
    qtbot.waitUntil(lambda: page.worker is None and not page.running, timeout=30000)
    assert [r["operator"] for r in ctx.inspections()] == ["operator"]
    assert page.queue_pos == 0 and len(page.queue) == 3 and page.act_start.isEnabled() and ctx.user == "engineer"
    assert "engineer signed in" in win.statusBar().currentMessage() and dialogs == []
    page.start_run()  # the Engineer carries on with the queue
    qtbot.waitUntil(lambda: page.worker is None and not page.running, timeout=30000)
    assert [r["operator"] for r in ctx.inspections()] == ["engineer", "engineer", "operator"]  # newest first


def test_req_usr_001_a_queued_job_acts_as_the_user_who_submitted_it(ctx: AppContext, tmp_path: Path) -> None:
    """The user is taken when the job is submitted, not when a pool thread gets to it."""
    start = threading.Event()

    def export() -> int:
        assert start.wait(30)
        return ctx.export_csv(tmp_path / "rows.csv", [{"a": 1}])

    job = ctx.jobs.submit(Job("export", export))
    ctx.set_user("operator")
    start.set()
    assert job.wait(30) and job.error is None and job.result == 1
    (entry,) = ctx.audit_entries(action="export.csv")
    assert _who(entry) == ("Engineer", ctx.db.user_uuid("engineer"))
    assert (ctx.user, ctx.role, ctx.user_uuid) == ("operator", "Operator", ctx.db.user_uuid("operator"))


def test_req_usr_001_the_signed_in_user_is_one_value(ctx: AppContext) -> None:
    """Name, role and UUID change together: a pool thread never reads one user's UUID with another's role. CPython
    cannot be made to switch threads between two attribute stores on demand, so this checks the structure."""
    ctx.set_user("operator")
    actor = ctx.actor
    assert (actor.name, actor.role, actor.uuid) == ("operator", "Operator", ctx.db.user_uuid("operator"))
    with pytest.raises(AttributeError):
        setattr(ctx, "role", "Admin")  # noqa: B010  # only set_user changes the user, as a whole
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(actor, "role", "Admin")  # noqa: B010
    ctx.set_user("engineer")
    assert ctx.actor is not actor and actor.role == "Operator" and ctx.role == "Engineer"


def test_req_usr_001_a_switch_user_on_the_last_board_ends_the_run_as_usual(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """A Switch User during the last board of the queue: no board is left to stop before, so the run ends with "End of
    queue", never with a line asking the new user to press Start for boards that are not there."""
    ctx = trained_ctx
    win = _window(qtbot, ctx, "Operator")
    reached, release = _hold(monkeypatch, ctx, "log_result")
    page = cast(InspectionPage, win.pages["Inspection"])
    assert win.navigate("Inspection")
    page._set_queue([Path(ctx.samples(BOARD, "OK")[0]["path"])])
    page.start_run()
    assert reached.wait(30)
    pick = staticmethod(lambda *a: (next(n for n in a[3] if n.startswith("engineer ")), True))
    monkeypatch.setattr(QInputDialog, "getItem", pick)
    win.switch_user()
    release.set()
    qtbot.waitUntil(lambda: page.worker is None and not page.running, timeout=30000)
    assert [r["operator"] for r in ctx.inspections()] == ["operator"] and dialogs == []
    assert win.statusBar().currentMessage() == "End of queue"
