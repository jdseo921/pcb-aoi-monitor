"""REQ-USR-001 (role check) and the audit wiring of REQ-LOG-004 (stage S16): every AppContext write checks the current
role and appends an audit entry, with no screen involved; so does what only an Engineer does without writing, minus
the entry (re-evaluating a result, since S28a)."""

from __future__ import annotations

import inspect
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.config import Settings, default_workspace
from aoi.core import crypto
from aoi.core.labels import DefectBox
from aoi.core.recipe import Recipe
from aoi.core.sample_import import ImportFile, ImportReport
from aoi.core.services import REQUIRED_ROLE, ROLES, AppContext, CsvFile
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import role_text
from aoi.ui.pages.settings import SettingsPage
from tools.trainable import a_store, in_store, key_of, trainable


def _raising(report: ImportReport) -> ImportReport:
    """import_files reports the error that stopped it rather than raising it: raised here, as every other write's is."""
    if report.stopped is not None:
        raise report.stopped[1]
    return report


def calibration_samples(ctx: AppContext) -> list[str]:
    """The board model CAL's 100 samples, added through the database when missing, so that only the call under test is
    role-checked and audited."""
    have = [s["uuid"] for s in ctx.samples("CAL")]
    return have or [ctx.db.sample(ctx.db.add_sample("CAL", "images/CAL/board.png", "OK"))["uuid"] for _ in range(100)]


def calibration_set(ctx: AppContext) -> tuple[str, list[str]]:
    """The newest calibration set's UUID and images; none before one is made, as for a call refused by its role."""
    sets = ctx.calibration_sets("CAL")
    return (sets[0]["uuid"], sets[0]["sample_uuids"]) if sets else ("", [""])


def labelled_blind(ctx: AppContext) -> str:
    """The set's UUID, labelled blind where missing by the engineer and, past label_blind's image, the user acting."""
    uid, images = calibration_set(ctx)
    users = (ctx.db.user_uuid("engineer"), ctx.user_uuid)
    for n, image in enumerate(images if uid else []):
        for user in users[: 2 if n else 1]:
            if image not in ctx.db.blind_labels(uid, user):
                ctx.db.add_row("blind_labels", set_uuid=uid, sample_uuid=image, label="OK", labelled_by=user)
    return uid


def ready_to_freeze(ctx: AppContext) -> str:
    """TINY, with every Top OK and NG label checked and drawn, an agreed check, and its files in the store of Acme
    Electronics, stored through the database where missing, so that only the call under test is role-checked and
    audited."""
    in_store(ctx, "TINY", "Acme Electronics")
    who, labelled = str(ctx.db.user_uuid("engineer")), [s for s in ctx.samples("TINY") if s["label"] != "UNSURE"]
    for s in [s for s in labelled if s["checked_by"] is None]:  # TINY's samples are all Top
        ctx.db.add_check(s["label_uuid"], s["uuid"], who)
    if not ctx.labels_ready_to_freeze("TINY", "Top"):
        ctx.db.add_ok_check_draw("TINY", "Top", 0, 0, [s["uuid"] for s in labelled if s["label"] == "OK"], who)
    counts = {"images": 100, "ok_ng_agree": 100, "both_ng": 3, "type_agree": 3, "ok_ng_target": 98, "type_target": 90}
    if not ctx.agreement_checks("TINY"):  # who as both labellers, on a set of TINY's Top images, which decides Top
        images = json.dumps([s["uuid"] for s in labelled])
        cal = ctx.db.add_row("calibration_sets", board_model="TINY", sample_uuids=images, made_by=who)
        ctx.db.add_row("agreement_checks", set_uuid=cal, board_model="TINY", labeller_a=who, labeller_b=who, **counts,
                       agreed=1, run_by=who)  # fmt: skip
    return "TINY"


