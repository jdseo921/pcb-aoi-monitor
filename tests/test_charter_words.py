"""#207: no Charter "Not" word in a catalogue or translated text unless kept with a reason; no label never matches."""

from __future__ import annotations

import csv
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QRectF, Qt, QTranslator
from PySide6.QtWidgets import QFileDialog, QFormLayout, QLabel
from pytestqt.qtbot import QtBot

from aoi.core.anomaly import AnomalyModel, ModelFileError
from aoi.core.services import AppContext
from aoi.errors import CODES, AoiError
from aoi.ui import theme
from aoi.ui.pages.base import cell_item
from aoi.ui.pages.model_test import ModelTestPage
from aoi.ui.pages.profile3d import Profile3DPage
from aoi.ui.pages.recipe_editor import RecipeEditorPage
from aoi.ui.pages.training import TrainingPage
from tests.test_explain import not_words
from tests.test_req_done_in_v01 import BOARD, _button, _window
from tools.update_translations import TS_FILE

OPERATION = "an operation that did not succeed (a copy, a migration, a backup), not a verdict"
FOLDER_WINDOW = "the operating system's folder chooser that opens next, not an ROI"
OTHER_PROGRAM = "another program on the PC (a viewer, a database tool), not a recipe"
APP_ERROR = "an error of the app itself (an exception), not a defect on a board"
ALLOWED_WORDS = {  # (catalogue code or translation context, Not word): why the word stays; a stale entry fails a test
    ("AOI-INSP-005", "limit"): "the image size an Admin sets in settings.json; no check turns NG at it",
    ("AOI-INSP-007", "limit"): "the decoder's longest side; no check turns NG at it",
    ("AOI-INSP-006", "fail"): OPERATION,
    ("AOI-TRN-008", "fail"): OPERATION,
    ("AOI-TRN-009", "fail"): OPERATION,
    ("AOI-TRN-010", "fail"): OPERATION,
    ("AOI-LOG-001", "fail"): OPERATION,
    ("AOI-SET-004", "fail"): OPERATION,
    ("AOI-SET-009", "fail"): OPERATION,
    ("AOI-CMP-003", "program"): OTHER_PROGRAM,
    ("AOI-CMP-006", "program"): OTHER_PROGRAM,
    ("AOI-LOG-002", "program"): OTHER_PROGRAM,
    ("AOI-SET-012", "program"): OTHER_PROGRAM,
    ("AOI-SET-013", "program"): OTHER_PROGRAM,
    ("AOI-SET-017", "program"): OTHER_PROGRAM,
    ("AOI-SET-001", "window"): FOLDER_WINDOW,
    ("AOI-SET-002", "window"): FOLDER_WINDOW,
    ("AOI-SET-003", "window"): FOLDER_WINDOW,
    ("AOI-SET-005", "window"): FOLDER_WINDOW,
    ("AOI-SET-011", "window"): FOLDER_WINDOW,
    ("AOI-SET-012", "window"): FOLDER_WINDOW,
    ("AOI-TRN-005", "window"): "the operating system's name, Windows, whose file names ignore case",
    ("AOI-INSP-014", "window"): "the operating system's name, Windows, whose long paths setting is the step",
    ("AOI-TRN-011", "window"): "the operating system's name, Windows, whose long paths setting is the step",
    ("AOI-TRN-042", "window"): "the operating system's name, Windows, whose long paths setting is the step",
    ("StoresPanel", "window"): "the operating system's name, Windows, whose account the key store belongs to",
    ("AOI-SET-007", "error"): APP_ERROR,
    ("AOI-TRN-010", "error"): APP_ERROR,
    ("AOI-SET-006", "invalid"): "said of the app's migration files, never of a user (the Charter bans 'invalid user')",
    ("AOI-SET-008", "invalid"): "said of a setting's value, never of a user (the Charter bans 'invalid user')",
    ("ComparePage", "test image"): "the board image compared with the Golden board (its Test Image… button), not the "
    "regression set's images; the Charter has no term for it yet",
}  # fmt: skip
CATALOGUE_TEXTS = {text: c.code for c in CODES.values() for text in (c.title, c.what, c.action)}


def _kept(where: str, text: str, used: set[tuple[str, str]]) -> list[str]:
    """The Not words of `text` that ALLOWED_WORDS does not keep for `where`; the kept ones are added to `used`."""
    found = not_words(text)
    used.update((where, w) for w in found if (where, w) in ALLOWED_WORDS)
    return [w for w in found if (where, w) not in ALLOWED_WORDS]


