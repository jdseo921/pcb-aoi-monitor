"""REQ-TRN-021 for B5 of the 2026-10 business-readiness brief (D4; docs/sketches/first-run-guide.md, Q72, Q73, Q79,
Q80): the first-run guide's Train runs, in one press, the five parts the Engineering pages take one by one: it keeps
the validation images apart in a Trial version, trains, makes the AI model active, validates it on the images kept
apart and runs the shift check, with one progress line for the whole press. A part done before is not done again.
Results on synthetic boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from aoi.core import run_progress
from aoi.core.imaging import save_image
from aoi.core.jobs import JobCancelled
from aoi.core.labels import DefectBox
from aoi.core.recipe import Recipe
from aoi.core.run_progress import Press, RunProgress
from aoi.core.services import FIRST_LIVE, GUIDE_PARTS, AppContext
from aoi.errors import AoiError, Phrase
from tests.test_trial_versions import ONE, one_person, validated_live

ACTIONS = ("dataset.freeze", "dataset.lock", "model.train", "model.activate", "test.run", "inspection.shift_check")


def ready(ctx: AppContext, folder: Path) -> None:
    """ONE-1 as `one_person` leaves it, the engineer signed in and the shift check asked for every 12 hours."""
    one_person(ctx, folder)
    ctx.set_user("engineer")
    ctx.settings.shift_check_hours = 12


def press(ctx: AppContext, stop: Any = None) -> tuple[dict[str, Any], list[RunProgress]]:
    """Train pressed for ONE-1's Top view as R1, with the run kept short: its result and every report."""
    said: list[RunProgress] = []
    out = ctx.guide_train(ONE, "Top", "R1", epochs=1, image_size=32, progress=said.append, should_stop=stop)
    return out, said


def entries(ctx: AppContext) -> dict[str, int]:
    return {a: len(ctx.audit_entries(action=a)) for a in ACTIONS}


def test_req_trn_021_train_runs_the_five_parts_in_one_press(ctx: AppContext, tmp_path: Path) -> None:
    """One press on 80 OK and 20 NG images, boxed by one person: a Trial version for Acme, the use "own" only, R1; its
    validation set holds 50 OK and 6 NG (30 % of 20) apart; the AI model, v1.0 (Trial), trained on the other 30 OK and
    14 NG, is the active one, as a board model's first; a test of it on the images kept apart is stored with counts;
    and a shift check is stored, each part audited as on the Engineering pages."""
    ready(ctx, tmp_path / "boards")
    out, said = press(ctx)
    version = out["dataset"]
    assert (version["assurance"], version["customer"], version["revision"], version["allowed_uses"]) == (
        "Trial",
        "Acme",
        "R1",
        ["own"],
    )
    assert (out["held"], out["trained"]) == ({"ok": 50, "ng": 6}, {"ok": 30, "ng": 14})
    assert out["model"]["version"] == "v1.0 (Trial)" and out["model"]["active"]
    assert ctx.active_model(ONE)["version"] == "v1.0 (Trial)"  # type: ignore[index]
    [live] = ctx.audit_entries(action="model.activate")
    assert live["reason"] == FIRST_LIVE
    run = out["run"]
    assert (run["dataset_uuid"], run["model_uuid"]) == (version["uuid"], out["model"]["uuid"])
    rates = run["metrics"]["rates"]
    assert (rates["missed_defects"]["of"], rates["false_calls"]["of"]) == (6, 50)  # counts, with their bounds
    assert out["shift"]["state"] in ("passed", "failed") and out["shift"]["check"] is not None
    assert out["not_run"] == []
    assert entries(ctx) == dict.fromkeys(ACTIONS, 1)

    phases = [str(p.phase) for p in said]
    starts = ["Keeping 50 OK and 6 NG images apart for validation", "Aligning", "Training the AI model: round 1 of 1"]
    starts += ["Setting the threshold: image", "Saving AI model v1.0 (Trial)", "Validating AI model v1.0 (Trial)"]
    starts += ["Shift check: master sample"]
    firsts = [next(i for i, p in enumerate(phases) if p.startswith(s)) for s in starts]
    assert firsts == sorted(firsts), phases
    assert phases[-1] == "Shift check: master sample 2 of 2"
    percents = [p.percent for p in said]
    assert percents == sorted(percents) and percents[-1] <= 99  # never falling; 100 only when the press ends
    assert any(p.left_s is not None for p in said if str(p.phase).startswith("Training the AI model"))


