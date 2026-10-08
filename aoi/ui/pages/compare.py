"""Side-by-side Compare page.

Optional page (reachable from the sidebar or "Compare with Golden" on the
Inspection screen) that shows the golden reference next to a test board and
every metric that decided OK / WARN / NG; a stored result is shown as it was
decided and never inspected again (REQ-CMP-003). The "Try other thresholds"
panel is for an Engineer or Admin and hidden for an Operator (REQ-CMP-005,
docs/adr/0006-judging-a-stored-result-again.md decision 4).
Its Re-evaluate judges a stored result again from its stored maps and shows
what it would be; its Save to Recipe makes them the board model's recipe,
a new revision with an audit entry, after an inline sheet lists what changes and asks for a reason.
"""

from __future__ import annotations

import copy
import dataclasses
import html
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ... import defects as taxonomy
from ...core.explain import explain
from ...core.imaging import IMAGE_EXTS
from ...core.inspector import Check, InspectionResult, ai_check
from ...core.recipe import Recipe
from ...core.services import REQUIRED_ROLE, ROLES, ROLES_FROM, AppContext, ErrorReport, Judged
from ...core.views import ai_view, difference_view
from ...errors import AoiError
from ...times import to_local
from .. import theme
from ..errors import phrase_text, show_error
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..widgets.image_view import ImageView
from .base import (
    QT_TRANSLATE_NOOP,
    Page,
    action_button,
    breakable,
    breakable_names,
    button,
    fill_table,
    make_table,
    sentence_text,
    view_text,
)

if TYPE_CHECKING:
    from ..main_window import MainWindow
    from ..workers import Worker

MODES = [  # the Show combo, in this order; shown through tr()
    QT_TRANSLATE_NOOP("ComparePage", "Side by side"),
    QT_TRANSLATE_NOOP("ComparePage", "Difference heatmap"),
    QT_TRANSLATE_NOOP("ComparePage", "AI score heatmap"),
    QT_TRANSLATE_NOOP("ComparePage", "Defect boxes only"),
]
MODE_SIDE, MODE_DIFF, MODE_AI, MODE_BOXES = range(4)
NO_VERDICT = "—"  # the banner with no result shown
Stored: TypeAlias = (
    "tuple[np.ndarray | None, Judged, InspectionResult | None, list[tuple[ErrorReport, AoiError]]] | ErrorReport"
)
# golden board, why not, result, and the stored files of it that could not be read, each as the dialog's report and the
# note's copy of the error, whose file name may wrap (#245); or why none of it could be read. Each error is already
# logged and alarmed (#247)
# Evaluated: the golden board, the result, why the Golden board cannot be shown, the refusal of a test board it kept
# from being judged, and that refusal's report for the dialog of a run that was asked for, already alarmed (#206, #247)
Evaluated: TypeAlias = (
    "tuple[np.ndarray | None, InspectionResult | None, AoiError | None, AoiError | None, ErrorReport | None]"
)
JUDGED: dict[Judged, str] = {  # why a stored result's golden board is not shown; today's would mislead
    "none": QT_TRANSLATE_NOOP("ComparePage", "This result was judged without a Golden board."),
    "unrecorded": QT_TRANSLATE_NOOP("ComparePage", "This result was saved before results named their Golden board."),
    "missing": QT_TRANSLATE_NOOP("ComparePage", "The Golden board this result was judged against, {file}, is gone."),
    "unreadable": QT_TRANSLATE_NOOP(
        "ComparePage", "The Golden board this result was judged against, {file}, cannot be read."
    ),
    "changed": QT_TRANSLATE_NOOP(
        "ComparePage", "The Golden board this result was judged against, {file}, has changed since."
    ),
}

# The engine names its checks, their sources and rules in English and stores them with the result; the page shows
# them in the UI language. An ROI check is named after the ROI and shows as the engine wrote it.
CHECK_NAMES = {
    "SSIM similarity": QT_TRANSLATE_NOOP("ComparePage", "Similarity (SSIM)"),
    "Changed area %": QT_TRANSLATE_NOOP("ComparePage", "Changed area %"),
    "Difference regions": QT_TRANSLATE_NOOP("ComparePage", "Difference regions"),
    "Alignment inliers": QT_TRANSLATE_NOOP("ComparePage", "Alignment points"),
    "AI anomaly score": QT_TRANSLATE_NOOP("ComparePage", "AI score"),
}
SOURCES = {
    "Compare": QT_TRANSLATE_NOOP("ComparePage", "Golden board"),
    "AI": QT_TRANSLATE_NOOP("ComparePage", "AI model"),
    "ROI": QT_TRANSLATE_NOOP("ComparePage", "ROI"),
}
RULES = {
    "< thr → NG": QT_TRANSLATE_NOOP("ComparePage", "< threshold → NG"),
    "≥ thr → NG": QT_TRANSLATE_NOOP("ComparePage", "≥ threshold → NG"),
    "> thr → NG": QT_TRANSLATE_NOOP("ComparePage", "> threshold → NG"),
    "info only": QT_TRANSLATE_NOOP("ComparePage", "info only"),
}
THRESHOLDS = {  # the recipe's thresholds the panel holds, in its order: field -> its label, shown through tr()
    "anomaly_threshold": QT_TRANSLATE_NOOP("ComparePage", "AI score threshold"),
    "diff_threshold": QT_TRANSLATE_NOOP("ComparePage", "Pixel difference (0-255)"),
    "min_defect_area": QT_TRANSLATE_NOOP("ComparePage", "Minimum defect area (px)"),
    "ssim_min": QT_TRANSLATE_NOOP("ComparePage", "Similarity minimum (SSIM)"),
    "max_diff_regions": QT_TRANSLATE_NOOP("ComparePage", "Allowed difference regions"),
}


def _judging(r: Recipe, res: InspectionResult | None) -> Recipe:
    """`r` as the engine judged the board `res` by it, to compare with another: a value that did not judge the board is
    no change (review). An AI score threshold of 0 is none, as the engine reads it, and judges nothing when the board's
    AI check did not run (off, or no AI model active; #243, #246), nor do an ROI's AI score and name, as no ROI check
    runs then (`Inspector.judge`: an ROI only names the defects in it, by its type); the Golden board comparison's own
    thresholds judge nothing when the board was judged without it (Minimum defect area also sizes the AI model's
    defects: it counts); a disabled ROI, and an ROI's Stage 2 heights and volumes and its side, which nothing reads yet,
    never judge (verification). `res` None, a board still being worked out: `r`'s switches say what judges it."""
    ai, compared = (ai_check(res) == "RAN", res.compare is not None) if res is not None else (r.use_ai, r.use_compare)
    rois = [
        dataclasses.replace(x, height_min=None, height_max=None, volume_min=None, volume_max=None, side="")
        for x in r.rois
        if x.enabled
    ]
    if not ai:
        rois = [dataclasses.replace(x, name="", ai_score=0.0) for x in rois]
    r = dataclasses.replace(r, anomaly_threshold=(r.anomaly_threshold or None) if ai else None, rois=rois)
    if compared:
        return r
    return dataclasses.replace(r, diff_threshold=0, ssim_min=0.0, changed_pct_max=0.0, max_diff_regions=0)


def _as_read(r: Recipe) -> Recipe:
    """`r` as the engine reads it, to tell Save to Recipe a change: an AI score threshold of 0 is none. Unlike
    `_judging`, a value that did not judge the board shown counts, as saving it changes the recipe (S28d)."""
    return dataclasses.replace(r, anomaly_threshold=r.anomaly_threshold or None)


