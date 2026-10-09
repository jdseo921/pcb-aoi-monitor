"""REQ-TRN-016 (stage S34): two labellers label the same 100-image calibration set blind; they agree when their OK or
NG labels match on at least 98 % of the images and their defect types on at least 90 % of the images both labelled NG
(proposed targets), and every agreement check is stored with its counts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from aoi.core import labels
from aoi.core.imaging import save_image
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.test_labels import UUID4

CAL = "CAL-1"  # the calibration workspace's board model


def calibration_workspace(ctx: AppContext, folder: Path, n_ok: int = 80, n_ng: int = 20) -> list[dict[str, object]]:
    """Import n_ok OK and n_ng NG (Scratch) images of 32 x 32 px, each different, as the engineer; returns the samples.
    Also adds the Engineers kim, lee and park, as the admin."""
    folder.mkdir()
    rng = np.random.default_rng(16)
    for i in range(n_ok + n_ng):
        save_image(folder / f"board_{i:03d}.png", rng.integers(0, 256, (32, 32, 3), dtype=np.uint8))
    paths = [str(p) for p in sorted(folder.glob("*.png"))]
    ctx.import_samples(CAL, paths[:n_ok], "OK")
    ctx.import_samples(CAL, paths[n_ok:], "NG", "Scratch")
    ctx.set_user("admin")
    for name in ("kim", "lee", "park"):
        ctx.add_user(name, "Engineer")
    ctx.set_user("engineer")
    return ctx.samples(CAL)


def label_blind(ctx: AppContext, user: str, cal: str, samples: list[dict[str, object]], flips: int, types: int) -> str:
    """`user` labels every image of the set blind as the workspace does, but the first `flips` OK images NG (Scratch)
    and the first `types` NG images Solder Bridge; returns the user's UUID."""
    ctx.set_user(user)
    ok, ng = ([s for s in samples if s["label"] == k][:n] for k, n in (("OK", flips), ("NG", types)))
    for s in samples:
        label, dtype = ("NG", "Scratch") if s in ok else (str(s["label"]), s["defect_type"])
        ctx.label_blind(cal, str(s["uuid"]), label, "Solder Bridge" if s in ng else dtype)  # type: ignore[arg-type]
    ctx.set_user("engineer")
    return str(ctx.db.user_uuid(user))


def test_req_trn_016_agreement_thresholds(ctx: AppContext, tmp_path: Path) -> None:
    """98 of 100 OK/NG labels and 18 of 20 defect types alike reach the targets; 97 of 100, or 17 of 20, do not; a set
    with no image both labelled NG cannot show defect-type agreement. Each check is stored with its counts, targets,
    labellers and time, and audited; refused: a set not of 100 images labelled OK or NG, an image outside the set, a
    second blind label, an NG blind label with no type, an unknown set, one labeller twice, one not done labelling."""
    a = {f"s{i}": ("NG", "Scratch") if i < 20 else ("OK", None) for i in range(100)}

    def b(flips: int, types: int) -> dict[str, tuple[str, str | None]]:
        flipped = {f"s{i}": ("NG", "Scratch") for i in range(20, 20 + flips)}
        return a | flipped | {f"s{i}": ("NG", "Solder Bridge") for i in range(types)}

    assert labels.agreement(a, b(2, 2)) == {
        "images": 100, "ok_ng_agree": 98, "both_ng": 20, "type_agree": 18, "ok_ng_target": 98, "type_target": 90,
        "agreed": True,
    }  # fmt: skip
    assert [labels.agreement(a, b(*n))["agreed"] for n in ((3, 2), (2, 3), (0, 0))] == [False, False, True]
    ok_only = {s: ("OK", None) for s in a}
    assert not labels.agreement(ok_only, ok_only)["agreed"]  # 100 of 100 OK/NG, 0 of 0 defect types
    samples = calibration_workspace(ctx, tmp_path / "boards")
    cal = ctx.make_calibration_set(CAL, [str(s["uuid"]) for s in samples])
    kim, lee, park = (label_blind(ctx, u, cal, samples, n, n) for u, n in (("kim", 0), ("lee", 2), ("park", 3)))
    entries = len(ctx.audit_entries())
    reached = ctx.run_agreement_check(cal, kim, lee)
    missed = ctx.run_agreement_check(cal, kim, park)
    counts = ("images", "ok_ng_agree", "both_ng", "type_agree", "ok_ng_target", "type_target", "agreed")
    stored = [tuple(c[k] for k in counts) for c in (reached, missed)]
    assert stored == [(100, 98, 20, 18, 98, 90, 1), (100, 97, 20, 17, 98, 90, 0)]
    assert ctx.agreement_checks(CAL) == [missed, reached]  # newest first, as stored
    assert UUID4.match(reached["uuid"]) and (reached["labeller_a"], reached["labeller_b"]) == (kim, lee)
    assert (reached["set_uuid"], reached["run_by"]) == (cal, ctx.db.user_uuid("engineer"))
    assert str(reached["at_utc"]).endswith("+00:00")
    audited = [e["after"]["uuid"] for e in ctx.audit_entries(action="agreement.check")]
    assert audited == [missed["uuid"], reached["uuid"]]
    assert len(ctx.audit_entries()) == entries + 2
    first, unsure = str(samples[0]["uuid"]), str(samples[1]["uuid"])
    ctx.set_label(unsure, "UNSURE")
    ctx.set_user("park")
    refusals = [
        ("AOI-TRN-035", lambda: ctx.make_calibration_set(CAL, [str(s["uuid"]) for s in samples[:99]])),
        ("AOI-TRN-035", lambda: ctx.make_calibration_set(CAL, [str(s["uuid"]) for s in samples])),  # one UNSURE
        ("AOI-TRN-036", lambda: ctx.label_blind(cal, first, "OK")),  # park labelled it blind already
        ("AOI-TRN-036", lambda: ctx.label_blind(cal, "an-image-outside-the-set", "OK")),
        ("AOI-TRN-037", lambda: ctx.run_agreement_check("no-such-set", kim, lee)),
        ("AOI-TRN-037", lambda: ctx.run_agreement_check(cal, kim, kim)),
    ]
    ctx.set_user("admin")
    with pytest.raises(AoiError) as typeless:
        ctx.label_blind(cal, first, "NG")
    assert typeless.value.code == "AOI-TRN-036"
    ctx.label_blind(cal, first, "OK")  # the admin's only blind label
    refusals.append(("AOI-TRN-037", lambda: ctx.run_agreement_check(cal, kim, str(ctx.db.user_uuid("admin")))))
    ctx.set_user("park")
    entries = len(ctx.audit_entries())
    for code, call in refusals:
        with pytest.raises(AoiError) as refused:
            call()
        assert refused.value.code == code
    assert len(ctx.audit_entries()) == entries and len(ctx.agreement_checks(CAL)) == 2