def frozen_for_lock(ctx: AppContext) -> str:
    """A frozen version of board model LOCK with 60 OK files, stored through the database where missing, so that only
    the lock under test is role-checked and audited; its files are no workspace image's, so no training meets them."""
    if found := ctx.db.datasets("LOCK"):
        return str(found[0]["uuid"])
    who, uid = str(ctx.db.user_uuid("engineer")), "00000000-0000-4000-8000-00000000000c"
    version = {"uuid": uid, "name": "DS-LOCK-R1-TOP-v1", "board_model": "LOCK", "revision": "R1", "view": "Top"}
    version |= {"version": 1, "customer": "Acme", "allowed_uses": ["own"], "agreement_check_uuid": uid}
    version |= {"manifest_path": "datasets/DS-LOCK-R1-TOP-v1/manifest.json", "manifest_sha256": "0" * 64}
    files = [{"path": f"images/LOCK/OK/{i}.png", "sha256": f"{i:064x}", "sample_uuid": uid, "label_uuid": uid,
              "label": "OK", "defect_type": None, "boxes": [], "labelled_by": who, "checked_by": who}
             for i in range(60)]  # fmt: skip
    ctx.db.add_dataset(version | {"frozen_by": who, "frozen_at": "2026-10-09T00:00:00+00:00"}, files)
    return uid


# every AppContext write: method -> (its audit action, a call that works on the trained workspace), in a runnable order


def validation_version(ctx: AppContext) -> str:
    """A frozen version of TINY whose locked validation set holds its last NG sample: the newest, else a new one."""
    for d in ctx.db.datasets("TINY"):
        split = ctx.db.validation_split(d["uuid"])
        if split and split["validation"]:
            return str(d["uuid"])
    return trainable(ctx, "TINY", held=[ctx.samples("TINY", "NG")[-1]["uuid"]])


