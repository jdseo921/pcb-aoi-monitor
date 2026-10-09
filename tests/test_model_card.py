"""REQ-TRN-011 and REQ-TRN-013 (stage S43): every AI model version has a model card, as JSON and Markdown, with
identity, set-up, results with counts and 95 % upper bounds (or "not yet tested"), thresholds, known limits and sign-off
lines; an export writes the weights-only file and its card side by side. Results on the synthetic boards prove a code
path; they are never quoted as accuracy."""

from __future__ import annotations

import json
from pathlib import Path

import torch

from aoi.core import anomaly, model_card
from aoi.core.services import AppContext
from tests.test_train_from_version import BOARD, boards
from tools.trainable import trainable

SECTIONS = ("## Identity", "## Set-up", "## Training", "## Results on the locked validation set", "## Thresholds",
            "## Known limits", "## Sign-off")  # fmt: skip


def trained(ctx: AppContext, synthetic_dataset: Path) -> dict[str, object]:
    boards(ctx, synthetic_dataset, 21)
    ctx.train(trainable(ctx, BOARD), epochs=1, image_size=32)
    return ctx.models(BOARD)[0]


def test_req_trn_011_card_fields(ctx: AppContext, synthetic_dataset: Path) -> None:
    """Training writes the version's card beside its file; the card names the version, its dataset, seed, code and
    settings, who trained it, the set-up, its thresholds, known limits and two sign-off lines, and says in its first
    line that it is not yet tested, with no rate on it."""
    model = trained(ctx, synthetic_dataset)
    card = ctx.model_card(int(model["id"]))  # type: ignore[arg-type]
    ident = card["identity"]
    assert (ident["board_model"], ident["version"], ident["uuid"]) == (BOARD, model["version"], model["uuid"])
    assert ident["trained_by"] == ctx.user and ident["customer"] == "Acme Electronics" and ident["seed"] == 0
    assert ident["code"].split(" ")[0] in ("commit", "build") and ident["settings"]["epochs"] == 1
    assert card["first_line"].startswith("Not yet tested on a locked validation set")
    assert card["results"] == {"status": model_card.NOT_TESTED}
    assert card["thresholds"]["image_threshold"] > 0 and card["sign_off"] == {"ai_lead": None, "quality_lead": None}
    assert card["setup"]["golden_board_px"] and card["known_limits"]
    md_path, json_path = ctx.card_files(int(model["id"]))  # type: ignore[arg-type]
    assert json.loads(json_path.read_text(encoding="utf-8")) == card
    text = md_path.read_text(encoding="utf-8")
    assert all(s in text for s in SECTIONS) and f"**{card['first_line']}**" in text
    assert "| AI lead |" in text and "| Quality lead |" in text


def test_req_trn_011_tested_card_carries_the_test() -> None:
    """A card built with a test on the locked validation set says so in its first line and lists the test's results."""
    test = {"missed_defects": "0 of 12, upper bound 22.1 %", "false_calls": "1 of 50, upper bound 9.1 %"}
    card = model_card.build({"dataset": "DS-X-R1-TOP-v1"}, trained_by=None, customer=None, view="Top",
                            golden_size=None, px_per_mm=None, test=test)  # fmt: skip
    assert card["first_line"].startswith("Tested on the locked validation set of DS-X-R1-TOP-v1")
    assert card["results"] == test and "0 of 12, upper bound 22.1 %" in model_card.markdown(card)


def test_req_trn_013_export_loads_weights_only(ctx: AppContext, synthetic_dataset: Path, tmp_path: Path) -> None:
    """Export writes <version>.pt, which loads with torch.load(weights_only=True), and <version>.card.md and
    <version>.card.json beside it, all named in the export's audit entry."""
    model = trained(ctx, synthetic_dataset)
    out = ctx.export_model(int(model["id"]), tmp_path / "out" / f"{model['version']}.pt")  # type: ignore[arg-type]
    loaded = torch.load(out, weights_only=True)
    assert (
        loaded["meta"]["uuid"] == model["uuid"] and anomaly.AnomalyModel.load(out).meta["version"] == model["version"]
    )
    md, js = out.with_suffix(".card.md"), out.with_suffix(".card.json")
    assert md.read_text(encoding="utf-8").startswith(f"# Model card: {BOARD} {model['version']}")
    assert json.loads(js.read_text(encoding="utf-8"))["identity"]["uuid"] == model["uuid"]
    [entry] = ctx.audit_entries(action="export.model")
    assert {Path(p).name for p in entry["after"]["files"]} == {out.name, md.name, js.name}