@pytest.mark.parametrize(("n_ok", "n_ng", "drawn_ng"), [(80, 20, 20), (90, 40, 30), (60, 50, 40), (100, 0, 0)])
def test_req_trn_016_draw_calibration(n_ok: int, n_ng: int, drawn_ng: int) -> None:
    """A proposed set holds 100 different images labelled OK or NG: 30 NG, or every NG image when fewer, and more NG
    where the OK images run short; the same seed draws the same set, and the NG images are not drawn first."""
    ok, ng = [f"ok{i}" for i in range(n_ok)], [f"ng{i}" for i in range(n_ng)]
    drawn = labels.draw_calibration(ok, ng, 7)
    assert len(set(drawn)) == len(drawn) == labels.CALIBRATION_IMAGES and set(drawn) <= set(ok + ng)
    assert sum(s in ng for s in drawn) == drawn_ng and drawn == labels.draw_calibration(ok, ng, 7)
    assert drawn_ng == 0 or {s in ng for s in drawn[:drawn_ng]} == {True, False}
    assert labels.draw_calibration(ok[:-1], ng[: 100 - n_ok], 7) == []  # 99 images make no set


def test_req_trn_016_propose_calibration_set_and_blind_labelled(ctx: AppContext, tmp_path: Path) -> None:
    """The proposal draws from the board model's images labelled OK or NG, every view together, as the seed draws,
    and the set made from it is accepted; with fewer than 100 such images it is refused (AOI-TRN-035), proposing
    nothing and writing no audit entry. blind_labelled names the images each user labelled blind, never the labels."""
    samples = calibration_workspace(ctx, tmp_path / "boards", 85, 20)
    reference, unsure = (str(s["uuid"]) for s in samples[:2])  # the first import is the reference: it stays OK
    ctx.set_label(unsure, "UNSURE")
    ok, ng = ([str(s["uuid"]) for s in ctx.samples(CAL, k)] for k in ("OK", "NG"))
    proposed = ctx.propose_calibration_set(CAL, 3)
    assert proposed == labels.draw_calibration(ok, ng, 3) and unsure not in proposed
    cal = ctx.make_calibration_set(CAL, proposed)
    assert ctx.calibration_sets(CAL)[0]["sample_uuids"] == proposed
    for user, n in (("kim", 3), ("lee", 1)):
        ctx.set_user(user)
        for uuid in proposed[:n]:
            ctx.label_blind(cal, uuid, "OK" if uuid in ok else "NG", None if uuid in ok else "Scratch")
    assert ctx.blind_labelled(cal) == {ctx.db.user_uuid("kim"): proposed[:3], ctx.db.user_uuid("lee"): proposed[:1]}
    assert ctx.blind_labelled("no-such-set") == {}
    for uuid in [u for u in ok if u != reference][:5]:
        ctx.set_label(uuid, "UNSURE")
    entries = len(ctx.audit_entries())
    with pytest.raises(AoiError) as refused:
        ctx.propose_calibration_set(CAL)
    assert refused.value.code == "AOI-TRN-035" and "holds 99 images labelled OK or NG, not 100" in refused.value.what
    assert len(ctx.audit_entries()) == entries