WRITES: dict[str, tuple[str, Callable[[AppContext, Path, Path], Any]]] = {
    "ensure_board_model": ("board_model.create", lambda ctx, data, tmp: ctx.ensure_board_model("NEW")),
    "import_samples": (
        "sample.import",
        lambda ctx, data, tmp: ctx.import_samples("TINY", [str(data / "golden.png")], "OK"),
    ),
    "import_files": (
        "sample.import",
        lambda ctx, data, tmp: _raising(
            ctx.import_files("TINY", [ImportFile(str(data / "test" / "ok" / "ok_000.png"), "OK")])
        ),
    ),
    "set_reference": (
        "board_model.reference",
        lambda ctx, data, tmp: ctx.set_reference("TINY", ctx.samples("TINY", "OK")[1]["id"]),
    ),
    "set_scale": ("board_model.scale", lambda ctx, data, tmp: ctx.set_scale("TINY", 476.0, 10.0)),  # S29
    "update_sample": (
        "sample.update",
        lambda ctx, data, tmp: ctx.update_sample(ctx.samples("TINY", "OK")[0]["id"], "NG", "Scratch"),
    ),
    "delete_sample": ("sample.delete", lambda ctx, data, tmp: ctx.delete_sample(ctx.samples("TINY", "NG")[0]["id"])),
    "set_label": ("label.set", lambda ctx, data, tmp: ctx.set_label(ctx.samples("TINY", "OK")[-1]["uuid"], "UNSURE")),
    "set_boxes": (
        "label.set",
        lambda ctx, data, tmp: ctx.set_boxes(ctx.samples("TINY", "NG")[-1]["uuid"], [DefectBox(0, 0, 4, 4, "Scratch")]),
    ),
    "check_label": (  # an image the fixture's Engineer imported: the Admin acting here labelled golden.png above
        "label.check",
        lambda ctx, data, tmp: ctx.check_label(ctx.samples("TINY", "OK")[1]["uuid"]),
    ),
    "draw_ok_checks": ("label.draw", lambda ctx, data, tmp: ctx.draw_ok_checks("TINY", "Top", seed=1)),
    "make_calibration_set": (
        "calibration.make",
        lambda ctx, data, tmp: ctx.make_calibration_set("CAL", calibration_samples(ctx)),
    ),
    "label_blind": (
        "label.blind",
        lambda ctx, data, tmp: ctx.label_blind(calibration_set(ctx)[0], calibration_set(ctx)[1][0], "OK"),
    ),
    "run_agreement_check": (
        "agreement.check",
        lambda ctx, data, tmp: ctx.run_agreement_check(
            labelled_blind(ctx), str(ctx.user_uuid), str(ctx.db.user_uuid("engineer"))
        ),
    ),
    "freeze_dataset": (
        "dataset.freeze",
        lambda ctx, data, tmp: ctx.freeze_dataset(ready_to_freeze(ctx), "Top", "R1", "Acme Electronics"),
    ),
    "lock_validation_set": ("dataset.lock", lambda ctx, data, tmp: ctx.lock_validation_set(frozen_for_lock(ctx), 1)),
    "create_store": ("store.create", lambda ctx, data, tmp: ctx.create_store("Beta Boards")),  # S38, REQ-TRN-017
    "restore_store_key": (
        "store.restore",
        lambda ctx, data, tmp: ctx.restore_store_key(uid := a_store(ctx, "Gamma"), crypto.sheet(key_of(ctx, uid))),
    ),
    "move_in": ("store.move_in", lambda ctx, data, tmp: ctx.move_in("TINY", a_store(ctx, "Acme Electronics"))),
    "shred_store": ("store.shred", lambda ctx, data, tmp: ctx.shred_store(a_store(ctx, "Delta"))),
    # the version TINY was trained from (tests/conftest.py), so the call under test writes the only rows
    "train": ("model.train", lambda ctx, data, tmp: ctx.train(ctx.training_version("TINY")["uuid"], 1, 32)),
    # the version trained above, which installed inactive (REQ-TRN-010, S43)
    "activate_model": ("model.activate", lambda ctx, data, tmp: ctx.activate_model(ctx.models("TINY")[0]["id"])),
    # back to the version the activation above replaced, with its Golden board (REQ-TRN-010, S42)
    "rollback_model": ("model.rollback", lambda ctx, data, tmp: ctx.rollback_model("TINY")),
    "save_recipe": ("recipe.save", lambda ctx, data, tmp: ctx.save_recipe(Recipe(board_model="TINY"))),
    "batch_test": ("test.run", lambda ctx, data, tmp: ctx.batch_test("TINY", str(data / "test" / "ng"))),
    # a version of TINY with a locked validation set (S44), made once: a write table call changes nothing else
    "test_dataset": ("test.run", lambda ctx, data, tmp: ctx.test_dataset(validation_version(ctx))),
    "export_model": (
        "export.model",
        lambda ctx, data, tmp: ctx.export_model(ctx.models("TINY")[0]["id"], tmp / "m.pt"),
    ),
    "export_overlays": (
        "export.overlays",
        lambda ctx, data, tmp: ctx.export_overlays(ctx.inspections(), tmp / "overlays"),
    ),
    "export_csv": ("export.csv", lambda ctx, data, tmp: ctx.export_csv(tmp / "rows.csv", [{"a": 1}])),
    "export_report": (
        "export.report",
        lambda ctx, data, tmp: ctx.export_report(tmp / "report.pdf", b"%PDF-1.4", "TINY", None, None),
    ),
    "export_csv_files": (
        "export.csv",
        lambda ctx, data, tmp: ctx.export_csv_files([CsvFile(tmp / "a.csv", [{"a": 1}]), CsvFile(tmp / "b.csv", [])]),
    ),
    "export_board_image": (
        "export.image",
        lambda ctx, data, tmp: ctx.export_board_image(
            ctx.inspect_file("TINY", str(data / "golden.png"), save=False), "TINY", None, "golden.png", tmp / "b.png"
        ),
    ),
    "archive_old": ("inspection.archive", lambda ctx, data, tmp: ctx.archive_old(-1)),
    "add_user": ("user.change", lambda ctx, data, tmp: ctx.add_user("kim", "Engineer")),
    "save_settings": ("settings.change", lambda ctx, data, tmp: ctx.save_settings({"default_epochs": 7})),
}
# what only an Engineer does that writes no audit entry itself: re-evaluating a result (REQ-CMP-005, since S28a), and
# starting a training run, whose job writes model.train once it ends (REQ-TRN-008, S40)
CHECKED_READS: dict[str, Callable[[AppContext, Path, Path], Any]] = {
    "re_evaluate": lambda ctx, data, tmp: ctx.re_evaluate("a-result-uuid", Recipe(board_model="TINY")),
    "start_training": lambda ctx, data, tmp: ctx.start_training(ctx.training_version("TINY")["uuid"], 5, 32).wait(60),
}
# every public AppContext call that is not role-checked: reads, what an Operator does, and the lifecycle
UNCHECKED = {
    "alarm", "alarms", "audit", "audit_entries", "report_error", "close", "set_user", "load_model", "recipe",
    "inspector", "inspect", "inspect_file", "load_image", "log_result", "board_models", "reference_image", "samples",
    "sample_path", "models", "model", "active_model", "recipe_history", "inspections", "defects_for", "checks_for",
    "checks_for_many", "inspection_result", "inspection", "judged_reference", "users", "board_status", "start_user",
    "golden_board_unreadable", "engine_is_current", "calibrated_threshold", "calibration_of", "scale", "label_history",
    "boxes", "box_history", "unsure_samples", "label_check_status", "labels_ready_to_freeze", "calibration_sets",
    "agreement_checks", "propose_calibration_set", "blind_labelled", "datasets", "dataset_items", "verify_dataset",
    "validation_split", "stores", "store_of", "store_contents", "training_version", "freeze_gate",
    "dataset_counts", "previous_model", "model_card", "card_files", "card_text", "last_board",
    "recipe_revisions",
}  # fmt: skip
CALLS = {**{name: call for name, (_, call) in WRITES.items()}, **CHECKED_READS}
# The lowest role allowed each call, copied from the write table of docs/ARCHITECTURE.md §5 and REQ-CMP-005, never read
# from the decorators under test (#181): built from REQUIRED_ROLE, a lowered @requires refused fewer roles and passed.
EXPECTED_ROLE = {name: "Engineer" for name in CALLS} | {"add_user": "Admin", "save_settings": "Admin"}
EXPECTED_ROLE |= {"create_store": "Admin", "restore_store_key": "Admin", "move_in": "Admin", "shred_store": "Admin"}
EXPECTED_ROLE["export_board_image"] = "Operator"  # Save Image… (F9): every role keeps it, audited (#241, REQ-INSP-005)
REFUSED = [(name, role) for name in CALLS for role in ROLES[: ROLES.index(EXPECTED_ROLE[name])]]