def test_req_set_019_the_error_catalogue_uses_only_glossary_terms() -> None:
    """Every catalogue text (and so docs/error-codes.md) uses the Charter's terms, and none tells a user to import an AI
    model file, which the app cannot do."""
    used: set[tuple[str, str]] = set()
    found = [
        (c.code, field, words)
        for c in CODES.values()
        for field in ("title", "what", "action")
        if (words := _kept(c.code, getattr(c, field), used))
    ]
    print("catalogue texts with a Not word:", found)
    assert found == []
    assert {k for k in ALLOWED_WORDS if k[0].startswith("AOI-")} == used, "an ALLOWED_WORDS entry no longer applies"
    importing = [t.replace("board model", "") for t in CATALOGUE_TEXTS if re.search(r"\bimport\b", t, re.IGNORECASE)]
    assert not any("model" in t for t in importing), "import"  # images imported under a board model are no AI model
    ng = AoiError("AOI-INSP-003", board="board_0042.png", defects=3)
    assert (ng.entry.title, ng.what) == ("Board judged NG", "Board board_0042.png was judged NG with 3 defect(s).")


def test_req_set_005_every_translated_string_uses_only_glossary_terms() -> None:
    """Every source string of aoi/i18n/aoi_ko.ts uses the Charter's terms; a catalogue text is judged under its code."""
    used: set[tuple[str, str]] = set()
    found = []
    for context in ET.parse(TS_FILE).getroot().findall("context"):
        name = context.findtext("name") or ""
        for message in context.findall("message"):
            source = message.findtext("source") or ""
            if words := _kept(CATALOGUE_TEXTS.get(source, name), source, used):
                found.append((name, source, words))
    print("translation sources with a Not word:", found)
    assert found == []
    assert {k for k in ALLOWED_WORDS if not k[0].startswith("AOI-")} <= used, "an ALLOWED_WORDS entry no longer applies"


def test_req_rcp_002_stage_2_thresholds_are_called_thresholds(
    qtbot: QtBot, trained_ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """An Engineer reads 3D Profile's card and the Recipe Editor's Height and Volume rows and applies a Height min above
    its max: the card, the rows and the AOI-RCP-002 dialog say thresholds, never limits or a bare "min / max"."""
    win = _window(qtbot, trained_ctx)
    win.navigate("3D Profile")
    profile = win.pages["3D Profile"]
    assert isinstance(profile, Profile3DPage)
    card = [w.text() for w in profile.card.findChildren(QLabel) if w.isVisible() and w.text()]
    win.navigate("Recipe Editor")
    page = win.pages["Recipe Editor"]
    assert isinstance(page, RecipeEditorPage)
    form = page.r_hmin.parentWidget().parentWidget().layout()
    assert isinstance(form, QFormLayout)
    rows = [form.labelForField(page.r_hmin.parentWidget()), form.labelForField(page.r_vmin.parentWidget())]
    labels = [w.text() for w in rows if isinstance(w, QLabel)]
    page.view.roiDrawn.emit(QRectF(20, 30, 40, 50))
    page.r_hmin.setValue(5)
    page.r_hmax.setValue(1)
    qtbot.mouseClick(_button(page, "Apply"), Qt.MouseButton.LeftButton)
    print("3D Profile card:", card, "Recipe Editor rows:", labels, "dialogs:", dialogs)
    assert any("Height and volume thresholds" in t for t in card) and not any("limit" in t.lower() for t in card)
    assert labels == ["Height thresholds min / max (Stage 2)", "Volume thresholds min / max (Stage 2)"]
    assert [t for t, _ in dialogs] == ["AOI-RCP-002 ROI thresholds refused"]
    assert "limit" not in dialogs[0][1].lower() and "a threshold is 0 or more" in dialogs[0][1]


def test_req_trn_014_a_refused_ai_model_file_names_the_ai_model_and_no_import(tmp_path: Path) -> None:
    """A damaged AI model file is refused with AOI-TRN-001 in the Charter's words, with no import the app lacks."""
    bad = tmp_path / "bad.pt"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ModelFileError) as refused:
        AnomalyModel.load(bad)
    print(refused.value)
    assert not_words(str(refused.value)) == [] and "import" not in str(refused.value)
    assert "weights-only AI model file this app wrote" in refused.value.what
    assert refused.value.action == "Train the board model again."


