"""Side-by-side Compare page.

Optional page (reachable from the sidebar or "Compare with Golden" on the
Inspection screen) that shows the golden reference next to a test board and
every metric that decided OK / WARN / NG, with what-if thresholds; a stored
result is shown as it was decided and never inspected again (REQ-CMP-003).
"""

from __future__ import annotations

import copy
import functools
import html
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

import numpy as np
from PySide6.QtCore import Qt
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
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ... import defects as taxonomy
from ...core.explain import explain
from ...core.imaging import IMAGE_EXTS
from ...core.inspector import Check, InspectionResult
from ...core.recipe import Recipe
from ...core.services import ROLES_FROM, AppContext, ErrorReport, Judged
from ...core.views import ai_view, difference_view
from ...errors import AoiError
from ...times import to_local
from .. import theme
from ..errors import phrase_text, show_error
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..widgets.image_view import ImageView
from .base import QT_TRANSLATE_NOOP, Page, button, fill_table, make_table, sentence_text, view_text

if TYPE_CHECKING:
    from ..main_window import MainWindow

MODES = [  # the Show combo, in this order; shown through tr()
    QT_TRANSLATE_NOOP("ComparePage", "Side by side"),
    QT_TRANSLATE_NOOP("ComparePage", "Difference heatmap"),
    QT_TRANSLATE_NOOP("ComparePage", "AI score heatmap"),
    QT_TRANSLATE_NOOP("ComparePage", "Defect boxes only"),
]
MODE_SIDE, MODE_DIFF, MODE_AI, MODE_BOXES = range(4)
NO_VERDICT = "—"  # the banner with no result shown
Stored: TypeAlias = "tuple[np.ndarray | None, Judged, InspectionResult | None, list[ErrorReport]] | ErrorReport"
# golden board, why not, result, and the stored files of it that could not be read; or why none of it could be read.
# Each error is already logged and alarmed (#247)
Evaluated: TypeAlias = "tuple[np.ndarray | None, InspectionResult | None, AoiError | None, AoiError | None]"  # golden
# board, result, why the Golden board cannot be shown, and the refusal of a test board it kept from being judged
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
        pl.addWidget(self.metrics, 2)
        self.why = QTextEdit()
        self.why.setReadOnly(True)
        self.why.setMaximumHeight(150)
        pl.addWidget(self.why)

        g = QGroupBox(self.tr("What-if thresholds (not saved until you press Save to Recipe)"))
        f = QFormLayout(g)
        self.ai_thr = QDoubleSpinBox()
        self.ai_thr.setDecimals(3)
        self.ai_thr.setRange(0, 1e4)
        self.ai_thr.setSpecialValueText(self.tr("AI model default"))
        self.ai_thr.setSingleStep(0.1)
        self.diff_thr = QSpinBox()
        self.diff_thr.setRange(1, 255)
        self.min_area = QSpinBox()
        self.min_area.setRange(1, 100000)
        self.ssim_min = QDoubleSpinBox()
        self.ssim_min.setRange(0, 1)
        self.ssim_min.setSingleStep(0.01)
        self.max_regions = QSpinBox()
        self.max_regions.setRange(0, 1000)
        f.addRow(self.tr("AI score threshold"), self.ai_thr)
        f.addRow(self.tr("Pixel difference (0-255)"), self.diff_thr)
        f.addRow(self.tr("Minimum defect area (px)"), self.min_area)
        f.addRow(self.tr("Similarity minimum (SSIM)"), self.ssim_min)
        f.addRow(self.tr("Allowed difference regions"), self.max_regions)
        row = QHBoxLayout()
        row.addWidget(button(self.tr("Re-evaluate"), slot=self.run))
        self.btn_save = button(self.tr("Save to Recipe"), "primary", self.save_recipe)  # the page's one blue primary
        row.addWidget(self.btn_save)
        f.addRow(row)
        pl.addWidget(g)
        split.addWidget(panel)
        split.setSizes([800, 920])  # the decision table shows all six columns at 1920 x 1080
        self.root.addWidget(split, 1)

    # --- inputs ------------------------------------------------------------------
    def set_test(self, path: str) -> None:
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
        if (last := self.shell.last_inspected) and last[2] is not None:
            self.show_stored(last[2])  # the record, as it was decided (REQ-INSP-009)
        elif last:
            self.set_test(last[0])  # a preview from AI Model Test is not recorded: inspected again

    def pick_ref(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        f, _ = QFileDialog.getOpenFileName(
            self, self.tr("Reference image"), "", self.tr("Images ({extensions})").format(extensions=exts)
        )
        if f:
            self.ref_override = f
            self.run()

    def use_golden(self) -> None:
        self.ref_override = self.as_judged = None  # today's golden board
        self.run()

    def _load_recipe_into_form(self) -> None:
        if not self.board_model:
            return
        rev, r = self.ctx.recipe(self.board_model)
        self.form_revision = (self.board_model, rev)  # on_show loads the form again once another revision is saved
        self.ai_thr.setValue(r.anomaly_threshold or 0)
        self.diff_thr.setValue(r.diff_threshold)
        self.min_area.setValue(r.min_defect_area)
        self.ssim_min.setValue(r.ssim_min)
        self.max_regions.setValue(r.max_diff_regions)

    def _form_recipe(self, board_model: str) -> Recipe:
        """The board model's recipe with the what-if thresholds from the form."""
        _, r = self.ctx.recipe(board_model)
        r = copy.deepcopy(r)
        r.anomaly_threshold = self.ai_thr.value() or None
        r.diff_threshold = self.diff_thr.value()
        r.min_defect_area = self.min_area.value()
        r.ssim_min = self.ssim_min.value()
        r.max_diff_regions = self.max_regions.value()
        return r

    # --- evaluate ----------------------------------------------------------------
    def run(self) -> None:
        """Load the reference and inspect the test image on a pool thread (REQ-SET-021); the form is read here."""
        self._start(quiet=False)

    def _start(self, quiet: bool) -> None:
        """`quiet`: run because the page was shown, not asked for: a Golden board that still cannot be read is said on
        its pane only, with no dialog or alarm (#176 review)."""
        bm = self.board_model
        if not bm:
            return
        if self.test_path and self.record_board_model not in (None, bm):  # a record's board is judged under its own
            file, own = Path(self.test_path).name, self.record_board_model  # board model, never the header's (#172)
            self.error(AoiError("AOI-CMP-005", tried=bm, file=file, judged=own))
            return
        self.stored = None  # a fresh inspection with the form's thresholds, not a stored result
        self.note.hide()
        if self.test_path:
            self.test_label.setText(self.tr("Test board: {file}").format(file=Path(self.test_path).name))
        recipe = self._form_recipe(bm) if self.test_path else None
        judged = self.as_judged[1] if self.as_judged and not self.ref_override else None
        if not self.ref_override:
            self.golden_seen = self.golden_board_stamp()
        self.run_in_background(
            self._evaluate, bm, self.test_path, self.ref_override, recipe, judged,
            on_result=functools.partial(self._on_evaluated, quiet=quiet), busy=self.busy if self.test_path else None,
            on_error=self._not_inspected,
        )  # fmt: skip

    def _evaluate(
        self,
        board_model: str,
        test_path: str | None,
        ref_path: str | None,
        recipe: Recipe | None,
        ref: np.ndarray | None,
    ) -> Evaluated:
        """Pool thread: files and the engine only, never a widget. `ref` is a stored result's golden board as judged.
        Today's Golden board gone or damaged comes back as the error to say on its pane, not raised (it was a dialog
        at every start, #176), and is alarmed once (#195); a test board it keeps from being judged comes back with its
        AOI-INSP-009 refusal and no result, so the pane says why whether or not a board was to be judged (#176
        review)."""
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
        res = self.ctx.inspect(board_model, test, recipe, reference=ref) if test is not None else None
        return ref, res, golden_error, refused

    def _on_evaluated(self, out: Evaluated, quiet: bool) -> None:
        ref, res, self.golden_error, refused = out
        self._show_reference(ref)
        if refused is not None:  # the board was not judged: no verdict, table or picture of the board before beside it
            self._clear_result()
            what = self.tr("{file} was not inspected: its Golden board cannot be opened.").format(
                file=Path(self.test_path or "").name
            )
            self.test_empty.show_state(self.tr("Board not inspected"), what)
            if not quiet:  # asked for: the refusal's dialog and alarm, as on Inspection
                self.error(refused)
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
            self.ref_label.setText(self.tr("Reference: {file}").format(file=Path(self.ref_override).name))
        elif recorded:
            self.ref_label.setText(self.tr("Golden board as judged: {file}").format(file=Path(recorded).name))
        elif ref is not None or judged in JUDGED or self.golden_error is not None:
            self.ref_label.setText(self.tr("Reference: Golden board"))
        else:
            self.ref_label.setText(self.tr("Reference: none set"))
        self.ref_view.set_image(ref)
        self.golden_state = False
        if judged is not None and judged in JUDGED:
            what = self.tr(JUDGED[judged]).format(file=Path(recorded or "").name)
            do = self.tr(
                "The verdict and the decision table are the stored ones; press Re-evaluate to inspect the board again"
                " with today's Golden board."
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
        self.why.setHtml(self._explain(r))

    def show_stored(self, inspection_id: int) -> None:
        """A stored result as it was decided, never inspected again (REQ-CMP-003): the verdict, table and explanation
        from the record at once (REQ-INSP-009); the pictures and the stored maps follow from the pool thread."""
        rec = self.ctx.inspection(inspection_id)
        res = self.ctx.inspection_result(inspection_id)
        if rec is None or res is None:
            file = Path(rec["image_path"]).name if rec else "?"
            self.error(AoiError("AOI-CMP-002", id=inspection_id, file=file))
            return
        self.stored, self.test_path, self.ref_override, self.as_judged = rec, rec["image_path"], None, None
        self.golden_error, self.golden_state = None, False  # its pane shows the golden board as judged, not today's
        self.record_board_model = rec["board_model"]  # Re-evaluate judges the board under it (#172)
        self._fitted = False
        self.test_empty.hide()
        self.test_view.set_image(None)  # the board shown before goes at once, not when this one's picture arrives,
        self.ref_view.set_image(None)  # and so do its golden board and boxes, and why that pane had none (#247)
        self.ref_empty.hide()
        self.ref_label.setText(self.tr("Golden board"))
        self.test_label.setText(self.tr("Test board: {file} (stored result)").format(file=Path(rec["image_path"]).name))
        self._show_result(res)
        self._show_note(rec)
        self.run_in_background(self._load_stored, rec, inspection_id, on_result=self._on_stored_loaded)

    def _load_stored(self, rec: dict[str, Any], inspection_id: int) -> Stored:
        """Pool thread: the golden board the result was judged against (REQ-CMP-003), the result with its stored maps,
        and its stored overlay as the picture, aligned to that golden board as judged (the board's own file is not);
        never a widget. A map or overlay that cannot be read takes away only itself, never the golden board; when none
        of it can be read (a database another program holds, say), the report comes back alone. Each error is logged
        and alarmed here, so a load a newer one replaced loses none, and comes back for the panes and the dialog,
        which so name the one code (#247)."""
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
        return ref, judged, res, [self.ctx.report_error(e, self.title) for e in unread]

    def _on_stored_loaded(self, out: Stored) -> None:
        if self.stored is None:  # a fresh run or a board model change came first: nothing of it shows
            return
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
        for report in unread:  # after the panes are drawn, so the dialog names the file beside them; the note keeps it
            self.note.setText(f"{self.note.text()} {report.code} {phrase_text(report.what)}")
            show_error(self, report)

    def _no_board_picture(self, heading: str, why: str = "") -> None:
        """The test pane of a stored result without its picture: `why`, that the verdict and the table stand, and
        Re-evaluate."""
        sentence = self.tr(
            "The verdict and the decision table are the stored ones; press Re-evaluate to inspect the board again"
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
            name = Path(golden).name if golden else self.tr("none")
            parts.append(self.tr("The board model's Golden board is now {file}.").format(file=name))
        if not any(p and Path(p).is_file() for p in (rec["diff_map_path"], rec["ai_map_path"])):
            e = AoiError("AOI-CMP-001", file=Path(rec["image_path"]).name, days=self.ctx.settings.map_retention_days_ok)
            parts.append(f"{e.code} {phrase_text(e.what)} {phrase_text(e.action)}")
        self.note.setText(" ".join(parts))
        self.note.show()

    def _check_text(self, c: Check) -> tuple[str, str, str]:
        """A check's name, source and rule in the UI language (CHECK_NAMES, SOURCES, RULES)."""
        name = self.tr(CHECK_NAMES[c.name]) if c.name in CHECK_NAMES else c.name
        return name, self.tr(SOURCES.get(c.source, c.source)), self.tr(RULES.get(c.rule, c.rule))

    def _explain(self, r: InspectionResult) -> str:
        """The "why" box (REQ-CMP-004; sketch docs/sketches/compare-decision-table.md of PR #79): a heading with the
        verdict, then the plain-word sentences of `explain` as bullets, the deciding checks first, each in the UI
        language; every value is escaped, so none is read as markup."""
        heading = self.tr("Why this board is {verdict}:").format(verdict=r.verdict)
        return "<br>".join(
            [f"<b>{html.escape(heading)}</b>", *(f"• {html.escape(sentence_text(s))}" for s in explain(r))]
        )

    def redraw(self) -> None:
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
        if self.ctx.role == "Operator":
            self.error(
                AoiError(
                    "AOI-USR-001", what=QT_TRANSLATE_NOOP("Errors", "Changing recipes"), roles=ROLES_FROM["Engineer"]
                )
            )
            return
        if (bm := self.checked_board_model()) is None:
            return
        rev = self.ctx.save_recipe(self._form_recipe(bm))
        self.form_revision = (bm, rev)
        self.shell.status(self.tr("Recipe saved as revision {revision}").format(revision=rev))

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
        file = Path(self.test_path).name if self.test_path else ""
        what = self.tr("{file} was not inspected; press Re-evaluate to inspect it.").format(file=file)
        self.test_empty.show_state(self.tr("Inspection cancelled"), what, self.tr("Re-evaluate ›"), self.run)

    def _not_inspected(self, e: BaseException) -> None:
        """The board named over the picture could not be judged (its file or the reference cannot be read): as on
        Cancel, no verdict, table or picture of the board before stays under its name; the banner says Not inspected
        and the pane says why, with Re-evaluate (#182)."""
        if not self.test_path:  # only the Golden board was to be read: no result is shown to clear
            return
        self._clear_result()
        heading, sentence = self.not_inspected(self.verdict, Path(self.test_path).name, e)
        what = " ".join([sentence, self.tr("Press Re-evaluate to inspect it again.")])
        self.test_empty.show_state(heading, what, self.tr("Re-evaluate ›"), self.run)

    def on_board_model_changed(self, name: str | None) -> None:
        self.res = self.stored = self.as_judged = self.golden_error = None  # the last board model's views go with it
        self.golden_state = False
        self.note.hide()
        if self.record_board_model not in (None, name):  # a record's board is not judged under another board model
            self.test_path = self.record_board_model = None  # (#172): the page starts empty
            self.test_label.setText(self.tr("Test board"))
            self._clear_result()
        self._load_recipe_into_form()
        if name:
            self.run()

    def on_show(self) -> None:
        self.btn_save.setEnabled(self.ctx.role != "Operator")
        if self.golden_state and self.board_model:
            self._show_golden_state()
        fresh = self.stored is None and not self.ref_override  # a stored result is never inspected again unasked
        if self.board_model and fresh and (self.golden_error is not None or not self.test_path):
            if self.golden_board_stamp() != self.golden_seen:  # Set Reference, training, or the file put back,
                self._start(quiet=True)  # replaced or gone since: the pane, or a board it kept from judging, again
        if self.res is None and self.test_path is None:
            step = self.empty_step(self.tr("Inspect a board on Inspection, or pick a test image."), "Inspection")
            self.test_empty.show_state(self.tr("No board to compare yet"), *step)
        if self.board_model and self.form_revision != (self.board_model, self.ctx.recipe(self.board_model)[0]):
            self._load_recipe_into_form()  # a revision saved since, on Recipe Editor: Save to Recipe never reverts it
