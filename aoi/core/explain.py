"""Plain-word explanations of a verdict (REQ-CMP-004; sketch docs/sketches/compare-decision-table.md of PR #79,
"Why"): one sentence per check that decides it, NG before WARN, naming the check, its value and its threshold with
units, in the Charter's words; with no such check, why the verdict is what it is; then one per check that did not run,
with what to do. No Qt here: a sentence is an English template with named placeholders and the values that fill it,
and a screen translates the template under the context "Explain" before filling it in."""

from __future__ import annotations

from dataclasses import dataclass, field

from .inspector import NG, NO_AI_NOTE, NO_GOLDEN_NOTE, OK, WARN, Check, InspectionResult


def QT_TRANSLATE_NOOP(context: str, text: str) -> str:
    """Mark `text` for pyside6-lupdate, which finds the call by this name, under `context`; give it back unchanged."""
    return text


# (the check's name as the engine stores it, its verdict) -> the sentence that names it.
CHECKS = {
    ("SSIM similarity", NG): QT_TRANSLATE_NOOP(
        "Explain", "Similarity to the Golden board is {value}, below its threshold of {threshold}."
    ),
    ("SSIM similarity", WARN): QT_TRANSLATE_NOOP(
        "Explain", "Similarity to the Golden board is {value}, at or just above its threshold of {threshold}."
    ),
    ("Changed area %", NG): QT_TRANSLATE_NOOP(
        "Explain", "The changed area is {value} of the board, at or above its threshold of {threshold}."
    ),
    ("Changed area %", WARN): QT_TRANSLATE_NOOP(
        "Explain", "The changed area is {value} of the board, close to its threshold of {threshold}."
    ),
    ("Difference regions", NG): QT_TRANSLATE_NOOP(
        "Explain", "The number of difference regions is {value}, more than the threshold of {threshold}."
    ),
    ("Alignment inliers", WARN): QT_TRANSLATE_NOOP(
        "Explain",
        "The number of alignment points is {value}, fewer than the threshold of {threshold}, so the other checks may"
        " be off: check that the board lies flat, then inspect it again.",
    ),
    ("AI anomaly score", NG): QT_TRANSLATE_NOOP(
        "Explain", "The AI score is {value}, at or above its threshold of {threshold}."
    ),
    ("AI anomaly score", WARN): QT_TRANSLATE_NOOP(
        "Explain", "The AI score is {value}, close to its threshold of {threshold}."
    ),
}
ROI_CHECK = {  # an ROI's value is the AI score inside it as a multiple of the AI model's threshold
    NG: QT_TRANSLATE_NOOP(
        "Explain",
        "In ROI {roi}, the AI score is {value} the AI model's threshold, at or above the ROI's threshold of"
        " {threshold}.",
    ),
    WARN: QT_TRANSLATE_NOOP(
        "Explain",
        "In ROI {roi}, the AI score is {value} the AI model's threshold, close to the ROI's threshold of {threshold}.",
    ),
}
OTHER_CHECK = QT_TRANSLATE_NOOP("Explain", "{check} is {value}, against its threshold of {threshold}.")  # stored data
ALL_INSIDE = QT_TRANSLATE_NOOP("Explain", "Every check that decides the verdict is inside its threshold.")
SEVERE_DEFECT = QT_TRANSLATE_NOOP(
    "Explain", "No check failed, but a defect above Minor severity is marked on the board, so a person needs to look."
)
SEVERE_DEFECTS = QT_TRANSLATE_NOOP(
    "Explain",
    "No check failed, but {count} defects above Minor severity are marked on the board, so a person needs to look.",
)
UNEXPLAINED = QT_TRANSLATE_NOOP("Explain", "The stored checks do not show why; inspect the board again.")
NOTES = {
    NO_GOLDEN_NOTE: QT_TRANSLATE_NOOP(
        "Explain",
        "No Golden board is set for this board model, so the board was not compared with one: an Engineer makes one"
        " by training an AI model on Training.",
    ),
    NO_AI_NOTE: QT_TRANSLATE_NOOP(
        "Explain",
        "No AI model is trained for this board model, so the AI check did not run: an Engineer trains one on Training.",
    ),
}
OTHER_NOTE = QT_TRANSLATE_NOOP("Explain", "Note: {note}")
UNITS = {"Changed area %": "%", "Difference regions": "", "Alignment inliers": "", "ROI": "×"}  # "" = a count
TEMPLATES = [  # every template a screen may translate, for the tests
    *CHECKS.values(), *ROI_CHECK.values(), OTHER_CHECK, ALL_INSIDE, SEVERE_DEFECT, SEVERE_DEFECTS, UNEXPLAINED,
    *NOTES.values(), OTHER_NOTE,
]  # fmt: skip


@dataclass(frozen=True)
class Sentence:
    """An English template with named placeholders and the values that fill it."""

    template: str
    values: dict[str, str] = field(default_factory=dict)

    def text(self) -> str:
        """The sentence in English (logs and tests); a screen translates `template` first."""
        return self.template.format(**self.values)


def numbers(c: Check) -> tuple[str, str]:
    """A check's value and threshold as shown: the value, a space, then the unit (Charter, "Numbers"); counts whole;
    other values with two decimals, or with as many more, up to ten, as it takes to show a value that is not equal to
    its threshold as another number."""
    unit = UNITS.get("ROI" if c.source == "ROI" else c.name)
    if unit == "":
        return f"{c.value:.0f}", f"{c.threshold:.0f}"
    decimals = 2
    while c.value != c.threshold and decimals < 10 and f"{c.value:.{decimals}f}" == f"{c.threshold:.{decimals}f}":
        decimals += 1
    value, threshold = f"{c.value:.{decimals}f}", f"{c.threshold:.{decimals}f}"
    return (f"{value} {unit}", f"{threshold} {unit}") if unit else (value, threshold)


def explain(res: InspectionResult) -> list[Sentence]:
    """The sentences for `res`: one per NG check, then one per WARN check, each in the order the engine ran them (or,
    with none, why the verdict is what it is), then one per check that did not run (`notes`)."""
    out = []
    for c in [c for c in res.checks if c.verdict == NG] + [c for c in res.checks if c.verdict == WARN]:
        value, threshold = numbers(c)
        values = {"value": value, "threshold": threshold}
        if c.source == "ROI":  # named as the table names it: "R1 [Presence]"
            out.append(Sentence(ROI_CHECK[c.verdict], {"roi": c.name.removeprefix("ROI "), **values}))
        else:
            out.append(Sentence(CHECKS.get((c.name, c.verdict), OTHER_CHECK), {"check": c.name, **values}))
    severe = sum(d.severity != "Minor" for d in res.defects)
    if not out and res.verdict == WARN and severe:
        out.append(Sentence(SEVERE_DEFECT) if severe == 1 else Sentence(SEVERE_DEFECTS, {"count": str(severe)}))
    elif not out:
        out.append(Sentence(ALL_INSIDE if res.verdict == OK else UNEXPLAINED))
    return out + notes(res)


def notes(res: InspectionResult) -> list[Sentence]:
    """One sentence per check that did not run, from the notes the engine stored with `res`, in plain words with what
    to do; a note this build does not know shows as written."""
    return [Sentence(NOTES[n]) if n in NOTES else Sentence(OTHER_NOTE, {"note": n}) for n in res.notes]