def test_req_trn_021_a_part_done_is_not_done_again(ctx: AppContext, tmp_path: Path) -> None:
    """A second press finds every part done: no freeze, lock, training, activation, test or shift check again. Images
    changed since make a new Trial version, trained and tested in turn; another revision does too."""
    ready(ctx, tmp_path / "boards")
    first, _ = press(ctx)
    before = entries(ctx)
    again, said = press(ctx)
    assert entries(ctx) == before and said == []
    assert again["dataset"]["uuid"] == first["dataset"]["uuid"] and again["model"]["id"] == first["model"]["id"]
    assert again["run"]["uuid"] == first["run"]["uuid"]
    ng = ctx.samples(ONE, "NG")[0]
    ctx.set_boxes(ng["uuid"], [DefectBox(1, 2, 8, 6, "Scratch"), DefectBox(20, 20, 4, 4, "Scratch")])
    changed, _ = press(ctx)
    assert changed["dataset"]["name"] == "DS-ONE1-R1-TOP-v2" and changed["model"]["version"] == "v1.1 (Trial)"
    assert changed["model"]["active"] and changed["run"]["model_uuid"] == changed["model"]["uuid"]
    out = ctx.guide_train(ONE, "Top", "R2", epochs=1, image_size=32)
    assert out["dataset"]["name"] == "DS-ONE1-R2-TOP-v3"


def test_req_trn_021_cancel_keeps_the_parts_done(ctx: AppContext, tmp_path: Path) -> None:
    """Cancel while training: JobCancelled, the version kept frozen and locked and no AI model saved; the next press
    goes on from training, freezing nothing again. Cancel while validating: the AI model stays active, and the result
    says the test and the shift check did not run; the press after it runs them."""
    ready(ctx, tmp_path / "boards")
    seen: list[str] = []

    def in_training() -> bool:
        return any(p.startswith("Training the AI model") for p in seen)

    with pytest.raises(JobCancelled):
        ctx.guide_train(ONE, "Top", "R1", 1, 32, lambda p: seen.append(str(p.phase)), in_training)
    [frozen] = ctx.datasets(ONE)
    assert ctx.validation_split(frozen["uuid"]) is not None and ctx.models(ONE) == []
    seen.clear()

    def validating() -> bool:
        return any(p.startswith("Validating") for p in seen)

    out = ctx.guide_train(ONE, "Top", "R1", 1, 32, lambda p: seen.append(str(p.phase)), validating)
    assert out["dataset"]["uuid"] == frozen["uuid"] and len(ctx.audit_entries(action="dataset.freeze")) == 1
    assert out["model"]["active"] and out["run"] is None and out["shift"] is None
    assert out["not_run"] == list(GUIDE_PARTS[3:]) == ["validate", "shift_check"]
    assert ctx.audit_entries(action="test.run") == []
    done, _ = press(ctx)
    assert done["not_run"] == [] and done["run"] is not None and done["model"]["id"] == out["model"]["id"]


def test_req_trn_021_only_what_the_guide_would_make_now_is_used_again(ctx: AppContext, tmp_path: Path) -> None:
    """A Trial version frozen on Training with the uses "own" and "shared" is not the guide's: the press freezes one
    with "own" only. A press for R2 freezes again; one for R1 after it takes R1's version back, freezing nothing. A
    recipe revision saved since makes a test of the same AI model and a shift check again, as does a passed shift check
    past its 12 hours; a failed one judged with what judges boards now is not run again."""
    ready(ctx, tmp_path / "boards")
    shared = ctx.freeze_dataset(ONE, "Top", "R1", "Acme", ("own", "shared"), trial=True)
    first, _ = press(ctx)
    assert first["dataset"]["uuid"] != shared["uuid"] and first["dataset"]["allowed_uses"] == ["own"]  # type: ignore[index]
    r2 = ctx.guide_train(ONE, "Top", "R2", epochs=1, image_size=32)
    before = entries(ctx)
    r1, said = press(ctx)
    assert r1["dataset"]["uuid"] == first["dataset"]["uuid"] != r2["dataset"]["uuid"]
    assert entries(ctx)["dataset.freeze"] == before["dataset.freeze"] and r1["model"]["id"] == first["model"]["id"]
    ctx.save_recipe(Recipe(board_model=ONE), "a revision saved since")
    before = entries(ctx)
    again, _ = press(ctx)
    assert again["run"]["uuid"] != r1["run"]["uuid"] and again["run"]["model_uuid"] == r1["run"]["model_uuid"]
    grown = {a: entries(ctx)[a] - before[a] for a in ACTIONS}
    assert grown == {a: int(a in ("test.run", "inspection.shift_check")) for a in ACTIONS}
    old = "2026-01-01T00:00:00+00:00"  # passed, and past its 12 hours: expired
    ctx.db.execute("UPDATE shift_checks SET passed=1, time=? WHERE board_model=?", (old, ONE))
    assert ctx.shift_check(ONE)["state"] == "expired"
    press(ctx)
    assert entries(ctx)["inspection.shift_check"] == before["inspection.shift_check"] + 2
    ctx.db.execute("UPDATE shift_checks SET passed=0 WHERE board_model=?", (ONE,))  # failed, judged as boards are now
    _, said = press(ctx)
    assert entries(ctx)["inspection.shift_check"] == before["inspection.shift_check"] + 2 and said == []


