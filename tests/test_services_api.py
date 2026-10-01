"""REQ-USR-001, layering part (stage S15): the AppContext calls the screens use in place of the database."""

from __future__ import annotations

from pathlib import Path

from aoi.core.services import AppContext


def test_req_usr_001_appcontext_reads_and_writes_what_the_screens_need(trained_ctx: AppContext, tmp_path: Path) -> None:
    ctx = trained_ctx
    assert ctx.board_models() == ["TINY"]
    ctx.ensure_board_model("NEW")
    assert ctx.board_models() == ["NEW", "TINY"]
    samples, ok = ctx.samples("TINY"), ctx.samples("TINY", "OK")
    assert ok and len(ok) < len(samples) and all(Path(s["path"]).is_absolute() for s in samples)
    ctx.set_reference("TINY", ok[1]["id"])
    assert ctx.reference_image("TINY") == ctx.sample_path(ok[1]["id"]) == ok[1]["path"]
    ctx.update_sample(ok[0]["id"], "NG", "Scratch")
    assert next(s for s in ctx.samples("TINY", "NG") if s["id"] == ok[0]["id"])["defect_type"] == "Scratch"
    ctx.delete_sample(ok[0]["id"])
    assert all(s["id"] != ok[0]["id"] for s in ctx.samples("TINY"))
    (model,) = ctx.models("TINY")
    assert ctx.active_model("TINY") == model == ctx.model(model["id"]) and Path(model["path"]).is_file()
    assert ctx.export_model(model["id"], tmp_path / "exported.pt").read_bytes() == Path(model["path"]).read_bytes()
    ctx.inspect_file("TINY", ok[1]["path"])
    (row,) = ctx.inspections()
    assert row["board_model"] == "TINY" and Path(row["overlay_path"]).is_file()
    assert ctx.defects_for(row["id"]) == ctx.db.defects_for(row["id"])
    status = ctx.board_status("TINY")
    # one OK sample was relabelled NG and then removed
    assert (status.ok_samples, status.ng_samples) == (len(ok) - 1, len(samples) - len(ok))
    assert status.model_version == model["version"] and status.recipe_revision == 0 and status.last_test is None
    assert (status.inspected, status.ng) == (1, int(row["result"] == "NG"))
    assert ctx.export_overlays(ctx.inspections(), tmp_path / "overlays") == 1
    assert ctx.inspections(board_model="OTHER") == [] and ctx.archive_old() == 0
    assert ctx.archive_old(-1) == 1  # a cutoff in the future, so the record saved this second counts
    assert ctx.inspections() == [] and len(ctx.inspections(include_archived=True)) == 1
    ctx.add_user("kim", "Engineer")
    assert ("kim", "Engineer") in [(u["name"], u["role"]) for u in ctx.users()]
    assert ctx.recipe_history("TINY") == [] and ctx.save_recipe(ctx.recipe("TINY")[1]) == 1
    assert [h["revision"] for h in ctx.recipe_history("TINY")] == [1] and ctx.board_status("TINY").recipe_revision == 1