def test_req_usr_001_every_appcontext_call_is_classified() -> None:
    public = {name for name, _ in inspect.getmembers(AppContext, inspect.isfunction) if not name.startswith("_")}
    assert public == UNCHECKED | set(CALLS), public ^ (UNCHECKED | set(CALLS))
    assert REQUIRED_ROLE == EXPECTED_ROLE  # each @requires names the §5 role (re_evaluate: Engineer, REQ-CMP-005)


@pytest.mark.parametrize(("method", "role"), REFUSED, ids=[f"{m}-{r}" for m, r in REFUSED])
def test_req_usr_001_lower_role_is_refused(
    method: str, role: str, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    trained_ctx.set_user(role.lower())  # the seeded user of that role
    before = trained_ctx.audit_entries()  # the fixture's own imports and training
    with pytest.raises(AoiError) as refused:
        CALLS[method](trained_ctx, synthetic_dataset, tmp_path)
    allowed = " or ".join(ROLES[ROLES.index(EXPECTED_ROLE[method]) :])
    assert refused.value.code == "AOI-USR-001" and refused.value.what.endswith(f"needs the {allowed} role.")
    assert trained_ctx.audit_entries() == before  # refused before anything was written


def test_req_log_004_writes_are_audited(trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path) -> None:
    ctx = trained_ctx
    ctx.set_user("admin")
    earlier = {e["uuid"] for e in ctx.audit_entries()}  # the fixture's own imports and training
    ctx.inspect_file("TINY", ctx.samples("TINY", "OK")[0]["path"])  # an Operator's record: not audited, exportable
    assert {e["uuid"] for e in ctx.audit_entries()} == earlier
    for name, (action, call) in WRITES.items():
        call(ctx, synthetic_dataset, tmp_path)
        entry = ctx.audit_entries(action=action)[0]
        assert entry["role"] == "Admin" and entry["user_uuid"] == ctx.user_uuid == ctx.db.user_uuid("admin"), name
    by_action = {e["action"]: e for e in ctx.audit_entries() if e["uuid"] not in earlier}
    # Creating a board model also stores its default recipe as revision 1, the system's entry, not a user's (S25a-2).
    assert set(by_action) == {action for action, _ in WRITES.values()} | {"recipe.default"}
    assert (by_action["recipe.default"]["user_uuid"], by_action["recipe.default"]["role"]) == (None, None)
    versions = [m["version"] for m in ctx.models("TINY")]  # newest first: the version trained above, then v1.0
    assert by_action["model.train"]["before"] == {"active_version": versions[1]}  # it installs inactive (S43)
    assert by_action["model.train"]["after"]["activated"] is False
    assert by_action["model.train"]["after"]["version"] == versions[0]
    switched = [by_action[a] for a in ("model.activate", "model.rollback")]  # to the new version, then back
    assert [(e["before"]["active_version"], e["after"]["active_version"]) for e in switched] == [
        (versions[1], versions[0]),
        (versions[0], versions[1]),
    ]
    assert switched[0]["after"]["reference"] == switched[1]["before"]["reference"] != switched[1]["after"]["reference"]
    assert by_action["sample.update"]["before"] == {"label": "OK", "defect_type": None}
    assert by_action["sample.update"]["after"] == {"label": "NG", "defect_type": "Scratch"}
    assert not Path(by_action["board_model.reference"]["after"]["reference"]).is_absolute()
    assert by_action["user.change"]["before"] is None and by_action["user.change"]["after"]["role"] == "Engineer"
    assert by_action["settings.change"]["after"] == {"default_epochs": 7} and ctx.settings.default_epochs == 7
    assert by_action["inspection.archive"]["after"]["archived"] == 1 and by_action["export.csv"]["after"]["rows"] == 1
    assert by_action["recipe.save"]["before"] == Recipe(board_model="TINY").to_dict()  # revision 1, the default
    assert by_action["test.run"]["after"]["model_version"] == versions[1]  # the test ran after the roll back to it


def test_req_usr_001_the_current_user_is_held_with_uuid_name_and_role(ctx: AppContext) -> None:
    assert (ctx.user, ctx.role, ctx.user_uuid) == ("engineer", "Engineer", ctx.db.user_uuid("engineer"))
    ctx.set_user("operator")
    assert ctx.role == "Operator" and ctx.user_uuid == ctx.db.user_uuid("operator")
    ctx.set_user("admin")
    ctx.add_user("operator", "Engineer")
    ctx.set_user("operator")
    assert ctx.role == "Engineer"  # the role comes from the users table, never from the caller (#197)
    with pytest.raises(AoiError) as unknown:
        ctx.set_user("nobody")  # a name with no users row has no role to sign in with
    assert unknown.value.code == "AOI-USR-003" and (ctx.user, ctx.role) == ("operator", "Engineer")
    ctx.set_user("admin")
    ctx.add_user("kim", "Admin")
    ctx.add_user("admin", "Operator")  # the signed-in Admin gives up the role: the next check reads the stored one
    assert (ctx.user, ctx.role) == ("admin", "Operator")
    with pytest.raises(AoiError) as refused:
        ctx.save_settings({"default_epochs": 9})
    assert refused.value.code == "AOI-USR-001" and ctx.settings.default_epochs != 9


def test_req_log_004_settings_whose_entry_cannot_be_written_stay_as_they_were(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Settings save whose audit entry cannot be written (the disk full, the database held) leaves settings.json and
    the running app as they were, as every other write does (#178); before, the change stayed with no entry."""
    ctx.set_user("admin")
    epochs = ctx.settings.default_epochs

    def full(*a: object, **k: object) -> None:
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(ctx.db, "add_audit", full)
    with pytest.raises(sqlite3.OperationalError):
        ctx.save_settings({"default_epochs": epochs + 1})
    assert ctx.settings.default_epochs == epochs and Settings.load().default_epochs == epochs


def test_req_usr_001_the_last_admin_keeps_the_admin_role(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """Taking the Admin role from the last Admin is refused with AOI-USR-002 before anything is written or audited
    (#170): no user could open Settings again. With a second Admin it goes through. Add / Change User offers an existing
    user's own role first, so OK on the offer changes nothing, and a change of the signed-in user's role reaches the
    window. Before, the offer was Operator, the change was stored, and the session went on as Admin."""
    win = MainWindow(ctx)  # an empty workspace opens as Admin, signed in as "admin"
    qtbot.addWidget(win)
    with pytest.raises(AoiError) as refused:
        ctx.add_user("admin", "Operator")
    assert refused.value.code == "AOI-USR-002" and not ctx.audit_entries(action="user.change")
    offered: list[str] = []
    pick: list[str] = []  # the role chosen in the dialog; none: OK on the one it offers

    def get_item(*args: Any) -> tuple[str, bool]:
        offered.append(args[3][args[4]])
        return (role_text(pick.pop()) if pick else offered[-1]), True

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a: ("admin", True)))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(get_item))
    page = cast(SettingsPage, win.pages["Settings"])
    assert win.navigate("Settings")
    page.add_user()
    pick.append("Engineer")
    page.add_user()
    assert offered == [role_text("Admin")] * 2 and [title for title, _ in dialogs] == ["AOI-USR-002 Last Admin"]
    assert {u["name"]: u["role"] for u in ctx.users()}["admin"] == "Admin" and ctx.role == "Admin"
    ctx.add_user("engineer", "Admin")  # a second Admin
    pick.append("Engineer")
    page.add_user()
    assert {u["name"]: u["role"] for u in ctx.users()}["admin"] == "Engineer"
    assert ctx.role == "Engineer" and win.stack.currentWidget() is win.pages["Home"]  # Settings is the Admin's


def test_req_usr_001_saving_settings_needs_the_admin_role_and_is_audited(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """#197: the Settings page saved settings.json through `ctx.settings` with no role check and no audit entry, so
    an Operator's save went through and a one-day log retention, which archives records at every start, had no trace.
    It saves through `AppContext.save_settings` now: an Operator is refused with AOI-USR-001 and nothing changes, on
    disk or in the running app; an Admin's save writes one `settings.change` entry with the values before and after."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: QMessageBox.StandardButton.Ok))
    win = MainWindow(ctx)  # an empty workspace opens as Admin
    qtbot.addWidget(win)
    page = cast(SettingsPage, win.pages["Settings"])
    f = default_workspace() / "settings.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text('{"device": "cpu"}', encoding="utf-8")  # the retention not in the file: the default is in effect
    on_disk = f.read_bytes()

    def running() -> tuple[str, int]:
        return ctx.settings.device, ctx.settings.log_retention_days

    before = running()
    win.set_user("operator")
    page.device.setCurrentText("cuda")
    page.ret.setValue(1)
    page.save()
    assert [title for title, _ in dialogs] == ["AOI-USR-001 Not allowed for this role"]
    assert dialogs[0][1].startswith("Changing settings needs the Admin role.")
    assert f.read_bytes() == on_disk and running() == before
    assert not ctx.audit_entries(action="settings.change")
    win.set_user("admin")
    page.save()
    (entry,) = ctx.audit_entries(action="settings.change")
    assert (entry["role"], entry["user_uuid"], entry["object_type"]) == ("Admin", ctx.db.user_uuid("admin"), "settings")
    assert (entry["before"]["device"], entry["before"]["log_retention_days"]) == before
    assert (entry["after"]["device"], entry["after"]["log_retention_days"]) == ("cuda", 1)
    from_file = (entry["before"]["workspace"], entry["after"]["workspace"])  # a start would have opened the default
    assert from_file == (str(default_workspace()), ctx.settings.workspace)
    saved = Settings.load()
    assert (saved.device, saved.log_retention_days) == running() == ("cuda", 1)


def _restart(qtbot: QtBot, workspace: Settings) -> tuple[AppContext, MainWindow]:
    """Start again on `workspace`, as main.py does: a new AppContext, then the window."""
    again = AppContext(workspace)
    at_init = (again.user, again.role)
    win = MainWindow(again)
    qtbot.addWidget(win)
    stored = {u["name"]: u["role"] for u in again.users()}
    assert at_init[1] == stored[at_init[0]], at_init  # the context never holds a role the table does not
    return again, win


def test_req_usr_001_a_start_signs_in_with_the_role_the_users_table_holds(qtbot: QtBot, workspace: Settings) -> None:
    """#197: the start-up user's role was a literal in the code, Admin for 'admin' on a workspace with no board model
    and Operator for 'operator' otherwise, so a demoted 'admin' started as Admin, could change users and was audited
    as Admin under the UUID of a user the table holds as Operator, and a promoted 'operator' started as Operator.
    A start now reads the role from the users table: setting up, the first stored Admin; otherwise 'operator'."""
    first = AppContext(workspace)
    first.set_user("admin")
    first.add_user("kim", "Admin")
    first.add_user("admin", "Operator")  # kim is still an Admin, so the last-Admin guard (AOI-USR-002) allows it
    first.close()
    ctx, win = _restart(qtbot, workspace)  # no board model yet: the station is being set up
    stored = {u["name"]: u["role"] for u in ctx.users()}
    assert ctx.role == stored[ctx.user]  # before: 'admin' started as Admin, stored as Operator
    assert (ctx.user, ctx.role) == ("kim", "Admin")  # the first stored Admin
    assert win.user_label.text() == f"{ctx.user}  ·  {role_text(ctx.role)}"
    ctx.add_user("eve", "Engineer")
    entry = ctx.audit_entries(action="user.change")[0]
    by_uuid = {u["uuid"]: u["role"] for u in ctx.users()}
    assert entry["role"] == by_uuid[entry["user_uuid"]] == "Admin"


def test_req_usr_001_a_promoted_operator_starts_with_the_stored_role(qtbot: QtBot, workspace: Settings) -> None:
    """#197, the reverse: 'operator', promoted to Admin, started as Operator once a board model existed."""
    first = AppContext(workspace)
    first.set_user("admin")
    first.ensure_board_model("B1")
    first.add_user("operator", "Admin")
    first.close()
    ctx, win = _restart(qtbot, workspace)  # a board model exists: the station starts with 'operator'
    assert (ctx.user, ctx.role) == ("operator", "Admin")
    assert win.user_label.text() == f"operator  ·  {role_text('Admin')}"
    assert win.navigate("Settings")  # the page follows the stored role too