def test_req_trn_021_an_ai_model_made_active_on_training_leaves_the_guide(ctx: AppContext, tmp_path: Path) -> None:
    """Once an AI model trained on Training, from a Trial version with the uses "own" and "shared", judges the board
    model's boards, `guide_result` reads nothing and the guide shows no screen for the board model: its Train would
    put that AI model aside for its own."""
    ready(ctx, tmp_path / "boards")
    out, _ = press(ctx)
    made = ctx.guide_result(ONE)
    assert ctx.guide_step(ONE) == 3 and made is not None and made["model"]["id"] == out["model"]["id"]
    shared = ctx.freeze_dataset(ONE, "Top", "R1", "Acme", ("own", "shared"), trial=True)
    ctx.lock_validation_set(shared["uuid"], seed=1)
    meta = ctx.train(shared["uuid"], epochs=1, image_size=32)
    ctx.activate_model(int(next(m for m in ctx.models(ONE) if m["version"] == meta["version"])["id"]))
    assert ctx.active_model(ONE)["version"] == meta["version"] != out["model"]["version"]  # type: ignore[index]
    assert ctx.guide_result(ONE) is None and ctx.guide_step(ONE) is None


def test_req_trn_021_a_validated_ai_model_live_refuses_the_press(ctx: AppContext, tmp_path: Path) -> None:
    """While a Validated AI model of the board model is active, a Trial one never replaces it (ADR 0020, decision 4):
    the press is refused with AOI-TRN-057 before anything is frozen or trained."""
    ready(ctx, tmp_path / "boards")
    out, _ = press(ctx)
    meta = validated_live(ctx, out["dataset"])
    ng = ctx.samples(ONE, "NG")[0]
    ctx.set_boxes(ng["uuid"], [DefectBox(3, 3, 6, 6, "Scratch")])
    before = (ctx.audit_entries(), ctx.datasets(ONE), ctx.models(ONE))
    with pytest.raises(AoiError) as refused:
        press(ctx)
    assert refused.value.code == "AOI-TRN-057" and refused.value.params == {"board": ONE, "version": meta["version"]}
    assert (ctx.audit_entries(), ctx.datasets(ONE), ctx.models(ONE)) == before


def test_req_trn_021_cancel_before_the_lock_and_in_the_shift_check(ctx: AppContext, tmp_path: Path) -> None:
    """Cancel while the files are hashed: JobCancelled, nothing written. Cancel once the version is frozen: the next
    press locks that version, freezing nothing again. Cancel in the shift check: the test is stored and the result says
    only the shift check did not run."""
    ready(ctx, tmp_path / "boards")
    before = ctx.audit_entries()
    with pytest.raises(JobCancelled):
        ctx.guide_train(ONE, "Top", "R1", 1, 32, should_stop=lambda: True)
    assert ctx.audit_entries() == before and ctx.datasets(ONE) == []
    with pytest.raises(JobCancelled):
        ctx.guide_train(ONE, "Top", "R1", 1, 32, should_stop=lambda: bool(ctx.db.datasets(ONE)))
    [frozen] = ctx.datasets(ONE)
    assert ctx.validation_split(frozen["uuid"]) is None
    seen: list[str] = []
    out = ctx.guide_train(
        ONE, "Top", "R1", 1, 32, lambda p: seen.append(str(p.phase)), lambda: any("Shift check" in p for p in seen)
    )
    assert out["dataset"]["uuid"] == frozen["uuid"] and entries(ctx)["dataset.freeze"] == 1
    assert out["run"] is not None and out["shift"] is None and out["not_run"] == ["shift_check"]
    assert entries(ctx)["inspection.shift_check"] == 0