def test_req_trn_013_export_ai_model_offers_an_ai_model_file(
    qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Training's Export AI model dialog offers the file type "AI model file (*.pt)", not "PyTorch model"."""
    win = _window(qtbot, trained_ctx)
    win.navigate("Training")
    page = win.pages["Training"]
    assert isinstance(page, TrainingPage)
    asked: list[str] = []

    def save_as(parent: object, caption: str, name: str, filters: str) -> tuple[str, str]:
        asked.append(filters)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(save_as))
    page.models.selectRow(0)
    page.export_model()
    print("Export AI model offers:", asked)
    assert asked == ["AI model file (*.pt)"]


class _Marking(QTranslator):
    """Translates every ModelTestPage string to «string &»: a cell that bypasses the translator, or escaping, shows."""

    def translate(self, context: str, source: str, disambiguation: str | None = None, n: int = -1) -> str | None:
        return f"«{source} &»" if context == "ModelTestPage" else None

    def isEmpty(self) -> bool:
        return False


def test_req_tst_003_an_image_with_no_label_never_reads_as_matching_it(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An NG board under ng/ and under misc/ (no label): the unlabelled row, CSV value and report cell say No label,
    never PASS; the labelled one says whether it matches; cells and report come through the translator."""
    board = sorted(synthetic_dataset.glob("test/ng/*.png"))[0]
    folder = tmp_path / "validation"
    for sub in ("ng", "misc"):
        (folder / sub).mkdir(parents=True)
        shutil.copy(board, folder / sub / board.name)
    win = _window(qtbot, trained_ctx)
    win.navigate("AI Model Test")
    page = win.pages["AI Model Test"]
    assert isinstance(page, ModelTestPage)
    page.folder = str(folder)
    page.run()
    qtbot.waitUntil(lambda: bool(page.rows) and page.btn_run.isEnabled(), timeout=60000)
    by_folder = {Path(r["image"]).parent.name: r for r in page.rows}
    cells = {
        Path(cell_item(page.table, i, 0).toolTip()).parent.name: [
            cell_item(page.table, i, c).text() for c in range(page.table.columnCount())
        ]
        for i in range(page.table.rowCount())
    }
    print("rows:", {k: (r["gt"], r["ai_result"], r["pass_fail"]) for k, r in by_folder.items()}, "cells:", cells)
    unlabelled, labelled = by_folder["misc"], by_folder["ng"]
    assert unlabelled["gt"] == "?" and unlabelled["pass_fail"] == "NO_LABEL"
    assert cells["misc"][4] == "No label" and page.headers[4] == "Matches label?"
    matches = "PASS" if labelled["ai_result"] in ("NG", "WARN") else "FAIL"
    assert labelled["pass_fail"] == matches
    assert cells["ng"][4] == {"PASS": "Matches label", "FAIL": "Differs from label"}[matches]

    out = tmp_path / "model_test.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")))
    page.export_csv()
    with out.open(encoding="utf-8-sig", newline="") as f:
        exported = {Path(r["image"]).parent.name: r["pass_fail"] for r in csv.DictReader(f)}
    assert exported == {"misc": "NO_LABEL", "ng": matches}

    report = page._report_html()
    row = re.search(rf"<td>{re.escape(board.name)}</td><td>\?</td>(.*?)</tr>", report)
    assert row is not None, report
    assert f"<td>{theme.verdict_label(unlabelled['ai_result'])}</td>" in row.group(1)
    assert row.group(1).endswith("<td>No label</td>") and "PASS" not in report and "FAIL" not in report

    stored = {**unlabelled, "pass_fail": "PASS"}  # a run kept from before #207: its "?" label still reads No label
    translator = _Marking()
    assert QCoreApplication.installTranslator(translator)
    try:
        page._show((page.metrics, [stored, labelled], page.run_judged), str(folder), BOARD)
        shown = sorted(cell_item(page.table, i, 4).text() for i in range(page.table.rowCount()))
        report = page._report_html()
    finally:
        QCoreApplication.removeTranslator(translator)
    print("with a marking translator:", shown)
    assert shown == sorted(["«No label &»", {"PASS": "«Matches label &»", "FAIL": "«Differs from label &»"}[matches]])
    assert "<td>«No label &amp;»</td>" in report, report
