"""REQ-TRN-009 (stage S41; Engineering standard, "Lineage"): an AI model file records its seed, the code that trained
it, every training setting and its dataset version, and retraining the same inputs reproduces its validation metrics.
Results on the synthetic boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

from dataclasses import asdict, fields
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from aoi.config import APP_VERSION
from aoi.core import anomaly, lineage
from aoi.core.imaging import align_to_reference
from aoi.core.services import AppContext
from tests.regression import make_regression_set as rs
from tests.test_train_from_version import BOARD, boards
from tools.trainable import trainable

SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"


def test_req_trn_009_model_file_records_its_lineage(ctx: AppContext, synthetic_dataset: Path) -> None:
    """A model trained through AppContext records, in its weights-only file and its registry row, the seed, every
    setting of the run (the network's and the Golden board's), the code that trained it and the dataset version."""
    boards(ctx, synthetic_dataset, 21)
    version = trainable(ctx, BOARD)
    meta = ctx.train(version, epochs=1, image_size=32)
    [row] = ctx.models(BOARD)
    stored = anomaly.AnomalyModel.load(row["path"]).meta  # weights_only=True
    for m in (meta, stored):
        assert m["seed"] == 0 and m["deterministic"] is True
        assert {f.name for f in fields(anomaly.TrainConfig)} <= set(m["settings"])
        assert (m["settings"]["epochs"], m["settings"]["image_size"], m["settings"]["seed"]) == (1, 32, 0)
        assert {"golden_band_bytes", "golden_step_bytes"} <= set(m["settings"])
        assert m["code"] == lineage.code_version() and m["code"].split(" ")[0] in ("commit", "build")
        assert m["dataset_uuid"] == version
    [entry] = ctx.audit_entries(action="model.train")
    assert entry["after"]["metrics"]["code"] == meta["code"] and entry["after"]["metrics"]["seed"] == 0


def _git(root: Path, head: str, loose: dict[str, str] | None = None, packed: str = "") -> Path:
    git = root / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text(head + "\n", encoding="utf-8")
    for ref, sha in (loose or {}).items():
        (git / ref).write_text(sha + "\n", encoding="utf-8")
    if packed:
        (git / "packed-refs").write_text(packed, encoding="utf-8")
    return git


def test_req_trn_009_code_version_names_the_commit(tmp_path: Path) -> None:
    """The commit is read from a detached HEAD, a loose ref, packed-refs, or a worktree's git folder; with no git
    folder, or one that names no commit, the code is the build's version."""
    detached = tmp_path / "detached"
    _git(detached, SHA)
    assert lineage.code_version(detached) == f"commit {SHA}"
    loose = tmp_path / "loose"
    _git(loose, "ref: refs/heads/main", {"refs/heads/main": SHA})
    assert lineage.code_version(loose) == f"commit {SHA}"
    packed = tmp_path / "packed"
    _git(
        packed,
        "ref: refs/heads/main",
        packed=f"# pack-refs with: peeled\n{OTHER} refs/heads/other\n{SHA} refs/heads/main\n",
    )
    assert lineage.code_version(packed) == f"commit {SHA}"
    worktree = tmp_path / "worktree"
    common = _git(tmp_path / "main-repo", "ref: refs/heads/main", {"refs/heads/feature": OTHER})
    (common / "worktrees" / "wt").mkdir(parents=True)
    (common / "worktrees" / "wt" / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")
    (common / "worktrees" / "wt" / "commondir").write_text("../..\n", encoding="utf-8")
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {common / 'worktrees' / 'wt'}\n", encoding="utf-8")
    assert lineage.code_version(worktree) == f"commit {OTHER}"
    assert lineage.code_version(tmp_path / "no-git") == f"build {APP_VERSION}"
    unborn = tmp_path / "unborn"
    _git(unborn, "ref: refs/heads/main")
    assert lineage.code_version(unborn) == f"build {APP_VERSION}"


def test_req_trn_009_deterministic_restores_the_setting() -> None:
    """The deterministic algorithms are on for the run and as they were afterwards, also when the run fails."""
    before = torch.are_deterministic_algorithms_enabled()
    with pytest.raises(RuntimeError), lineage.deterministic():
        assert torch.are_deterministic_algorithms_enabled()
        raise RuntimeError
    assert torch.are_deterministic_algorithms_enabled() == before


def _metrics(model: anomaly.AnomalyModel, val: list[tuple[str, anomaly.Prepared]]) -> dict[str, float]:
    """Each validation metric of `model` on `val` in percent: false calls of OK boards, missed NG boards, accuracy."""
    called = [(label, model.score(model.prepared_map(p)) > model.image_threshold) for label, p in val]
    ok = [ng for label, ng in called if label == "OK"]
    ng = [ng for label, ng in called if label == "NG"]
    return {
        "false_call_pct": 100 * sum(ok) / len(ok),
        "missed_pct": 100 * (len(ng) - sum(ng)) / len(ng),
        "accuracy_pct": 100 * (ok.count(False) + sum(ng)) / len(called),
    }


def test_req_trn_009_retrain_reproduces_metrics(tmp_path: Path) -> None:
    """Training twice on the synthetic regression set with the same inputs and settings gives each validation metric
    within 1 percentage point (Engineering standard, "Lineage"); on CPU the two AI models are identical, weight for
    weight and score for score."""
    found = rs.generate(tmp_path)
    golden = cv2.imread(str(tmp_path / "golden.png"))

    def prepared(name: str) -> anomaly.Prepared:
        return anomaly.prepare(align_to_reference(cv2.imread(str(tmp_path / name)), golden)[0], 64)

    ok = [b.name for b in found if b.label == "OK"]
    ng = [b.name for b in found if b.label == "NG"]
    train_ok, train_ng = [prepared(n) for n in ok[:12]], [prepared(n) for n in ng[:6]]
    val = [("OK", prepared(n)) for n in ok[12:]] + [("NG", prepared(n)) for n in ng[6:]]
    cfg = anomaly.TrainConfig(image_size=64, epochs=3, steps_per_epoch=4, seed=7)
    first, second = (anomaly.train(train_ok, train_ng, cfg) for _ in range(2))
    a, b = _metrics(first, val), _metrics(second, val)
    assert all(abs(a[k] - b[k]) <= 1.0 for k in a), (a, b)
    state_a, state_b = first.net.state_dict(), second.net.state_dict()
    assert all(torch.equal(state_a[k], state_b[k]) for k in state_a)
    assert first.image_threshold == second.image_threshold and first.meta["ok_scores"] == second.meta["ok_scores"]
    assert np.array_equal(first.meta["err_std"], second.meta["err_std"])
    assert first.meta["settings"] == asdict(cfg) and first.meta["seed"] == 7
