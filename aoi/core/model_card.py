"""The model card of an AI model version (REQ-TRN-011; Engineering standard, "Model card"): what it is, the set-up it is
for, its results with counts and one-sided 95 % upper bounds, its thresholds, its known limits and the sign-off lines
for the AI lead and the quality lead. Built from the training record and, from S45, the latest test on the version's
locked validation set; as JSON and as Markdown, which a printed card and an export use. No Qt.

A card claims no accuracy it has no test for: until a test on the locked validation set fills the results, the card
says so in its first line and every result reads "not yet tested" (Customers & Launch, "Claims carry counts")."""

from __future__ import annotations

from pathlib import Path
from typing import Any

CARD_VERSION = 1
NOT_TESTED = "not yet tested"
# What every card says it was not made for; a card adds its own lines from what it knows (`limits`)
LIMITS = (
    "Judges boards of its own board model and view only, captured with the set-up below; a new board revision, camera,"
    " lens, lighting or distance needs a new AI model version.",
    "Learns from OK boards: a defect unlike anything it has seen may score low; the Golden board comparison checks"
    " every board as well.",
)


def paths(model_file: Path) -> tuple[Path, Path]:
    """The card's Markdown and JSON files beside an AI model file: `<version>.card.md` and `<version>.card.json`."""
    return model_file.with_suffix(".card.md"), model_file.with_suffix(".card.json")


TRAINING_KEYS = ("n_ok_train", "n_ok_val", "n_ng", "epochs_run", "final_loss", "train_seconds")


def build(
    meta: dict[str, Any],
    *,
    trained_by: str | None,
    customer: str | None,
    view: str | None,
    golden_size: tuple[int, int] | None,
    px_per_mm: float | None,
    test: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The card of the AI model whose file metadata is `meta`, as plain JSON values. `test` is the latest test on the
    version's locked validation set (S45), or None while there is none."""
    tested = test is not None
    first = (
        f"Tested on the locked validation set of {meta.get('dataset')}: rates below carry their counts."
        if tested
        else "Not yet tested on a locked validation set: nothing on this card is a measure of accuracy."
    )
    limits = list(LIMITS)
    if not tested:
        limits.append("Missed-defect and false call rates are unknown until it is tested on its locked validation set.")
    if px_per_mm is None:
        limits.append("Its board model has no scale: sizes are in pixels, not millimetres.")
    return {
        "card_version": CARD_VERSION,
        "first_line": first,
        "identity": {
            "board_model": meta.get("board_model"),
            "version": meta.get("version"),
            "uuid": meta.get("uuid"),
            "created_at": meta.get("created_at"),
            "trained_by": trained_by,
            "dataset": meta.get("dataset"),
            "dataset_uuid": meta.get("dataset_uuid"),
            "customer": customer,
            "use": meta.get("use"),
            "seed": meta.get("seed"),
            "code": meta.get("code"),
            "settings": meta.get("settings"),
        },
        "setup": {
            "view": view,
            "golden_board_px": list(golden_size) if golden_size else None,
            "px_per_mm": px_per_mm,
            "input_size_px": meta.get("image_size"),
        },
        "training": {k: meta.get(k) for k in TRAINING_KEYS},
        "results": test if tested else {"status": NOT_TESTED},
        "thresholds": {
            "image_threshold": meta.get("image_threshold"),
            "pixel_threshold": meta.get("pixel_threshold"),
            "rule": meta.get("threshold_rule"),
        },
        "known_limits": limits,
        "sign_off": {"ai_lead": None, "quality_lead": None},
    }


def _value(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def markdown(card: dict[str, Any]) -> str:
    """The card as Markdown, for printing and for `<version>.card.md` beside an exported `<version>.pt`."""
    ident, setup = card["identity"], card["setup"]
    lines = [f"# Model card: {ident['board_model']} {ident['version']}", "", f"**{card['first_line']}**", ""]
    lines += ["## Identity", "", "| Field | Value |", "|---|---|"]
    for key in ("board_model", "version", "uuid", "created_at", "trained_by", "dataset", "dataset_uuid", "customer",
                "use", "seed", "code"):  # fmt: skip
        lines.append(f"| {key} | {_value(ident.get(key))} |")
    settings = ident.get("settings") or {}
    lines.append("| settings | " + ", ".join(f"{k} {_value(v)}" for k, v in sorted(settings.items())) + " |")
    lines += ["", "## Set-up", "", "| Field | Value |", "|---|---|"]
    lines += [f"| {k} | {_value(v)} |" for k, v in setup.items()]
    lines += ["", "## Training", "", "| Field | Value |", "|---|---|"]
    lines += [f"| {k} | {_value(v)} |" for k, v in card["training"].items()]
    lines += ["", "## Results on the locked validation set", ""]
    results = card["results"]
    if results.get("status") == NOT_TESTED:
        lines.append(f"Missed defects, false calls, recall per defect type and time per image: {NOT_TESTED}.")
    else:
        lines += ["| Measure | Value |", "|---|---|"] + [f"| {k} | {_value(v)} |" for k, v in results.items()]
    lines += ["", "## Thresholds", "", "| Threshold | Value |", "|---|---|"]
    lines += [f"| {k} | {_value(v)} |" for k, v in card["thresholds"].items()]
    lines += ["", "## Known limits", ""] + [f"- {limit}" for limit in card["known_limits"]]
    lines += ["", "## Sign-off", "", "| Role | Name | Date | Signature |", "|---|---|---|---|"]
    lines += ["| AI lead |  |  |  |", "| Quality lead |  |  |  |", ""]
    return "\n".join(lines)