def test_req_trn_021_with_the_shift_check_off_train_runs_four_parts(ctx: AppContext, tmp_path: Path) -> None:
    """With the shift check off on Settings (0 hours), the press runs no shift check and counts none in its line; a
    Cancel while it validates names only the test as not run."""
    ready(ctx, tmp_path / "boards")
    ctx.settings.shift_check_hours = 0
    seen: list[str] = []
    out = ctx.guide_train(
        ONE, "Top", "R1", 1, 32, lambda p: seen.append(str(p.phase)), lambda: any("Validating" in p for p in seen)
    )
    assert out["run"] is None and out["not_run"] == ["validate"]
    done, said = press(ctx)
    assert done["shift"]["state"] == "off" and done["not_run"] == [] and done["run"] is not None
    assert not any(str(p.phase).startswith("Shift check") for p in said)
    assert entries(ctx)["inspection.shift_check"] == 0


def test_req_trn_021_a_refused_part_keeps_the_parts_before_it(ctx: AppContext, tmp_path: Path) -> None:
    """60 OK images: the press freezes a Trial version and locks 50 OK images apart, and training refuses the 10 left
    with AOI-TRN-045 (it takes 20), saving no AI model. With 10 OK images more, the next press freezes a version of the
    images now held, and runs every part."""
    one_person(ctx, tmp_path / "boards", n_ok=60)
    ctx.set_user("engineer")
    ctx.settings.shift_check_hours = 12
    with pytest.raises(AoiError) as e:
        press(ctx)
    assert e.value.code == "AOI-TRN-045"
    [refused] = ctx.datasets(ONE)
    assert ctx.validation_split(refused["uuid"]) is not None and ctx.db.models(ONE) == []
    assert entries(ctx) == dict.fromkeys(ACTIONS, 0) | {"dataset.freeze": 1, "dataset.lock": 1}
    more = tmp_path / "more"
    more.mkdir()
    rng = np.random.default_rng(21)
    for i in range(10):
        save_image(more / f"ok_{i}.png", rng.integers(0, 256, (32, 32, 3), dtype=np.uint8))
    ctx.import_samples(ONE, [str(p) for p in sorted(more.glob("*.png"))], "OK")
    out, _ = press(ctx)
    assert out["dataset"]["uuid"] != refused["uuid"] and out["not_run"] == []
    assert entries(ctx) == dict.fromkeys(ACTIONS, 1) | {"dataset.freeze": 2, "dataset.lock": 2}


def test_req_trn_021_train_is_an_engineers_and_one_run_at_a_time(ctx: AppContext, tmp_path: Path) -> None:
    """An Operator may not press Train; the guide's Train is the context's one training run, so a second while it goes
    on is refused with AOI-TRN-047, as Training's Start Training is."""
    one_person(ctx, tmp_path / "boards")
    ctx.set_user("operator")
    with pytest.raises(AoiError) as e:
        ctx.guide_train(ONE, "Top", "R1")
    assert e.value.code == "AOI-USR-001"
    ctx.set_user("engineer")
    job = ctx.start_guide_train(ONE, "Top", "R1")
    try:
        with pytest.raises(AoiError) as busy:
            ctx.start_guide_train(ONE, "Top", "R1")
        assert busy.value.code == "AOI-TRN-047" and ctx.training is job
    finally:
        job.cancel()
        job.wait(60)


def test_req_trn_021_the_press_reports_one_percent_and_time_left(monkeypatch: pytest.MonkeyPatch) -> None:
    """The press's line: training's time left plus the images judged after it, each taking an image aligned and a map
    as training timed them, then the time an image judged takes; the percent of the whole press never falls."""
    now = [0.0]
    monkeypatch.setattr(run_progress, "clock", lambda: now[0])
    align, threshold = "Aligning image {n} of {count}", "Setting the threshold: image {n} of {count}"
    p = Press(10, align, threshold)
    step = Phrase("Training", "Keeping {ok} OK and {ng} NG images apart for validation").fill(ok=50, ng=3)
    assert p.step(step).left_s is None  # nothing timed yet
    for n in (1, 2, 3):  # an image aligned each 2 s
        now[0] += 2
        report = p.training(RunProgress(5, 100.0, Phrase("Training", align).fill(n=n, count=60)))
    assert report.left_s == pytest.approx(100 + 10 * (2 + 2))  # an image aligned stands in for a map
    for n in (1, 2):  # a map each 1 s
        now[0] += 1
        report = p.training(RunProgress(90, 10.0, Phrase("Training", threshold).fill(n=n, count=16)))
    assert report.left_s == pytest.approx(10 + 10 * (2 + 1))
    now[0] += 5
    judged = p.judged_one(
        Phrase("Training", "Validating AI model {version}: image {n} of {count}").fill(version="v1.0", n=2, count=10)
    )
    assert judged.left_s == pytest.approx(9 * 5)  # timed now: 5 s each
    percents = [report.percent, judged.percent]
    assert percents == sorted(percents) and judged.percent == int(100 * 13 / (13 + 45))