class ComparePage(Page):
    title = QT_TRANSLATE_NOOP("Page", "Compare")
    subtitle = QT_TRANSLATE_NOOP("Page", "Golden board vs. test board, with the metrics behind the verdict")

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        self.test_path: str | None = None
        self.ref_override: str | None = None
        self._views: dict[tuple[int, int], np.ndarray | None] = {}  # (view, pixel difference) -> its picture
        self._res: InspectionResult | None = None
        self.stored: dict[str, Any] | None = None  # the record of the stored result shown; None for a fresh inspection
        self.as_judged: tuple[str, np.ndarray] | None = None  # its golden board, which Re-evaluate keeps (REQ-CMP-003)
        self.golden_seen: tuple[str | None, int, int] | None = None  # today's Golden board file the last run read,
        self.golden_error: AoiError | None = None  # and why the pane could not show it (#176)
        self.golden_state = False  # the pane says there is no Golden board, or why it cannot be opened
        self.record_board_model: str | None = None  # the board model of the record the test board came from, if any
        self.form_revision: tuple[str, int] | None = None  # the board model and recipe revision the form came from
        self.form_recipe: Recipe | None = None  # and that revision's recipe, which Save to Recipe tells a change from
        self._asking = False  # the Save to Recipe sheet is open in place of the panel
        self.shown_board_model: str | None = None  # the header's board model the page last followed (#247)
        self.judge_on_show = False  # the header changed while the page was hidden: judge its board when shown (#247)
        self.judged_by: Recipe | None = None  # the recipe a board inspected here, shown or still worked out, judges by
        self.loaded = False  # the load of a stored result's pictures and maps has ended: Re-evaluate may judge it
        self.tried = False  # the table and the "why" box show the checks the form's thresholds give, not the result's
        self._trying: Worker | None = None  # the re-evaluation running, if any
        self._refocus = False  # the focus waits in the "why" box while Re-evaluate is off, for it to take back (review)
        self._fitted = False

        bar = QHBoxLayout()
        bar.addWidget(button(self.tr("Test Image…"), slot=self.pick_test))
        bar.addWidget(button(self.tr("Use Last Inspected"), slot=self.use_last))
        bar.addWidget(button(self.tr("Reference…"), slot=self.pick_ref))
        bar.addWidget(button(self.tr("Golden Board"), slot=self.use_golden))
        bar.addWidget(QLabel(self.tr("Show:")))
        self.mode = QComboBox()
        self.mode.addItems([self.tr(m) for m in MODES])
        self.mode.currentIndexChanged.connect(self.redraw)
        bar.addWidget(self.mode)
        bar.addStretch(1)
        self.root.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        views = QWidget()
        grid = QGridLayout(views)  # the labels share a row, so one wrapped to two lines never shifts its view down
        grid.setContentsMargins(0, 0, 0, 0)
        self.panes, self.splitter = grid, split  # Defect boxes only gives the Golden board's column away (#248)
        self.ref_label = QLabel(self.tr("Golden board"))
        self.ref_label.setObjectName("muted")
        self.test_label = QLabel(self.tr("Test board"))
        self.test_label.setObjectName("muted")
        self.ref_view = ImageView(placeholder="")
        self.test_view = ImageView(placeholder="")
        self.ref_empty, self.test_empty = EmptyState(self.ref_view), EmptyState(self.test_view)
        self.ref_view.link(self.test_view)  # zoom/pan stay in sync
        self.busy = BusyOverlay(self.test_view, self.tr("Inspecting…"))  # where the result will appear
        self.busy.cancel_button.clicked.connect(self._cancelled)  # at the press, not when the job stops (#172)
        for column, (label, view) in enumerate(((self.ref_label, self.ref_view), (self.test_label, self.test_view))):
            label.setWordWrap(True)  # a long file name wraps rather than widen its pane: the two stay the same width
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)  # each label over its view
            grid.addWidget(label, 0, column)
            grid.addWidget(view, 1, column)
            grid.setColumnStretch(column, 1)
        grid.setRowStretch(1, 1)
        split.addWidget(views)

        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(8, 0, 0, 0)
        self.verdict = QLabel(NO_VERDICT)
        self.verdict.setStyleSheet(theme.verdict_style("INFO"))
        self.verdict.setMinimumHeight(theme.BANNER_H)
        pl.addWidget(self.verdict)
        self.note = QLabel()  # a stored result's versions, what changed since, and AOI-CMP-001 when its maps are gone
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.note.hide()
        pl.addWidget(self.note)
        self.metrics = make_table(
            [
                self.tr("Check"),
                self.tr("Source"),
                self.tr("Value"),
                self.tr("Threshold"),
                self.tr("Rule"),
                self.tr("Result"),
            ],
            sortable=False,
        )
        hh = self.metrics.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)  # a stretched Check column shrank to "C…"
        self.metrics.setWordWrap(True)
        self.decision = QWidget()  # the decision table and the "why" box, where the checks tried appear
        dl = QVBoxLayout(self.decision)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(self.metrics, 1)
        self.why = QTextEdit()
        self.why.setReadOnly(True)
        self.why.setMaximumHeight(150)
        self.why.setMinimumHeight(theme.WHY_MIN_H)  # at 1600 x 900 the panel is too short for all of it at full height
        dl.addWidget(self.why)
        pl.addWidget(self.decision, 2)
        self.try_busy = BusyOverlay(self.decision, self.tr("Re-evaluating…"))  # over both: Cancel fits at least size
        self.try_busy.cancel_button.clicked.connect(self._cancel_tried)  # the stored checks again (REQ-SET-021, review)

        self.tryout = QGroupBox(self.tr("Try other thresholds (nothing is saved until you press Save to Recipe)"))
        f = QFormLayout(self.tryout)
        self.ai_thr = self.ai_threshold_field(self.tr("Override the AI model's value {value}"), own_row=True)
        self.diff_thr = QSpinBox()
        self.diff_thr.setRange(1, 255)
        self.min_area = QSpinBox()
        self.min_area.setRange(1, 100000)
        self.ssim_min = QDoubleSpinBox()
        self.ssim_min.setRange(0, 1)
        self.ssim_min.setSingleStep(0.01)
        self.max_regions = QSpinBox()
        self.max_regions.setRange(0, 1000)
        f.addRow(self.tr(THRESHOLDS["anomaly_threshold"]), self.ai_thr)
        f.addRow(self.ai_thr.tick_row)  # the sketch's label, naming the value: beside the field it widens the window
        f.addRow(self.ai_thr.note)  # why no calibrated value is named, as wide as the panel
        f.addRow(self.tr(THRESHOLDS["diff_threshold"]), self.diff_thr)
        f.addRow(self.tr(THRESHOLDS["min_defect_area"]), self.min_area)
        f.addRow(self.tr(THRESHOLDS["ssim_min"]), self.ssim_min)
        f.addRow(self.tr(THRESHOLDS["max_diff_regions"]), self.max_regions)
        self.ai_thr.changed.connect(self._drop_tried)  # what was tried no longer applies
        self.ai_thr.ticking.connect(self._show_calibration)  # an AI model trained since the value was named
        for field in (self.diff_thr, self.min_area, self.ssim_min, self.max_regions):
            field.valueChanged.connect(self._drop_tried)
        row = QHBoxLayout()
        self.would_be = QLabel()  # "Would be: ▲ WARN" beside Re-evaluate once a stored result is judged again (sketch)
        self.would_be.hide()
        row.addWidget(self.would_be)
        self.act_try = self.action(self.tr("Re-evaluate"), "Ctrl+R", self.re_evaluate)
        self.btn_try = action_button(self.act_try, show_key=False)
        row.addWidget(self.btn_try)
        self.act_save = self.action(self.tr("Save to Recipe"), "Ctrl+S", self.save_recipe)
        self.btn_save = action_button(self.act_save, "primary", show_key=False)  # the page's one blue primary
        row.addWidget(self.btn_save)
        f.addRow(row)
        pl.addWidget(self.tryout)
        pl.addWidget(self._save_sheet())
        self.ai_thr.changed.connect(self._sync_save)  # Save to Recipe is on while a threshold differs from the recipe
        for field in (self.diff_thr, self.min_area, self.ssim_min, self.max_regions):
            field.valueChanged.connect(self._sync_save)
        split.addWidget(panel)
        split.setSizes([800, 920])  # the decision table shows all six columns at 1920 x 1080
        self.root.addWidget(split, 1)

    def _save_sheet(self) -> QGroupBox:
        """Save to Recipe's confirmation, shown in place of the panel: inline, never a dialog over a dialog (sketch). It
        lists each threshold that changes, before -> after, and asks for a reason, without which Save Revision is off;
        Cancel, or Esc in the sheet, closes it. Save Revision is a plain button: the page keeps one blue primary."""
        self.sheet = QGroupBox(self.tr("Save to Recipe"))
        sl = QVBoxLayout(self.sheet)
        self.sheet_heading, self.sheet_changes, self.sheet_note = QLabel(), QLabel(), QLabel()
        self.sheet_note.setObjectName("muted")
        for label in (self.sheet_heading, self.sheet_changes, self.sheet_note):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)  # a board model's name is never read as markup
            sl.addWidget(label)
        form = QFormLayout()
        self.reason = QLineEdit()
        self.reason.textChanged.connect(self._sync_save)
        self.reason.returnPressed.connect(self._confirm_save)
        form.addRow(self.tr("Reason (required)"), self.reason)
        sl.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = button(self.tr("Cancel"), slot=self._close_sheet)
        row.addWidget(self.btn_cancel)
        self.btn_confirm = button(self.tr("Save Revision"), slot=self._confirm_save)  # named with its revision on open
        row.addWidget(self.btn_confirm)
        sl.addLayout(row)
        esc = QAction(self.sheet)
        esc.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        esc.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)  # Esc in the sheet closes it
        esc.triggered.connect(self._close_sheet)
        self.sheet.addAction(esc)
        self.sheet.hide()
        return self.sheet

    # --- inputs ------------------------------------------------------------------
    def set_test(self, path: str) -> None:
        self._close_sheet()  # any board opened, the one shown too, closes it with its reason, as Cancel does
        self.test_path, self.as_judged, self.record_board_model = path, None, None  # a file: the header's board model
        self.test_empty.hide()
        self._fitted = False
        self.run()

    def pick_test(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        f, _ = QFileDialog.getOpenFileName(
            self, self.tr("Test image"), "", self.tr("Images ({extensions})").format(extensions=exts)
        )
        if f:
            self.set_test(f)

    def use_last(self) -> None:
        if not (last := self.shell.last_inspected):
            return
        self.show_golden_pane()
        if last[2] is not None:
            self.show_stored(last[2])  # the record, as it was decided (REQ-INSP-009)
        else:
            self.set_test(last[0])  # a preview from AI Model Test is not recorded: inspected again

    def pick_ref(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        f, _ = QFileDialog.getOpenFileName(
            self, self.tr("Reference image"), "", self.tr("Images ({extensions})").format(extensions=exts)
        )
        if f:
            self.ref_override = f
            self.show_golden_pane()
            self.run()

    def use_golden(self) -> None:
        self.ref_override = self.as_judged = None  # today's golden board
        self.show_golden_pane()
        self.run()

    def show_golden_pane(self) -> None:
        """A Golden board or a reference asked for ("Compare with Golden board ›", Use Last Inspected, Golden Board,
        Reference…): Defect boxes only, which hides its pane, gives way to Side by side; any other view stays (#248)."""
        if self.mode.currentIndex() == MODE_BOXES:
            self.mode.setCurrentIndex(MODE_SIDE)  # redraw shows the pane and its label, and fits the board to its half

    def _load_recipe_into_form(self) -> Recipe | None:
        """The form takes the header's board model's recipe, which is returned; None with no board model. A Save to
        Recipe sheet open closes: what it lists was tried on the recipe before."""
        self._drop_tried()  # tried with the recipe the form came from
        self.form_recipe = None
        self._close_sheet()
        if not self.board_model:
            return None
        rev, r = self.ctx.recipe(self.board_model)
        self.form_revision = (self.board_model, rev)  # on_show loads the form again once another revision is saved
        self.ai_thr.set_override(r.anomaly_threshold)
        self.diff_thr.setValue(r.diff_threshold)
        self.min_area.setValue(r.min_defect_area)
        self.ssim_min.setValue(r.ssim_min)
        self.max_regions.setValue(r.max_diff_regions)
        self.form_recipe = r
        self._sync_save()
        return r

    def _show_calibration(self) -> None:
        """The calibrated value the AI score threshold names (REQ-TRN-015): on a stored result, that of the AI model
        that judged it, which Re-evaluate applies (ADR 0006 decision 2); else the active AI model's, which judges a
        board inspected here, also on a stored result judged with the AI check off, whose record names the AI model
        active then, which judged nothing (#246)."""
        if self.stored is not None and self.stored["model_uuid"] and ai_check(self.res) == "RAN":
            stored = self.stored
            self.show_calibrated(self.ai_thr, stored["board_model"], stored["model_uuid"], stored["model_version"])
        else:
            self.show_calibrated(self.ai_thr, self.board_model)

    def _form_recipe(self, board_model: str, saved: Recipe | None = None) -> Recipe:
        """The board model's recipe (`saved`, when read already) with the thresholds from the form."""
        r = copy.deepcopy(self.ctx.recipe(board_model)[1] if saved is None else saved)
        r.anomaly_threshold = self.ai_thr.override()
        r.diff_threshold = self.diff_thr.value()
        r.min_defect_area = self.min_area.value()
        r.ssim_min = self.ssim_min.value()
        r.max_diff_regions = self.max_regions.value()
        return r

    # --- evaluate ----------------------------------------------------------------
    def re_evaluate(self) -> None:
        """Re-evaluate (Ctrl+R, Engineer and Admin): a stored result is judged again with the form's thresholds from its
        stored maps on the pool thread, without the AI model (`AppContext.re_evaluate`, REQ-CMP-005), under a busy
        indicator over the decision table once it takes a second (REQ-SET-021), and "Would be" shows the verdict they
        give while the banner keeps the stored one (ADR 0006 decision 3); a board not stored is inspected again with
        them. The service refuses the header's board model's thresholds for another's result. The focus rule: a focus
        on Re-evaluate or on any other control the run turns off waits in the "why" box under the indicator, one Tab
        before Cancel once that shows, and goes to Re-evaluate when the run ends if it is still there (`_sync_roles`);
        Qt would pass it on to the next control in the Tab order that is on, the header's board model list, where Down
        would pick another board model (review)."""
        if self.stored is None:
            self.run()
            return
        if (bm := self.checked_board_model()) is None:
            return
        focus: QWidget | None = self.window().focusWidget()  # the window's, before anything is turned off (review)
        self._drop_tried()
        recipe, uuid = self._form_recipe(bm), self.stored["uuid"]
        self._trying = self.run_in_background(
            self.ctx.re_evaluate, uuid, recipe, on_result=self._on_tried, busy=self.try_busy,
            on_error=self._refused,  # a refusal holds no worker past its end (#132), nor its indicator (verification)
        )  # fmt: skip
        self._sync_roles()  # Re-evaluate is off while it runs: a second press would start the same job (REQ-SET-021)
        if focus is not None and not focus.isEnabled():  # on Re-evaluate, or on another control the run turned off
            self.why.setFocus(Qt.FocusReason.OtherFocusReason)  # under the indicator, one Tab before Cancel once shown
            self._refocus = True

    def _not_trying(self) -> None:
        """No re-evaluation runs any more: its worker is let go (#132) and Re-evaluate is on again, with the focus it
        had when the run started if that is still in the "why" box, where the run put it (`_sync_roles`). Its answer, a
        refusal and `_drop_tried` call this before the indicator hides, so a focus on its Cancel, which Qt would then
        pass on to the AI score threshold's tick, goes to Re-evaluate too, or, once an Operator's sign-in hides the
        panel, to the "why" box, not on to the header's board model (second verification). The focus read is the
        window's, which it keeps while another window is in front, when `hasFocus()` is False for every control: given
        to Re-evaluate then, it is there when the window is in front again (review)."""
        held = self.window().focusWidget() is self.try_busy.cancel_button
        self._trying = None
        self._sync_roles()
        if held and self.act_try.isEnabled():
            self.btn_try.setFocus(Qt.FocusReason.OtherFocusReason)
        elif held:
            self.why.setFocus(Qt.FocusReason.OtherFocusReason)

    def _refused(self, _exc: BaseException) -> None:
        """A refusal ends the run as its answer does (`_on_tried`): the indicator goes at once, not at the job's end,
        which a loaded pool thread may signal after the dialog, Cancel still shown meanwhile to take the focus and pass
        it on to the AI score threshold's tick as it hides (third verification)."""
        self._not_trying()  # first: a focus on Cancel goes to Re-evaluate before Cancel hides
        self.try_busy.finish()

    def _cancel_tried(self) -> None:
        """Cancel on the busy indicator: the stored checks again, and the focus on Re-evaluate, on again (verification).
        Cancel held it, pressed by key or click, and Qt passed it on as Cancel hid, to the AI score threshold's tick or
        field, where a second Space would set the tick."""
        self._drop_tried()
        if self.act_try.isEnabled():
            self.btn_try.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_tried(self, res: InspectionResult) -> None:
        """The checks and the explanation the thresholds tried give; the banner keeps the stored verdict."""
        self._not_trying()
        self.try_busy.finish()  # at the answer, not at the job's end, which a loaded pool thread may signal later
        self.tried = True
        self.would_be.setText(self.tr("Would be: {verdict}").format(verdict=theme.verdict_label(res.verdict)))
        self.would_be.setStyleSheet(theme.verdict_mark_style(res.verdict))  # beside the buttons, never one of them
        self.would_be.show()
        self._show_checks(res, tried=True)

    def _drop_tried(self) -> None:
        """Back to the checks of the result shown once what was tried no longer applies: a threshold or the recipe
        changes, another run starts or another result shows, the board model changes, an Operator signs in or Cancel is
        pressed on the busy indicator. A re-evaluation still running is stopped and its indicator goes, so its answer
        never shows, and its error, logged and alarmed, shows no dialog (#206)."""
        if (trying := self._trying) is not None:
            self._not_trying()  # first: a focus on Cancel goes back before Cancel hides (second verification)
            if trying is self._bg:
                trying.stop()
                self.try_busy.finish()  # at once, not when the pool thread lets go of it
        self.would_be.hide()
        if self.tried and self.res is not None:
            self._show_checks(self.res)
        self.tried = False

    def run(self) -> None:
        """Load the reference and inspect the test image on a pool thread (REQ-SET-021); the form is read here."""
        self._start(quiet=False)

    def _start(self, quiet: bool) -> None:
        """`quiet`: run because the page was shown, not asked for: a Golden board that still cannot be read is said on
        its pane only, with no dialog or alarm (#176 review), and so is a board no check can judge (#247)."""
        self.judge_on_show = False  # this run replaces the one a header change left for on_show
        bm = self.board_model
        if not bm:
            return
        if self.test_path and self.record_board_model not in (None, bm):  # a record's board is judged under its own
            file, own = Path(self.test_path).name, self.record_board_model  # board model, never the header's (#172)
            self.error(AoiError("AOI-CMP-005", tried=bm, file=file, judged=own))
            return
        self._drop_tried()
        self.stored = None  # a fresh inspection with the form's thresholds, not a stored result
        self._show_calibration()
        self.note.hide()
        if self.test_path:
            self.test_label.setText(self.tr("Test board: {file}").format(file=breakable(Path(self.test_path).name)))
        recipe: Recipe | None = None  # an Operator's board is judged by the recipe
        self.judged_by = None  # only the Golden board to read
        if self.test_path:  # what judges it, which an Operator's sign-in holds against the recipe then (review)
            saved = self.ctx.recipe(bm)[1]
            recipe = None if self.ctx.role == "Operator" else self._form_recipe(bm, saved)
            self.judged_by = saved if recipe is None else recipe
        self._sync_roles()  # Re-evaluate, waiting for a stored result's maps, now inspects again
        judged = self.as_judged[1] if self.as_judged and not self.ref_override else None
        if not self.ref_override:
            self.golden_seen = self.golden_board_stamp()
        self.run_in_background(
            self._evaluate, bm, self.test_path, self.ref_override, recipe, judged, quiet,
            on_result=self._on_evaluated, busy=self.busy if self.test_path else None,
            on_error=self._not_inspected,
        )  # fmt: skip

    def _evaluate(
        self,
        board_model: str,
        test_path: str | None,
        ref_path: str | None,
        recipe: Recipe | None,
        ref: np.ndarray | None,
        quiet: bool,
    ) -> Evaluated:
        """Pool thread: files and the engine only, never a widget. `ref` is a stored result's golden board as judged.
        Today's Golden board gone or damaged comes back as the error to say on its pane, not raised (it was a dialog
        at every start, #176), and is alarmed once (#195); a test board it keeps from being judged comes back with its
        AOI-INSP-009 refusal and no result, so the pane says why whether or not a board was to be judged (#176
        review); so does AOI-INSP-010, a board model with nothing that can judge it (#247). A refusal is logged here,
        and alarmed when the run was asked for (not `quiet`), so a run cancelled or replaced loses none (#206)."""
        golden_error = refused = None
        if ref is None and ref_path:
            ref = self.ctx.load_image(ref_path)
        elif ref is None and test_path is None and (golden := self.ctx.reference_image(board_model)):
            try:
                ref = self.ctx.load_image(golden)
            except AoiError as e:
                golden_error = e
        elif ref is None and test_path is not None:
            try:
                ref = self.ctx.inspector(board_model).reference
            except AoiError as e:
                if e.code != "AOI-INSP-009":
                    raise
                refused, golden_error = e, e.__cause__ if isinstance(e.__cause__, AoiError) else e
        if golden_error is not None:  # logged, and alarmed once per board model, file and code (#195)
            self.ctx.golden_board_unreadable(board_model, golden_error)
        test = self.ctx.load_image(test_path) if test_path and refused is None else None
        try:
            res = self.ctx.inspect(board_model, test, recipe, reference=ref) if test is not None else None
        except AoiError as e:  # no check can judge the board under this board model: said as AOI-INSP-009 is (#247)
            if e.code != "AOI-INSP-010":
                raise
            res, refused = None, e
        report = None
        if refused is not None and not quiet:  # asked for: the refusal's alarm, as on Inspection, and its dialog
            report = self.ctx.report_error(refused, self.title)
        elif refused is not None:  # not asked for: logged with its trace, with no dialog or alarm (#247)
            trace = (type(refused), refused, refused.__traceback__)
            self.ctx.log.warning("compare.not_inspected", exc_info=trace, extra={"code": refused.code})
        return ref, res, golden_error, refused, report

    def _on_evaluated(self, out: Evaluated) -> None:
        ref, res, self.golden_error, refused, report = out
        self._show_reference(ref)
        if refused is not None and refused.code != "AOI-INSP-009":  # nothing can judge it: banner and pane say so
            self._not_inspected(refused)
        elif refused is not None:  # the board was not judged: no verdict, table or picture of the board before
            self._clear_result()
            what = self.tr("{file} was not inspected: its Golden board cannot be opened.").format(
                file=breakable(Path(self.test_path or "").name)
            )
            self.test_empty.show_state(self.tr("Board not inspected"), what)
        if report is not None:  # asked for: the refusal's dialog, as on Inspection
            show_error(self, report)
        if res is not None:
            self.test_empty.hide()  # a fresh result: no "Board picture no longer stored" over it (#172)
            self._show_result(res)
            self.redraw()

    def _show_reference(self, ref: np.ndarray | None, judged: Judged | None = None) -> None:
        """The golden board pane: a reference picked by hand, a stored result's golden board as judged (`judged` says
        whether it is shown, and why not, with the next step), or the board model's golden board today."""
        named = judged in ("missing", "unreadable", "changed")
        stored = self.stored["reference_path"] if self.stored and named else None
        recorded = self.as_judged[0] if self.as_judged else stored
        if self.ref_override:
            self.ref_label.setText(self.tr("Reference: {file}").format(file=breakable(Path(self.ref_override).name)))
        elif recorded:
            self.ref_label.setText(
                self.tr("Golden board as judged: {file}").format(file=breakable(Path(recorded).name))
            )
        elif ref is not None or judged in JUDGED or self.golden_error is not None:
            self.ref_label.setText(self.tr("Reference: Golden board"))
        else:
            self.ref_label.setText(self.tr("Reference: none set"))
        self.ref_view.set_image(ref)
        self.golden_state = False
        if judged is not None and judged in JUDGED:
            what = self.tr(JUDGED[judged]).format(file=breakable(Path(recorded or "").name))
            if self.record_board_model and self.ctx.reference_image(self.record_board_model):
                do = self.tr(
                    "The verdict and the decision table are the stored ones; press Re-evaluate › to inspect the board"
                    " again with today's Golden board."
                )
            else:  # none today either: Re-evaluate judges the board without one, so the sentence promises none
                do = self.tr(
                    "The verdict and the decision table are the stored ones; press Re-evaluate › to inspect the board"
                    " again from its image file."
                )
            self.ref_empty.show_state(
                self.tr("Golden board not available"), f"{what} {do}", self.tr("Re-evaluate ›"), self.run
            )
        elif ref is None and (self.golden_error is not None or self.board_model):
            self.golden_state = True
            self._show_golden_state()
        else:
            self.ref_empty.hide()

    def _show_golden_state(self) -> None:
        """Why the pane has no Golden board, with the next step for the role signed in now: the first is built at
        start-up, before anyone signs in, so on_show() builds it again (#176 review)."""
        if self.golden_error is not None:
            self.ref_empty.show_state(*self.golden_board_unreadable(self.golden_error))
        else:
            step = self.empty_step(self.tr("Train an AI model on Training."), "Training")
            heading = self.tr("No Golden board for {board_model} yet").format(board_model=self.board_model)
            self.ref_empty.show_state(heading, *step)

    def _show_result(self, r: InspectionResult) -> None:
        """The verdict, the decision table with its failing rows highlighted, and the explanation, from `r`'s checks."""
        self.res = r
        self.verdict.setText(theme.verdict_label(r.verdict))
        self.verdict.setStyleSheet(theme.verdict_style(r.verdict))
        self._show_checks(r)

    def _show_checks(self, r: InspectionResult, tried: bool = False) -> None:
        """The decision table and "why" box of `r`: the result shown, or (`tried`) what the thresholds tried give it."""
        rows, colors = [], []
        for c in r.checks:
            name, source, rule = self._check_text(c)
            rows.append([name, source, float(c.value), float(c.threshold), rule, c.verdict])
            colors.append(None if c.verdict in ("OK", "INFO") else theme.VERDICT_COLORS[c.verdict])
        rows.append(
            [
                self.tr("Inspection time (ms)"),
                self.tr("System"),
                float(r.elapsed_ms),
                1000.0,
                self.tr("spec < 1 s"),
                "OK" if r.elapsed_ms < 1000 else "WARN",
            ]
        )
        colors.append(None)
        fill_table(self.metrics, rows, colors)
        self.why.setHtml(self._explain(r, tried))

    def show_stored(self, inspection_id: int) -> None:
        """A stored result as it was decided, never inspected again (REQ-CMP-003): the verdict, table and explanation
        from the record at once (REQ-INSP-009); the pictures and the stored maps follow from the pool thread."""
        rec = self.ctx.inspection(inspection_id)
        res = self.ctx.inspection_result(inspection_id)
        if rec is None or res is None:
            file = Path(rec["image_path"]).name if rec else "?"
            self.error(AoiError("AOI-CMP-002", id=inspection_id, file=file))
            return
        self._drop_tried()
        self._close_sheet()  # any board opened, the one shown too, closes it with its reason, as Cancel does
        self.stored, self.test_path, self.ref_override, self.as_judged = rec, rec["image_path"], None, None
        self.golden_error, self.golden_state = None, False  # its pane shows the golden board as judged, not today's
        self.record_board_model = rec["board_model"]  # Re-evaluate judges the board under it (#172)
        self._fitted = self.loaded = False
        self.judged_by = None  # judged as it was decided: an Operator's sign-in never judges it again
        self._sync_roles()  # Re-evaluate waits for its pictures and maps
        self.judge_on_show = False  # a stored result is never inspected again unasked
        self.test_empty.hide()
        self.test_view.set_image(None)  # the board shown before goes at once, not when this one's picture arrives,
        self.ref_view.set_image(None)  # and so do its golden board and boxes, and why that pane had none (#247)
        self.ref_empty.hide()
        self.ref_label.setText(self.tr("Golden board"))
        name = breakable(Path(rec["image_path"]).name)  # the labels over the pictures wrap a long name (#245)
        self.test_label.setText(self.tr("Test board: {file} (stored result)").format(file=name))
        self._show_result(res)
        self._show_calibration()
        self._show_note(rec)
        self.run_in_background(self._load_stored, rec, inspection_id, on_result=self._on_stored_loaded)

    def _load_stored(self, rec: dict[str, Any], inspection_id: int) -> Stored:
        """Pool thread: the golden board the result was judged against (REQ-CMP-003), the result with its stored maps,
        and its stored overlay as the picture, aligned to that golden board as judged (the board's own file is not);
        never a widget. A map or overlay that cannot be read takes away only itself, never the golden board; when none
        of it can be read (a database another program holds, say), the report comes back alone. Each error is logged
        and alarmed here, so a load a newer one replaced loses none, and comes back for the panes and the dialog,
        which so name the one code (#247), beside a copy for the note whose file name may wrap (breakable_names,
        #245)."""
        unread: list[AoiError] = []
        try:
            ref, judged = self.ctx.judged_reference(inspection_id)
            try:
                res = self.ctx.inspection_result(inspection_id, with_maps=True)
            except AoiError as e:  # AOI-CMP-003: the heat views show the picture alone
                if e.code != "AOI-CMP-003":
                    raise
                res = self.ctx.inspection_result(inspection_id)
                unread.append(e)
        except Exception as exc:  # reported as a failed job is, but here: a busy database is AOI-SET-013 (#195)
            return self.ctx.report_error(exc, self.title)
        path = rec["overlay_path"]
        if res is not None and path and Path(path).is_file():
            try:
                res.image = self.ctx.load_image(path)
            except AoiError as e:  # a stored file, not one to save again with an image tool (AOI-INSP-004)
                picture = AoiError(
                    "AOI-CMP-006", detail=str(e), file=Path(path).name, error_code=e.code, error_title=e.title
                )
                picture.__cause__ = e  # the log keeps the reader's error and its trace
                unread.append(picture.with_traceback(e.__traceback__))
        return ref, judged, res, [(self.ctx.report_error(e, self.title), breakable_names(e)) for e in unread]

    def _on_stored_loaded(self, out: Stored) -> None:
        if self.stored is None:  # a fresh run or a board model change came first: nothing of it shows
            return
        self.loaded = True  # read, or not: Re-evaluate no longer stops the load
        self._sync_roles()  # Re-evaluate on, with a focus that waited for it in the "why" box
        if isinstance(out, ErrorReport):  # none of its pictures: the verdict and table stand, and each pane says why
            why = f"{out.code} {phrase_text(out.what)}"  # the Golden board pane's next step is the dialog's
            self.ref_empty.show_state(self.tr("Golden board not shown"), f"{why} {phrase_text(out.action)}")
            self._no_board_picture(self.tr("Board picture not shown"), why)
            show_error(self, out)
            return
        ref, judged, res, unread = out
        if res is None:
            return
        self.as_judged = (self.stored["reference_path"], ref) if ref is not None else None
        self.golden_error = None  # the pane shows the stored result's golden board now, not today's
        self._show_reference(ref, judged)
        self.res = res  # the table stays as show_stored filled it
        if res.image is None:  # its overlay was deleted by hand, or cannot be read: the verdict and the table stand
            self._no_board_picture(self.tr("Board picture no longer stored"))
        self.redraw()
        # after the panes are drawn, so the dialog names the file beside them; the note keeps it, the name breakable
        # (#245), while the dialog, the log and the alarm keep the name as it is
        for report, shown in unread:
            self.note.setText(f"{self.note.text()} {report.code} {phrase_text(shown.what)}")
            show_error(self, report)

    def _no_board_picture(self, heading: str, why: str = "") -> None:
        """The test pane of a stored result without its picture: `why`, that the verdict and the table stand, and
        Re-evaluate."""
        sentence = self.tr(
            "The verdict and the decision table are the stored ones; press Re-evaluate › to inspect the board again"
            " from its image file."
        )
        self.test_empty.show_state(heading, f"{why} {sentence}".strip(), self.tr("Re-evaluate ›"), self.run)

    def _show_note(self, rec: dict[str, Any]) -> None:
        """One line under the verdict: when the result was judged and with which versions, what has changed since
        (REQ-CMP-003), and AOI-CMP-001 when its maps are gone."""
        bm = rec["board_model"]
        line = self.tr("Stored result of {time}: AI model {model}, recipe revision {revision}, view {view}.")
        then, view = rec["model_version"] or self.tr("none"), view_text(rec["view"]) if rec["view"] else ""
        parts = [line.format(time=to_local(rec["time"]), model=then, revision=rec["recipe_rev"], view=view)]
        model, recipes = self.ctx.active_model(bm), self.ctx.recipe_history(bm)  # registry rows: no weights loaded
        now = (str(model["uuid"]) if model else None, recipes[0]["uuid"] if recipes else None)
        if now != (rec["model_uuid"], rec["recipe_uuid"]):
            moved = self.tr("Since then the board model moved to AI model {model} and recipe revision {revision}.")
            version, revision = model["version"] if model else self.tr("none"), recipes[0]["revision"] if recipes else 0
            parts.append(moved.format(model=version, revision=revision))
        golden = self.ctx.reference_image(bm)
        if rec["reference_path"] and golden != rec["reference_path"]:  # an Engineer or a training run set another
            name = breakable(Path(golden).name) if golden else self.tr("none")
            parts.append(self.tr("The board model's Golden board is now {file}.").format(file=name))
        if not any(p and Path(p).is_file() for p in (rec["diff_map_path"], rec["ai_map_path"])):
            name = breakable(Path(rec["image_path"]).name)  # shown only, never raised or logged, so it may wrap
            e = AoiError("AOI-CMP-001", file=name, days=self.ctx.settings.map_retention_days_ok)
            parts.append(f"{e.code} {phrase_text(e.what)} {phrase_text(e.action)}")
        self.note.setText(" ".join(parts))
        self.note.show()

    def _check_text(self, c: Check) -> tuple[str, str, str]:
        """A check's name, source and rule in the UI language (CHECK_NAMES, SOURCES, RULES)."""
        name = self.tr(CHECK_NAMES[c.name]) if c.name in CHECK_NAMES else c.name
        return name, self.tr(SOURCES.get(c.source, c.source)), self.tr(RULES.get(c.rule, c.rule))

    def _explain(self, r: InspectionResult, tried: bool = False) -> str:
        """The "why" box (REQ-CMP-004; sketch docs/sketches/compare-decision-table.md of PR #79): a heading with the
        verdict, then the plain-word sentences of `explain` as bullets, the deciding checks first, each in the UI
        language, a stored result's notes in the past tense; every value is escaped, so none is read as markup. With
        `tried`, the verdict the thresholds tried would give, and the AI check off said of their recipe (#246)."""
        heading = self.tr("Why this board is {verdict}:").format(verdict=r.verdict)
        if tried:
            heading = self.tr("Why this board would be {verdict} with these thresholds:").format(verdict=r.verdict)
        sentences = explain(r, stored=self.stored is not None, tried=tried)  # tried: the board keeps the stored boxes
        return "<br>".join(
            [f"<b>{html.escape(heading)}</b>", *(f"• {html.escape(sentence_text(t))}" for t in sentences)]
        )

    def redraw(self) -> None:
        """The view chosen under Show: the test board's picture for it, with a labelled box per defect, beside the
        Golden board pane with a dashed box per defect; Defect boxes only hides that pane, so the test board and its
        boxes take the width of both (REQ-CMP-002, #248)."""
        alone = self.mode.currentIndex() == MODE_BOXES  # with or without a result: the panes follow the view chosen
        if alone != self.ref_view.isHidden():  # the test board's pane changes width: the board is fitted to it again
            self.ref_label.setHidden(alone)
            self.ref_view.setHidden(alone)
            self.panes.setColumnStretch(0, 0 if alone else 1)  # a hidden column with a stretch keeps its half
            self.panes.activate()  # now, not at the next event: the fit below needs the pane's new width
            self.splitter.refresh()
            self._fitted = False
        r = self.res
        if r is None or r.image is None:  # a stored result whose picture is gone: no boxes in the air
            return
        self.test_view.set_image(self._view_image(r, self.mode.currentIndex()), keep_view=self._fitted)
        self._fitted = True
        self.ref_view.clear_overlays()  # the Golden board's dashed boxes, drawn anew with the test board's
        for d in r.defects:
            sev = taxonomy.BY_NAME.get(d.type, taxonomy.ANOMALY).severity
            color = theme.SEVERITY_COLORS.get(sev, theme.NG_COLOR)
            self.test_view.add_box(d.x, d.y, d.w, d.h, color, f"{d.no} {d.type}")
            self.ref_view.add_box(d.x, d.y, d.w, d.h, color, f"{d.no}", dashed=True)

    @property
    def res(self) -> InspectionResult | None:
        """The result shown; showing another drops the heat views drawn for this one."""
        return self._res

    @res.setter
    def res(self, r: InspectionResult | None) -> None:
        if r is not self._res:
            self._views = {}
        self._res = r

    def _view_image(self, r: InspectionResult, mode: int) -> np.ndarray | None:
        """The picture of a view: the board, or the board under a heat map (aoi/core/views.py), drawn once per view and
        pixel difference for the result shown, so that switching back to a view only shows it again (REQ-CMP-002)."""
        if mode not in (MODE_DIFF, MODE_AI):
            return r.image
        key = (mode, self.diff_thr.value() if mode == MODE_DIFF else 0)
        if key not in self._views:  # one picture per view: one drawn at another pixel difference goes
            self._views = {k: v for k, v in self._views.items() if k[0] != mode}
            self._views[key] = difference_view(r, key[1]) if mode == MODE_DIFF else ai_view(r)
        view = self._views[key]
        return r.image if view is None else view

    def save_recipe(self) -> None:
        """Save to Recipe (Ctrl+S, Engineer and Admin; REQ-CMP-005): the sheet, in place of the panel, lists each
        threshold the form holds otherwise than the recipe, before -> after, and asks for a reason; nothing is stored
        until Save Revision (sketch docs/sketches/compare-decision-table.md). Off while nothing differs."""
        if not self._may_save():
            roles = ROLES_FROM[REQUIRED_ROLE["save_recipe"]]
            self.error(AoiError("AOI-USR-001", what=QT_TRANSLATE_NOOP("Errors", "Changing recipes"), roles=roles))
            return
        if (bm := self.checked_board_model()) is None or not (changes := self._changes()):
            return
        revision = (self.form_revision[1] if self.form_revision else 0) + 1  # the revision the save will make
        line = self.tr("{threshold}: {before} → {after}")
        heading = self.tr("Save these thresholds as revision {revision} of the recipe of {board_model}?")
        self.sheet_heading.setText(heading.format(revision=revision, board_model=breakable(bm)))  # wraps (#245)
        shown = [(self.tr(THRESHOLDS[k]), self._shown(k, was, bm), self._shown(k, now, bm)) for k, was, now in changes]
        self.sheet_changes.setText("\n".join(line.format(threshold=t, before=b, after=a) for t, b, a in shown))
        note = self.tr(
            "Boards inspected after the save are judged by revision {revision}; stored results keep their verdicts."
        )
        self.sheet_note.setText(note.format(revision=revision))
        self.btn_confirm.setText(self.tr("Save Revision {revision}").format(revision=revision))
        self._asking = True
        self.reason.clear()
        self._sync_roles()
        self.reason.setFocus(Qt.FocusReason.OtherFocusReason)

    def _changes(self) -> list[tuple[str, Any, Any]]:
        """Each threshold the form holds otherwise than the recipe it came from, as the engine reads them (`_as_read`):
        the recipe field, the recipe's value and the form's."""
        if (saved := self.form_recipe) is None:
            return []
        was, now = _as_read(saved), _as_read(self._form_recipe(saved.board_model, saved))
        return [(k, getattr(was, k), getattr(now, k)) for k in THRESHOLDS if getattr(was, k) != getattr(now, k)]

    def _shown(self, field: str, value: object, board_model: str) -> str:
        """A threshold's value as the sheet lists it as it opens: none of the recipe's own is what the saved revision
        judges by, read from `board_model`'s active AI model, not from the panel, which names the AI model of when
        Compare was shown, or of a stored result: "the AI model's calibrated value" while its calibration can be read,
        else "none", as the audit entry of the save then names no threshold; a number shows as its field does, or with
        every decimal the recipe holds where the field shows fewer."""
        if value is None:
            try:
                named = self.ctx.calibrated_threshold(board_model) is not None
            except AoiError:  # AOI-TRN-012: a calibration that cannot be read names no value
                named = False
            return self.tr("the AI model's calibrated value") if named else self.tr("none")
        if isinstance(value, float):
            places = self.ai_thr.field.decimals() if field == "anomaly_threshold" else self.ssim_min.decimals()
            exact = np.format_float_positional(value, trim="-")  # shortest that reads back the same, never 1e-05
            return f"{value:.{places}f}" if round(value, places) == value else exact
        return str(value)

    def _confirm_save(self) -> None:
        """Save Revision, or Enter in the reason: the form's thresholds on the recipe the sheet listed them against,
        stored through AppContext as the next revision with its audit entry of before, after, user, time and reason
        (REQ-CMP-005, REQ-LOG-004). A refusal (AOI-USR-001 for a role that may not save, say) is the coded dialog, and
        the sheet stays with its reason; a revision saved since the sheet opened closes it with AOI-RCP-004, nothing
        stored. Inspection and the Recipe Editor take the revision up as they do one the Recipe Editor saves: at the
        next board, and when the editor is shown again."""
        reason, saved = self.reason.text().strip(), self.form_recipe
        if not (self._asking and reason) or saved is None:
            return
        if (moved := self._take_up_revision()) is not None:  # one saved since the sheet opened: never undone (sketch)
            self.error(moved)
            return
        try:
            rev = self.ctx.save_recipe(self._form_recipe(saved.board_model, saved), reason)
        except Exception as e:  # logged and alarmed; nothing was stored (one transaction)
            self.error(e)
            return
        self.form_revision, self.form_recipe = (saved.board_model, rev), self.ctx.recipe(saved.board_model)[1]
        self._close_sheet()
        self.shell.status(self.tr("Recipe saved as revision {revision}").format(revision=rev))

    def _close_sheet(self) -> None:
        """The sheet goes, with its reason, and the panel is back, nothing stored: Cancel, Esc, a save, any sign-in (a
        revision never carries the reason of a user it does not name), any board opened, a board model change or a
        recipe reloaded. With none open, nothing changes: the panel shown or hidden while the page is not is a minimum
        size the window never learns (the stack keeps the size its hidden page had). The focus, if in the sheet, goes
        back to the panel, or to the "why" box while Save to Recipe and Re-evaluate are both off (a stored result still
        loading), where a run puts it, and on to Re-evaluate when the load ends if it is still there (`_sync_roles`),
        as at a run's end; moved out of the sheet, to the header's board model say, it stays, as a run's end leaves
        it."""
        if not self._asking:
            return
        held = self.sheet.isAncestorOf(self.window().focusWidget())  # read before the sheet hides and Qt moves it
        self._asking = False
        self.reason.clear()
        self._sync_roles()
        if held and self.isVisible():  # the focus back on the panel, not lost with the sheet
            back = next((b for b in (self.btn_save, self.btn_try) if b.isEnabled()), self.why)
            back.setFocus(Qt.FocusReason.OtherFocusReason)
            self._refocus = back is self.why and self.ctx.role != "Operator"  # for Re-evaluate once on (_sync_roles)

    def _sync_save(self) -> None:
        """Save to Recipe on for a role that may save a recipe while a threshold differs, no sheet is open and no
        re-evaluation runs (Ctrl+S opens no sheet over one), and Save Revision while the sheet has a reason."""
        free = self._may_save() and not self._asking and self._trying is None
        self.act_save.setEnabled(free and bool(self._changes()))
        self.btn_confirm.setEnabled(self._asking and bool(self.reason.text().strip()))

    def _may_save(self) -> bool:
        """The role signed in is at or above the one `AppContext.save_recipe`'s @requires names (#241)."""
        return self.ctx.role in ROLES and ROLES.index(self.ctx.role) >= ROLES.index(REQUIRED_ROLE["save_recipe"])

    def _clear_result(self) -> None:
        """No result on the page: the banner, the decision table, the explanation and the board's pictures go."""
        self.res = None
        self.verdict.setText(NO_VERDICT)
        self.verdict.setStyleSheet(theme.verdict_style("INFO"))
        fill_table(self.metrics, [])
        self.why.clear()
        self.test_view.set_image(None)
        self.ref_view.clear_overlays()

    def _cancelled(self) -> None:
        """Cancel on the busy overlay: the board named over the picture was not judged, so no verdict, table or picture
        of the board before stays under its name (#172); Re-evaluate inspects it."""
        self._clear_result()
        file = breakable(Path(self.test_path).name) if self.test_path else ""
        what = self.tr("{file} was not inspected; press Re-evaluate › to inspect it.").format(file=file)
        self.test_empty.show_state(self.tr("Inspection cancelled"), what, self.tr("Re-evaluate ›"), self.run)

    def _not_inspected(self, e: BaseException) -> None:
        """The board named over the picture could not be judged (its file or the reference cannot be read): as on
        Cancel, no verdict, table or picture of the board before stays under its name; the banner says Not inspected
        and the pane says why, with Re-evaluate (#182)."""
        if not self.test_path:  # only the Golden board was to be read: no result is shown to clear
            return
        self._clear_result()
        shown = breakable_names(e) if isinstance(e, AoiError) else e  # the file it names wraps in the pane (#245)
        heading, sentence = self.not_inspected(self.verdict, breakable(Path(self.test_path).name), shown)
        what = " ".join([sentence, self.tr("Press Re-evaluate › to inspect it again.")])
        self.test_empty.show_state(heading, what, self.tr("Re-evaluate ›"), self.run)

    def on_board_model_changed(self, name: str | None) -> None:
        if name == self.shown_board_model:  # "+ New" with its own name: nothing changed, so nothing goes (#247)
            return
        self.shown_board_model = name
        if self._bg is not None:  # a run of the last board model still going: no verdict or dialog of it shows under
            self._bg.stop()  # this one; a refusal it was asked for is still logged and alarmed (#206, #247 review)
        self.res = self.stored = self.as_judged = self.golden_error = None  # the last board model's views go with it
        self.golden_state = False
        self.note.hide()
        if self.record_board_model not in (None, name):  # a record's board is not judged under another board model
            self.test_path = self.record_board_model = None  # (#172): the page starts empty
            self.test_label.setText(self.tr("Test board"))
            self._clear_result()
        self._load_recipe_into_form()
        self.judge_on_show = bool(name and (self.test_path or self.ref_override))  # a board to judge: when the page
        if self.judge_on_show:  # is shown (MainWindow calls on_show next), never with a dialog over another page,
            self._clear_result()  # and no verdict of the last board model meanwhile (#247)
        elif name:  # only the Golden board to read: now, not asked for, so the pane is ready at start-up
            self._start(quiet=True)

    def _sync_roles(self) -> None:
        """The threshold panel for an Engineer or Admin only, hidden for an Operator, who never sees what other
        thresholds would give (REQ-CMP-005; ADR 0006 decision 4, sketch Q17). Re-evaluate waits until the load of a
        stored result's pictures and maps has ended, so it never stops it, and is off while a re-evaluation runs. A
        focus on it as it goes off waits in the "why" box and goes back to it once it is on again, if still there,
        as when Inspection's "Compare with Golden board ›" showed Compare with the focus it had on Re-evaluate, then a
        stored result (third verification): Qt would pass it on to the header's board model, whose list a Space opens,
        or, while a threshold differs, to Save to Recipe, where one more Space would open its sheet. The focus
        read is the window's, which it keeps while another window is in front (review)."""
        engineer = self.ctx.role != "Operator"
        on = engineer and not self._asking and (self.stored is None or self.loaded) and self._trying is None
        focus = self.window().focusWidget()
        if not on and focus is self.btn_try:
            self.why.setFocus(Qt.FocusReason.OtherFocusReason)
            self._refocus = True
        self.tryout.setVisible(engineer and not self._asking)
        self.sheet.setVisible(engineer and self._asking)
        self.act_try.setEnabled(on)
        self._sync_save()
        if on and self._refocus and focus is self.why:
            self.btn_try.setFocus(Qt.FocusReason.OtherFocusReason)
        self._refocus = self._refocus and engineer and not on  # only while an Engineer's Re-evaluate is off

    def on_user_changed(self) -> None:
        """An Operator signs in, on Compare or on any other page (review): the hidden form goes back to the recipe's
        thresholds, which the Difference heatmap follows, and what was tried with values an Engineer left unsaved goes,
        so the next Engineer finds the recipe's thresholds too; a board inspected with thresholds or other values the
        recipe does not hold now (an Engineer's not saved, or a revision saved since it was inspected) is cleared, a run
        of it still going stopped, and judged by the recipe when Compare is shown (`on_show`, next if it is shown now).
        A run stopped by Cancel stays so, and a stored result as it was decided; a value that did not judge the board is
        no change (`_judging`). A focus in the panel, which the sign-in hides, waits in the "why" box, which every role
        sees, as one on the indicator's Cancel does (`_not_trying`), where Qt would pass it on to the header's board
        model, whose list a Space opens (review); it can be in the panel only while Compare is shown. Any sign-in closes
        Save to Recipe's sheet, its reason with it."""
        self._close_sheet()
        if self.ctx.role != "Operator":
            return
        focus: QWidget | None = self.window().focusWidget()  # before a run, ended by _drop_tried, hides the panel
        scale = self.diff_thr.value()
        saved = self._load_recipe_into_form()  # values an Engineer left there unsaved go, and what was tried with them
        if self.diff_thr.value() != scale and self.mode.currentIndex() == MODE_DIFF:
            self.redraw()
        going = self._bg is not None and not self._bg.job.cancelled  # a run stopped, by Cancel say, is not judged again
        by, judged = self.judged_by, None if going else self.res  # a run still going: not its result yet
        stale = by is not None and saved is not None and _judging(by, judged) != _judging(saved, judged)  # read now
        if stale and self.stored is None and (self.res is not None or going):
            if self._bg is not None:
                self._bg.stop()  # its verdict never shows; an error of it is still logged and alarmed (#206)
            self._clear_result()  # no verdict, table or "why" by the form's thresholds while the recipe judges it
            self.judge_on_show = True  # by the recipe, as soon as the page is shown
        if focus is not None and self.tryout.isAncestorOf(focus):
            self.why.setFocus(Qt.FocusReason.OtherFocusReason)  # outside the panel, which hides now or in on_show

    def on_show(self) -> None:
        self._sync_roles()
        if self.golden_state and self.board_model:
            self._show_golden_state()
        fresh = self.stored is None and not self.ref_override  # a stored result is never inspected again unasked
        again = self.judge_on_show  # the header changed while the page was hidden
        if self.board_model and (again or fresh and (self.golden_error is not None or not self.test_path)):
            if again or self.golden_board_stamp() != self.golden_seen:  # Set Reference, training, or the file put
                self._start(quiet=True)  # back, replaced or gone since: the pane, or a board it kept from judging
        if self.res is None and self.test_path is None:
            step = self.empty_step(self.tr("Inspect a board on Inspection, or pick a test image."), "Inspection")
            self.test_empty.show_state(self.tr("No board to compare yet"), *step)
        moved = self._take_up_revision()  # a revision saved since, on Recipe Editor: Save to Recipe never reverts it
        self._show_calibration()  # an AI model trained or activated since: its value
        if moved is not None:  # nor does a sheet left open: it closed (sketch)
            self.error(moved)

    def _take_up_revision(self) -> AoiError | None:
        """The form takes up a revision of the header's board model saved since it was loaded (on the Recipe Editor,
        or anywhere through AppContext). A Save to Recipe sheet open then closes, nothing stored, and AOI-RCP-004 for
        the page to show is returned: its changes were listed against the revision before (sketch, Errors)."""
        asked = self.form_revision if self._asking else None  # the revision Save to Recipe's open sheet lists against
        if self.board_model and self.form_revision != (self.board_model, self.ctx.recipe(self.board_model)[0]):
            self._load_recipe_into_form()
        if asked and (now := self.form_revision) and now != asked:
            return AoiError("AOI-RCP-004", board_model=now[0], latest=now[1], revision=asked[1])
        return None
