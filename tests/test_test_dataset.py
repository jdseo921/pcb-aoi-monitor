"""REQ-TST-001 (stage S44, part 1): AI Model Test validates the active AI model on a frozen dataset version's locked
validation set, with the labels frozen, and the same AI model and data give the same verdicts and scores again. Results
on the synthetic boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

import pytest

from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.test_req_done_in_v01 import BOARD
from tools.trainable import trainable


def held_out(ctx: AppContext) -> tuple[str, dict[str, str]]:
    """A frozen version of TINY whose locked validation set holds 4 OK and 2 NG samples, and their labels by sample."""
    oks, ngs = ctx.samples(BOARD, "OK")[-4:], ctx.samples(BOARD, "NG")[-2:]
    labels = {s["uuid"]: s["label"] for s in oks + ngs}
    return trainable(ctx, BOARD, held=list(labels)), labels


def test_req_tst_001_dataset_version_input(trained_ctx: AppContext) -> None:
    """A run on a dataset version judges exactly its locked validation set, each image labelled as frozen, and is stored
    and audited naming the version."""
    ctx = trained_ctx
    version, labels = held_out(ctx)
    metrics, rows, _ = ctx.test_dataset(version)
    frozen = {i["path"].split("/")[-1]: i["label"] for i in ctx.dataset_items(version) if i["sample_uuid"] in labels}
    assert sorted((r["image"].replace("\\", "/").split("/")[-1], r["gt"]) for r in rows) == sorted(frozen.items())
    assert all(r["pass_fail"] in ("PASS", "FAIL") for r in rows) and metrics
    run = ctx.db.latest_test_run(BOARD)
    assert run is not None and run["dataset_uuid"] == version and run["uuid"] == rows[0]["run_uuid"]
    entry = ctx.audit_entries(action="test.run")[0]
    assert entry["after"]["dataset_uuid"] == version and entry["after"]["run_uuid"] == run["uuid"]


def test_req_tst_001_rerun_identical(trained_ctx: AppContext) -> None:
    """Run Test Again with the same AI model, recipe and dataset version gives the same verdicts and scores, row for
    row, in the same order."""
    ctx = trained_ctx
    version, _ = held_out(ctx)
    keys = ("image", "gt", "ai_result", "score", "defects", "pass_fail", "ai_check")
    first, second = ([{k: r[k] for k in keys} for r in ctx.test_dataset(version)[1]] for _ in range(2))
    assert first == second and len(first) == 6


def test_req_tst_001_unlocked_version_refused(trained_ctx: AppContext) -> None:
    """A version without a locked validation set, or one the workspace does not hold, is refused with AOI-TST-003
    before anything is judged or stored."""
    ctx = trained_ctx
    unsplit = trainable(ctx, BOARD, split=False)
    before = (ctx.db.latest_test_run(BOARD), ctx.audit_entries())
    for uid, why in ((unsplit, "its validation set is not split and locked"),
                     ("no-such-version", "the workspace holds no such dataset version")):  # fmt: skip
        with pytest.raises(AoiError) as e:
            ctx.test_dataset(uid)
        assert e.value.code == "AOI-TST-003" and why in e.value.what
    assert (ctx.db.latest_test_run(BOARD), ctx.audit_entries()) == before
