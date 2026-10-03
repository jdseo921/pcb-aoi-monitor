"""REQ-USR-001 (role check) and the audit wiring of REQ-LOG-004 (stage S16): every AppContext write checks the current
role and appends an audit entry, with no screen involved; so does what only an Engineer does without writing, minus
the entry (re-evaluating a result, since S28a)."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtWidgets import QInputDialog
from pytestqt.qtbot import QtBot

from aoi.core.recipe import Recipe
from aoi.core.services import REQUIRED_ROLE, ROLES, AppContext
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import role_text
from aoi.ui.pages.settings import SettingsPage

# every AppContext write: method -> (its audit action, a call that works on the trained workspace), in a runnable order
WRITES: dict[str, tuple[str, Callable[[AppContext, Path, Path], Any]]] = {
    "ensure_board_model": ("board_model.create", lambda ctx, data, tmp: ctx.ensure_board_model("NEW")),
    "import_samples": (
        "sample.import",
        lambda ctx, data, tmp: ctx.import_samples("TINY", [str(data / "golden.png")], "OK"),
    ),
    "set_reference": (
        "board_model.reference",
        lambda ctx, data, tmp: ctx.set_reference("TINY", ctx.samples("TINY", "OK")[1]["id"]),
    ),
    "update_sample": (
        "sample.update",
        lambda ctx, data, tmp: ctx.update_sample(ctx.samples("TINY", "OK")[0]["id"], "NG", "Scratch"),
    ),
    "delete_sample": ("sample.delete", lambda ctx, data, tmp: ctx.delete_sample(ctx.samples("TINY", "NG")[0]["id"])),
    "train": ("model.train", lambda ctx, data, tmp: ctx.train("TINY", epochs=1, image_size=32)),
    "activate_model": ("model.activate", lambda ctx, data, tmp: ctx.activate_model(ctx.models("TINY")[-1]["id"])),
    "save_recipe": ("recipe.save", lambda ctx, data, tmp: ctx.save_recipe(Recipe(board_model="TINY"))),
    "batch_test": ("test.run", lambda ctx, data, tmp: ctx.batch_test("TINY", str(data / "test" / "ng"))),
    "export_model": (
        "export.model",
        lambda ctx, data, tmp: ctx.export_model(ctx.models("TINY")[0]["id"], tmp / "m.pt"),
    ),
    "export_overlays": (
        "export.overlays",
        lambda ctx, data, tmp: ctx.export_overlays(ctx.inspections(), tmp / "overlays"),
    ),
    "export_csv": ("export.csv", lambda ctx, data, tmp: ctx.export_csv(tmp / "rows.csv", [{"a": 1}])),
    "archive_old": ("inspection.archive", lambda ctx, data, tmp: ctx.archive_old(-1)),
    "add_user": ("user.change", lambda ctx, data, tmp: ctx.add_user("kim", "Engineer")),
}
# what only an Engineer does that writes nothing, so no audit entry: re-evaluating a result (REQ-CMP-005, since S28a)
CHECKED_READS: dict[str, Callable[[AppContext, Path, Path], Any]] = {
    "re_evaluate": lambda ctx, data, tmp: ctx.re_evaluate("a-result-uuid", Recipe(board_model="TINY")),
}
# every public AppContext call that is not role-checked: reads, what an Operator does, and the lifecycle
UNCHECKED = {
    "alarm", "alarms", "audit", "audit_entries", "report_error", "close", "set_user", "load_model", "recipe",
    "inspector", "inspect", "inspect_file", "load_image", "log_result", "board_models", "reference_image", "samples",
    "sample_path", "models", "model", "active_model", "recipe_history", "inspections", "defects_for", "checks_for",
    "checks_for_many", "inspection_result", "inspection", "judged_reference", "users", "board_status",
}  # fmt: skip
CALLS = {**{name: call for name, (_, call) in WRITES.items()}, **CHECKED_READS}
# The lowest role allowed each call, copied from the write table of docs/ARCHITECTURE.md §5 and REQ-CMP-005, never read
# from the decorators under test (#181): built from REQUIRED_ROLE, a lowered @requires refused fewer roles and passed.
EXPECTED_ROLE = {name: "Engineer" for name in CALLS} | {"add_user": "Admin"}
REFUSED = [(name, role) for name in CALLS for role in ROLES[: ROLES.index(EXPECTED_ROLE[name])]]


def test_req_usr_001_every_appcontext_call_is_classified() -> None:
    public = {name for name, _ in inspect.getmembers(AppContext, inspect.isfunction) if not name.startswith("_")}
    assert public == UNCHECKED | set(CALLS), public ^ (UNCHECKED | set(CALLS))
    assert REQUIRED_ROLE == EXPECTED_ROLE  # each @requires names the §5 role (re_evaluate: Engineer, REQ-CMP-005)


@pytest.mark.parametrize(("method", "role"), REFUSED, ids=[f"{m}-{r}" for m, r in REFUSED])
def test_req_usr_001_lower_role_is_refused(
    method: str, role: str, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    trained_ctx.set_user("someone", role)
    before = trained_ctx.audit_entries()  # the fixture's own imports and training
    with pytest.raises(AoiError) as refused:
        CALLS[method](trained_ctx, synthetic_dataset, tmp_path)
    allowed = " or ".join(ROLES[ROLES.index(EXPECTED_ROLE[method]) :])
    assert refused.value.code == "AOI-USR-001" and refused.value.what.endswith(f"needs the {allowed} role.")
    assert trained_ctx.audit_entries() == before  # refused before anything was written


def test_req_log_004_writes_are_audited(trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path) -> None:
    ctx = trained_ctx
    ctx.set_user("admin", "Admin")
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
    reference = by_action["board_model.reference"]["after"]["reference"]  # set before training; the Golden board (#178)
    assert by_action["model.train"]["before"] == {"active_version": versions[1], "reference": reference}
    assert by_action["model.train"]["after"]["version"] == versions[0]
    assert (by_action["model.activate"]["before"], by_action["model.activate"]["after"]) == (
        {"active_version": versions[0]},
        {"active_version": versions[1]},
    )  # a rollback
    assert by_action["sample.update"]["before"] == {"label": "OK", "defect_type": None}
    assert by_action["sample.update"]["after"] == {"label": "NG", "defect_type": "Scratch"}
    assert not Path(by_action["board_model.reference"]["after"]["reference"]).is_absolute()
    assert by_action["user.change"]["before"] is None and by_action["user.change"]["after"]["role"] == "Engineer"
    assert by_action["inspection.archive"]["after"]["archived"] == 1 and by_action["export.csv"]["after"]["rows"] == 1
    assert by_action["recipe.save"]["before"] == Recipe(board_model="TINY").to_dict()  # revision 1, the default
    assert by_action["test.run"]["after"]["model_version"] == versions[1]  # the test ran after the rollback


def test_req_usr_001_the_current_user_is_held_with_uuid_name_and_role(ctx: AppContext) -> None:
    assert (ctx.user, ctx.role, ctx.user_uuid) == ("engineer", "Engineer", ctx.db.user_uuid("engineer"))
    ctx.set_user("operator", "Operator")
    assert ctx.role == "Operator" and ctx.user_uuid == ctx.db.user_uuid("operator")
    ctx.set_user("nobody", "Admin")  # a picked name with no users row (G1 keeps the picker, ADR 0002)
    uid = ctx.audit("test.only", "x", None, None, None)
    (entry,) = ctx.audit_entries()
    assert ctx.user_uuid is None and entry["uuid"] == uid and entry["user_uuid"] is None


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
