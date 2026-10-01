"""REQ-LOG-004, audit part (S13): an append-only audit trail with before and after."""

from __future__ import annotations

import sqlite3

import pytest

from aoi.core.recipe import Recipe
from aoi.core.services import AppContext


def test_req_log_004_audit_is_append_only(ctx: AppContext) -> None:
    uid = ctx.audit("test.change", "recipe", "11111111-1111-4111-8111-111111111111", {"a": 1}, {"a": 2}, "why")
    (row,) = ctx.audit_entries(object_type="recipe")
    assert row["uuid"] == uid and row["at_utc"].endswith("+00:00") and row["role"] == "Engineer"
    assert row["user_uuid"] == ctx.db.user_uuid("engineer") and (row["before"], row["after"]) == ({"a": 1}, {"a": 2})
    with pytest.raises(sqlite3.DatabaseError, match="never changed"):
        ctx.db.execute("UPDATE audit SET reason='edited' WHERE uuid=?", (uid,))
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        ctx.db.execute("DELETE FROM audit WHERE uuid=?", (uid,))
    assert ctx.audit_entries()[0]["reason"] == "why"
    assert not hasattr(ctx.db, "update_audit") and not hasattr(ctx.db, "delete_audit")


def test_req_log_004_recipe_save_writes_before_and_after(ctx: AppContext) -> None:
    first = Recipe(board_model="TINY")
    assert ctx.save_recipe(first) == 1
    second = Recipe(board_model="TINY", ssim_min=first.ssim_min - 0.05)
    assert ctx.save_recipe(second, reason="looser SSIM for the new lighting") == 2
    entries = ctx.audit_entries(object_type="recipe", action="recipe.save")
    assert [e["before"] for e in entries] == [first.to_dict(), None]  # newest first
    assert entries[0]["after"] == second.to_dict() and entries[0]["reason"] == "looser SSIM for the new lighting"
    assert entries[0]["object_uuid"] == ctx.db.query("SELECT uuid FROM recipes WHERE revision=2")[0]["uuid"]
    assert entries[0]["user_uuid"] == ctx.db.user_uuid("engineer")


def test_req_log_004_audit_entries_filter(ctx: AppContext) -> None:
    for i in range(3):
        ctx.audit("model.activate", "model", f"model-{i}", None, {"version": i})
    ctx.audit("user.change", "user", "u-1", {"role": "Operator"}, {"role": "Engineer"})
    assert len(ctx.audit_entries()) == 4
    assert [e["after"]["version"] for e in ctx.audit_entries(object_type="model", limit=2)] == [2, 1]
    assert ctx.audit_entries(object_uuid="model-0")[0]["action"] == "model.activate"
    assert ctx.audit_entries(action="user.change")[0]["before"] == {"role": "Operator"}
    assert ctx.audit_entries(since="2999-01-01T00:00:00+00:00") == []
