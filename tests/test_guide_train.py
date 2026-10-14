"""REQ-TRN-021 for B5 of the 2026-10 business-readiness brief (D4; docs/sketches/first-run-guide.md, Q72, Q73, Q79,
Q80): the first-run guide's Train runs, in one press, the five parts the Engineering pages take one by one: it keeps
the validation images apart in a Trial version, trains, makes the AI model active, validates it on the images kept
apart and runs the shift check, with one progress line for the whole press. A part done before is not done again.
Results on synthetic boards prove a code path; they are never quoted as accuracy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aoi.core import run_progress
from aoi.core.jobs import JobCancelled
from aoi.core.labels import DefectBox
from aoi.core.run_progress import Press, RunProgress
from aoi.core.services import FIRST_LIVE, GUIDE_PARTS, AppContext
from aoi.errors import AoiError, Phrase
from tests.test_trial_versions import ONE, one_person

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
