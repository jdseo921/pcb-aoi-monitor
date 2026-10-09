"""Recipe Editor (spec 4.2): draw ROIs on the golden board and set thresholds."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import defects as taxonomy
from ...core.imaging import IMAGE_EXTS
from ...core.inspector import InspectionResult
from ...core.recipe import ROI, ROI_TYPES, Recipe
from ...core.services import AppContext
from ...errors import AoiError
from ...times import to_local
from .. import theme
from ..errors import phrase_text
from ..widgets.box_editor import RoiEditor
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..widgets.scale import CalibrationSheet, DefectSizeField
from .base import QT_TRANSLATE_NOOP, Page, button, fill_table, make_table, scrolled

if TYPE_CHECKING:
    from ..main_window import MainWindow

ROI_TYPE_NAMES = {  # the recipe stores the English type (ROI_TYPES); the editor shows it in the UI language
    "Presence": QT_TRANSLATE_NOOP("RecipeEditorPage", "Presence"),
    "Polarity": QT_TRANSLATE_NOOP("RecipeEditorPage", "Polarity"),
    "Solder Bridge": QT_TRANSLATE_NOOP("RecipeEditorPage", "Solder Bridge"),
    "Height": QT_TRANSLATE_NOOP("RecipeEditorPage", "Height"),
    "Anomaly": QT_TRANSLATE_NOOP("RecipeEditorPage", "Anomaly"),
}
REPLACED = QT_TRANSLATE_NOOP("Errors", "its Golden board was replaced after the points were picked on it")


def _opt_spin(maxv: float = 1e4) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(-1, maxv)
    s.setDecimals(3)
    s.setSpecialValueText("—")
    s.setValue(-1)
    return s


class RecipeEditorPage(Page):
    title = QT_TRANSLATE_NOOP("Page", "Recipe Editor")
    subtitle = QT_TRANSLATE_NOOP("Page", "Draw ROIs on the Golden board · zoom with the wheel · double-click to fit")
    roles = ("Engineer", "Admin")

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        self.recipe: Recipe | None = None
        self.rev = 0
        self._loaded: dict[str, object] = {}  # the recipe as load() showed it, to tell an unsaved change (#173)
        self.ref: np.ndarray | None = None
        self.golden_seen: tuple[str | None, int, int] | None = None  # the Golden board file last read (#176)
        self.golden_error: AoiError | None = None  # and why it could not be
        self.px_per_mm: float | None = None  # the board model's scale, which load() reads (REQ-RCP-006)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.draw_btn = button(self.tr("Draw ROI"), slot=self.toggle_draw)  # Save Recipe is the page's one blue primary
        self.draw_btn.setCheckable(True)
        tools.addWidget(self.draw_btn)
        tools.addWidget(QLabel(self.tr("Type:")))
        self.roi_type = QComboBox()
        self._fill_types(self.roi_type)
        tools.addWidget(self.roi_type)
        tools.addStretch(1)
        ll.addLayout(tools)
        scale_row = QHBoxLayout()  # a row of its own: on the tools row it widened the window past 1920 px
        self.scale_text, self.scale_badge = QLabel(), QLabel()  # the scale, or AOI-RCP-005 in amber (Q21)
        self.scale_text.setObjectName("muted")
        self.scale_badge.setObjectName("badge")
        self.calibrate_btn = button(self.tr("Calibrate Scale…"), slot=self.calibrate)
        for part in (self.scale_text, self.calibrate_btn):
            scale_row.addWidget(part)
        scale_row.addStretch(1)
        ll.addLayout(scale_row)
        self.scale_badge.setWordWrap(True)  # a row of its own under the scale, as AOI-RCP-009: beside Calibrate Scale…
        ll.addWidget(self.scale_badge)  # it made the window 1601 px wide, wider than a 1600 x 900 screen
        self.held_badge = QLabel()  # AOI-RCP-009, word-wrapped on a row of its own under the scale: no wider window
        self.held_badge.setObjectName("badge")  # amber, as AOI-RCP-005 (S29 review)
        self.held_badge.setWordWrap(True)
        self.held_badge.hide()
        ll.addWidget(self.held_badge)
        self.scale_text.hide()  # until load() finds a board model
        self.scale_badge.hide()
        self.calibrate_btn.setEnabled(False)
        self.sheet = CalibrationSheet()  # inline, under the scale: no dialog over the page
        self.sheet_user = ""  # who opened it: another user signed in closes it, with the points picked
        self.sheet.hide()
        self.sheet.submitted.connect(self.set_scale)
        self.sheet.cancelled.connect(self._close_sheet)
        ll.addWidget(self.sheet)
        self.view = RoiEditor(placeholder="")
        self.view.type_text = self._type_text
        self.view_empty = EmptyState(self.view)
        self.view.roiDrawn.connect(self.add_roi)
        self.view.picked.connect(self._picked)  # an ROI pressed on the Golden board: its row, and the form
        self.view.edited.connect(self._moved)
        self.view.pointPicked.connect(self._pick)
        self.busy = BusyOverlay(self.view, self.tr("Trying the recipe…"))
        ll.addWidget(self.view, 1)
        split.addWidget(left)

        tabs = QTabWidget()
        # ROI tab
        roi_tab = QWidget()
        roi_tab.setObjectName("page")
        rl = QVBoxLayout(roi_tab)
        self.roi_table = make_table(self._roi_headers(), sortable=False)
        self.roi_table.itemSelectionChanged.connect(self._select_roi)
        self.roi_empty = EmptyState(self.roi_table)
        rl.addWidget(self.roi_table, 1)
        g = QGroupBox(self.tr("Selected ROI"))
        f = QFormLayout(g)
        self.r_name = QLineEdit()
        self.r_type = QComboBox()
        self._fill_types(self.r_type)
        self.r_ai = QDoubleSpinBox()
        self.r_ai.setRange(0.05, 100)
        self.r_ai.setSingleStep(0.1)
        self.r_hmin, self.r_hmax, self.r_vmin, self.r_vmax = (_opt_spin() for _ in range(4))
        self.r_enabled = QCheckBox(self.tr("Enabled"))
        f.addRow(self.tr("Name"), self.r_name)
        f.addRow(self.tr("ROI type"), self.r_type)
        f.addRow(self.tr("AI score (× AI score threshold)"), self.r_ai)  # the recipe's, else the AI model's
        f.addRow(self.tr("Height thresholds min / max (Stage 2)"), self._pair(self.r_hmin, self.r_hmax))
        f.addRow(self.tr("Volume thresholds min / max (Stage 2)"), self._pair(self.r_vmin, self.r_vmax))
        f.addRow(self.r_enabled)
        row = QHBoxLayout()
        self.apply_btn = button(self.tr("Apply"), slot=self.apply_roi)  # off while no ROI is selected (#173)
        row.addWidget(self.apply_btn)
        self.delete_btn = button(self.tr("Delete"), "danger", self.delete_roi)  # red, last, never the default; off too
        row.addWidget(self.delete_btn)
        f.addRow(row)
        rl.addWidget(g)
        self._select_roi()  # none yet: the empty form, as after a Delete
        tabs.addTab(roi_tab, self.tr("ROIs"))

        # Global thresholds tab
        thr_tab = QWidget()
        thr_tab.setObjectName("page")
        tf = QFormLayout(thr_tab)
        self.use_ai = QCheckBox(self.tr("Use the self-trained AI model"))
        self.use_cmp = QCheckBox(self.tr("Use the Golden board comparison"))
        self.ai_thr = self.ai_threshold_field()
        self.ai_thr.ticking.connect(lambda: self.show_calibrated(self.ai_thr, self.board_model))  # trained since shown
        self.warn = QDoubleSpinBox()
        self.warn.setRange(0.1, 1)
        self.warn.setSingleStep(0.05)
        self.diff = QSpinBox()
        self.diff.setRange(1, 255)
        self.min_size = DefectSizeField()  # in px without a scale, in mm with one
        self.area = self.min_size.area
        self.ssim = QDoubleSpinBox()
        self.ssim.setRange(0, 1)
        self.ssim.setSingleStep(0.01)
        self.chg = QDoubleSpinBox()
        self.chg.setRange(0, 100)
        self.chg.setSingleStep(0.05)
        self.maxreg = QSpinBox()
        self.maxreg.setRange(0, 1000)
        for w, label in (
            (self.use_ai, None),
            (self.ai_thr, self.tr("AI score threshold")),
            (self.ai_thr.note, None),  # why no calibrated value is named, as wide as the form
            (self.warn, self.tr("WARN band (fraction of the threshold)")),
            (self.use_cmp, None),
            (self.diff, self.tr("Pixel difference (0-255)")),
            (self.min_size, self.min_size.label),
            (self.min_size.notice, None),
            (self.ssim, self.tr("Similarity minimum (SSIM)")),
            (self.chg, self.tr("Maximum changed area %")),
            (self.maxreg, self.tr("Allowed difference regions")),
        ):
            tf.addRow(label, w) if label else tf.addRow(w)
        tabs.addTab(scrolled(thr_tab), self.tr("Thresholds"))  # scrolls where the window is too short for its rows

        # Mandatory defect set tab (classification table §4)
        mand = QWidget()
        mand.setObjectName("page")
        ml = QVBoxLayout(mand)
        ml.addWidget(QLabel(self.tr("Mandatory AOI defect set (every recipe must cover it):")))
        self.mand_list = QListWidget()
        ml.addWidget(self.mand_list, 1)
        tabs.addTab(mand, self.tr("Mandatory Set"))

        # History tab
        hist = QWidget()
        hist.setObjectName("page")
        hl = QVBoxLayout(hist)
        self.history = make_table([self.tr("Revision"), self.tr("User"), self.tr("Saved")])
        hl.addWidget(self.history)
        tabs.addTab(hist, self.tr("Revisions"))

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)
        rv.addWidget(tabs, 1)
        self.test_verdict = QLabel("")
        self.test_verdict.setMinimumHeight(theme.FIELD_H)
        rv.addWidget(self.test_verdict)
        b = QHBoxLayout()
        b.addWidget(button(self.tr("Try Recipe…"), slot=self.test_run))
        b.addWidget(button(self.tr("Save Recipe"), "primary", self.save))
        rv.addLayout(b)
        split.addWidget(right)
        split.setSizes([1000, 640])
        self.root.addWidget(split, 1)

    def _fill_types(self, combo: QComboBox) -> None:
        for roi_type in ROI_TYPES:
            combo.addItem(self._type_text(roi_type), roi_type)  # the English type is the key the recipe stores

    def _type_text(self, roi_type: str) -> str:
        return self.tr(ROI_TYPE_NAMES[roi_type]) if roi_type in ROI_TYPE_NAMES else roi_type

    def _roi_headers(self) -> list[str]:
        unit = self.tr("px") if self.px_per_mm is None else self.tr("mm")
        box = (self.tr("X"), self.tr("Y"), self.tr("W"), self.tr("H"))  # each a literal, so lupdate finds it (#173)
        sized = [self.tr("{name} ({unit})").format(name=name, unit=unit) for name in box]
        return [self.tr("Name"), self.tr("Type"), *sized, self.tr("AI score")]

    def _box(self, x: ROI) -> list[float]:
        """An ROI's place and size as the table shows them: in px, or in mm at the scale."""
        if (s := self.px_per_mm) is None:
            return [x.x, x.y, x.w, x.h]
        return [round(v, 2) for v in x.mm or [v / s for v in (x.x, x.y, x.w, x.h)]]

    @staticmethod
    def _pair(a: QWidget, b: QWidget) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(a)
        layout.addWidget(b)
        return w

    @property
    def edited_recipe(self) -> Recipe:
        """The recipe being edited: `load()` sets it with the board model and the ROI and threshold controls act on it,
        so a call without one is a programming error, not a state to handle. It belongs to the board model `load()`
        last found: when the board model is cleared, `load()` shows the empty state and keeps the old recipe (Save
        asks for a board model first), and `on_show()` reloads it as soon as a board model is picked again."""
        if self.recipe is None:
            raise RuntimeError("the Recipe Editor has no recipe loaded")
        return self.recipe

    # --- load / show ------------------------------------------------------------
    def load(self) -> None:
        self.roi_table.clearSelection()  # row i of the recipe before is not ROI i of this one: the form empties (#173)
        if not self.board_model:
            self.calibrate_btn.setEnabled(False)  # no Golden board to click on, nor to take the focus back
            if not self.sheet.isHidden():  # no Golden board to pick points on: Draw ROI and panning come back
                self._close_sheet()
            self.view_empty.show_state(*self.no_board_model())
            self.show_calibrated(self.ai_thr, None)  # nothing to name, never the board model before's value (review)
            self.scale_text.hide()  # no board model, so no scale and no AOI-RCP-005 to show
            self.scale_badge.hide()
            self.held_badge.hide()
            return
        self.rev, r = self.ctx.recipe(self.board_model)
        try:
            self.px_per_mm = self.ctx.scale(self.board_model)
        except AoiError as e:  # AOI-RCP-012: said, and the page left for Set Scale to replace it (S29 review)
            self.px_per_mm = None
            self.error(e)
        self.recipe = r = r.in_px(self.px_per_mm)  # its sizes in mm as the engine applies them, in px
        self._read_golden_board()
        self._close_sheet()
        self.use_ai.setChecked(r.use_ai)
        self.use_cmp.setChecked(r.use_compare)
        self.show_calibrated(self.ai_thr, self.board_model)
        self.ai_thr.set_override(r.anomaly_threshold)
        self.warn.setValue(r.warn_ratio)
        self.diff.setValue(r.diff_threshold)
        self.min_size.show_recipe(r, self.px_per_mm)
        self.ssim.setValue(r.ssim_min)
        self.chg.setValue(r.changed_pct_max)
        self.maxreg.setValue(r.max_diff_regions)
        fill_table(
            self.history,
            [[h["revision"], h["user"], to_local(h["created_at"])] for h in self.ctx.recipe_history(self.board_model)],
        )
        self._loaded = self._collect().to_dict()  # as the form shows it, rounded to its spin boxes
        self.view.saved = self._saved_rois()
        self._refresh_rois()

    def _saved_rois(self) -> list[ROI]:
        """The ROIs of the revision loaded, as shown: any other ROI on the Golden board is a change not saved yet."""
        return Recipe.from_dict(copy.deepcopy(self._loaded)).rois

    def _read_golden_board(self) -> None:
        """Read the board model's Golden board into the view, in place of a Try's board and its defects. A file gone
        or damaged must not stop the window opening on this board model (#176): its error is kept for the pane, logged
        and alarmed (#195)."""
        self.view.extra = []
        self.golden_seen, self.golden_error = self.golden_board_stamp(), None
        try:
            self.ref = self.ctx.load_image(self.golden_seen[0]) if self.golden_seen[0] else None
        except AoiError as e:
            self.ref, self.golden_error = None, e
            self.ctx.golden_board_unreadable(self.board_model or "", e)
        self.view.set_image(self.ref)
        self._show_golden_board()

    def _show_golden_board(self) -> None:
        """The Golden board pane's empty state, for the role signed in now: load() runs at start-up, before anyone signs
        in, so on_show() builds it again (#176 review)."""
        if self.golden_error is not None:
            self.view_empty.show_state(*self.golden_board_unreadable(self.golden_error))
        elif self.ref is None:
            step = self.empty_step(self.tr("Train an AI model or set a reference image on Training."), "Training")
            heading = self.tr("No Golden board for {board_model} yet").format(board_model=self.board_model)
            self.view_empty.show_state(heading, *step)
        else:
            self.view_empty.hide()
        self.calibrate_btn.setEnabled(self.ref is not None)  # Calibrate Scale… is clicked on the Golden board

    def _refresh_rois(self) -> None:
        r = self.edited_recipe
        self.roi_table.setHorizontalHeaderLabels(self._roi_headers())
        fill_table(self.roi_table, [[x.name, x.type, *self._box(x), x.ai_score] for x in r.rois])
        self._show_scale()
        if r.rois:
            self.roi_empty.hide()
        else:
            self.roi_empty.show_state(self.tr("No ROIs yet"), self.tr("Press Draw ROI and drag on the Golden board."))
        self._draw_rois()
        covered = {x.type for x in r.rois}
        self.mand_list.clear()
        roi_for = {
            "Missing Component": "Presence",
            "Polarity Error": "Polarity",
            "Solder Bridge": "Solder Bridge",
            "Connector Pin Height": "Height",
            "3D Coplanarity": "Height",
            "Solder Volume": "Height",
        }
        for name in taxonomy.MANDATORY_AOI_SET:
            if name in taxonomy.REQUIRES_3D_OR_SIDE:
                mark = self.tr("◌  needs Stage 2 (3D / side camera)")
            elif roi_for.get(name) in covered:
                mark = self.tr("✓  ROI defined")
            else:
                mark = self.tr("•  covered by the whole-board AI model and the Golden board comparison")
            self.mand_list.addItem(self.tr("{defect:<24}  {mark}").format(defect=name, mark=mark))

    def _sel_index(self) -> int:
        rows = self.roi_table.selectionModel().selectedRows() if self.roi_table.selectionModel() else []
        return rows[0].row() if rows else -1

    # --- ROI editing ------------------------------------------------------------
    def toggle_draw(self) -> None:
        self.view.set_draw_mode(self.draw_btn.isChecked())

    def add_roi(self, rect: QRectF) -> None:
        rois = self.edited_recipe.rois
        n = len(rois) + 1
        rois.append(
            ROI(
                f"R{n}",
                self.roi_type.currentData(),
                int(rect.x()),
                int(rect.y()),
                int(rect.width()),
                int(rect.height()),
            )
        )
        self._refresh_rois()
        self.roi_table.selectRow(len(rois) - 1)

    def _select_roi(self) -> None:
        i = self._sel_index()
        self.apply_btn.setEnabled(i >= 0)
        self.delete_btn.setEnabled(i >= 0)
        rois = self.edited_recipe.rois if i >= 0 else []
        x = rois[i] if i >= 0 else ROI("", "", ai_score=0, enabled=False)  # none selected: an empty form, no stale ROI
        self.r_name.setText(x.name)
        self.r_type.setCurrentIndex(self.r_type.findData(x.type))
        self.r_ai.setValue(x.ai_score)
        for w, v in (
            (self.r_hmin, x.height_min),
            (self.r_hmax, x.height_max),
            (self.r_vmin, x.volume_min),
            (self.r_vmax, x.volume_max),
        ):
            w.setValue(-1 if v is None else v)
        self.r_enabled.setChecked(x.enabled)
        if self.recipe is not None:
            self._draw_rois()  # the points picked stay in view (S29 review)

    def _picked(self, i: int) -> None:
        if i != self._sel_index():
            self.roi_table.selectRow(i) if i >= 0 else self.roi_table.clearSelection()

    def _moved(self) -> None:
        """ROIs moved or resized on the Golden board (REQ-RCP-001): each takes its new box in px, and drops its box in
        mm, so that Save Recipe stores the new box in mm at the scale (`Recipe.in_mm`)."""
        i = self._sel_index()
        for x, shown in zip(self.edited_recipe.rois, self.view.boxes, strict=True):
            if (shown.x, shown.y, shown.w, shown.h) != (x.x, x.y, x.w, x.h):
                x.x, x.y, x.w, x.h, x.mm = shown.x, shown.y, shown.w, shown.h, None
        self._refresh_rois()
        self.roi_table.selectRow(i)

    def apply_roi(self) -> None:
        i = self._sel_index()
        if i < 0:
            return
        x = self.edited_recipe.rois[i]
        thresholds = [self._threshold(w) for w in (self.r_hmin, self.r_hmax, self.r_vmin, self.r_vmax)]
        height, volume = QT_TRANSLATE_NOOP("Errors", "Height"), QT_TRANSLATE_NOOP("Errors", "Volume")
        for quantity, (low, high) in ((height, thresholds[:2]), (volume, thresholds[2:])):
            negative = any(v is not None and v < 0 for v in (low, high))
            if negative or (low is not None and high is not None and low > high):
                shown = ["—" if v is None else f"{v:g}" for v in (low, high)]
                self.error(AoiError("AOI-RCP-002", roi=x.name, quantity=quantity, low=shown[0], high=shown[1]))
                return  # nothing applied: a Stage 2 check would judge every board NG on these thresholds (#173)
        x.name, x.type, x.ai_score, x.enabled = (
            self.r_name.text(),
            self.r_type.currentData(),
            self.r_ai.value(),
            self.r_enabled.isChecked(),
        )
        x.height_min, x.height_max, x.volume_min, x.volume_max = thresholds
        self._refresh_rois()

    @staticmethod
    def _threshold(w: QDoubleSpinBox) -> float | None:
        """A Stage 2 threshold: None only at the spin box's "—" (its minimum, -1); any other number is kept as typed."""
        return None if w.value() == w.minimum() else w.value()

    def delete_roi(self) -> None:
        i = self._sel_index()
        if i >= 0:
            self.roi_table.clearSelection()  # the next ROI moves up to row i: the form must not stay on the deleted one
            del self.edited_recipe.rois[i]
            self._refresh_rois()

    def _collect(self) -> Recipe:
        r = self.edited_recipe
        r.use_ai, r.use_compare = self.use_ai.isChecked(), self.use_cmp.isChecked()
        r.anomaly_threshold = self.ai_thr.override()
        r.warn_ratio, r.diff_threshold = self.warn.value(), self.diff.value()
        self.min_size.apply(r)  # a size left in px stays in px until save() stores it in mm (Recipe.in_mm)
        r.ssim_min, r.changed_pct_max, r.max_diff_regions = self.ssim.value(), self.chg.value(), self.maxreg.value()
        return r

    # --- scale (REQ-RCP-006) -----------------------------------------------------
    def held_in_px(self) -> AoiError | None:
        """AOI-RCP-009 while the board model has a scale and its latest revision holds its minimum defect size or an
        ROI in px, which keep their px when the scale is set again (a camera change), until Save Recipe stores them in
        mm (S29 review); else None."""
        if self.px_per_mm is None or not (bm := self.board_model):
            return None
        rev, r = self.ctx.recipe(bm)
        count, total = (r.min_defect_mm is None) + sum(x.mm is None for x in r.rois), 1 + len(r.rois)
        return AoiError("AOI-RCP-009", revision=rev, board_model=bm, count=count, total=total) if count else None

    def _show_scale(self) -> None:
        """The board model's scale above the Golden board, or, without one, AOI-RCP-005 in amber: sizes in px (Q21);
        with one, AOI-RCP-009 in amber under it while the latest revision still holds a size in px (`held_in_px`), with
        what to do, as touch and keys reach no tooltip."""
        s, bm, held = self.px_per_mm, self.board_model or "", self.held_in_px()
        self.scale_text.setVisible(s is not None)
        self.scale_badge.setVisible(s is None)
        self.held_badge.setVisible(held is not None)
        if s is not None:
            self.scale_text.setText(self.tr("Scale {scale:.2f} px/mm").format(scale=s))
        for label, badge in ((self.scale_badge, AoiError("AOI-RCP-005", board_model=bm)), (self.held_badge, held)):
            if badge is not None:
                label.setText(" ".join([badge.code, phrase_text(badge.title)]))
                label.setToolTip(" ".join([phrase_text(badge.what), phrase_text(badge.action)]))
        if held is not None:
            self.held_badge.setText(self._with_action(held))

    def _with_action(self, notice: AoiError) -> str:
        """A notice's code, title and what to do, in one line, under the scale or in the status bar (S29 review)."""
        return self.tr("{code} {title}: {action}").format(
            code=notice.code, title=phrase_text(notice.title), action=phrase_text(notice.action)
        )

    def calibrate(self) -> None:
        """Calibrate Scale…: the inline sheet opens, and clicks on the Golden board pick its points; a Try running or
        shown, of another board, goes (S29 review)."""
        self._drop_try()
        self.view.set_image(self.ref, keep_view=True)
        self.draw_btn.setChecked(False)
        self.draw_btn.setEnabled(False)
        self.sheet_user = self.ctx.user
        self.sheet.start()
        self.sheet.show()
        self.view.addAction(self.sheet.esc)  # Esc on the Golden board too, while it picks points (S29 review)
        self.view.set_draw_mode(True, pick=True)
        self._draw_rois()

    def _pick(self, p: QPointF) -> None:
        self.sheet.add_point(p)
        self._draw_rois()

    def _close_sheet(self) -> None:
        """The sheet goes with its points; Draw ROI and panning come back. The focus, if in the sheet, goes back to
        Calibrate Scale…, or to the image view while that is off, where Space and the arrow keys write nothing:
        decided here, not left to the focus chain."""
        held = self.sheet.isAncestorOf(self.window().focusWidget())  # read before the sheet hides and Qt moves it
        self.sheet.hide()
        self.sheet.points = []
        self.view.removeAction(self.sheet.esc)
        self.draw_btn.setEnabled(True)
        self.view.set_draw_mode(self.draw_btn.isChecked())
        self._draw_rois()
        if held and self.isVisible():
            back = self.calibrate_btn if self.calibrate_btn.isEnabled() else self.view  # off: no Golden board
            back.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_scale(self, length_px: float, distance_mm: float) -> None:
        """Set Scale: store the board model's scale (audited), then show the recipe being edited at it, as the engine
        will apply it: a size held in mm, saved so or typed, moves to its px at the new scale, and a size still in px
        stays as it is, so a recipe in px judges as before. The revision as loaded moves so too, so only an edit counts
        as an unsaved change. The status bar names the scale and, while the revision holds sizes in px, AOI-RCP-009.
        A Golden board replaced since the points were picked on it sets nothing, said with AOI-RCP-008 (S29 review)."""
        if (bm := self.checked_board_model()) is None:
            return
        if self.golden_board_stamp() != self.golden_seen:
            self._read_golden_board()
            self._close_sheet()
            self.error(AoiError("AOI-RCP-008", board_model=bm, reason=REPLACED))
            return
        scale = self.ctx.set_scale(bm, length_px, distance_mm)
        self.recipe = self._collect().in_px(scale)
        self._loaded = Recipe.from_dict(copy.deepcopy(self._loaded)).in_px(scale).to_dict()  # as load() shows it now
        self.view.saved = self._saved_rois()
        self.px_per_mm = scale
        self._close_sheet()
        self.min_size.show_recipe(self.recipe, scale)
        self._refresh_rois()
        done = self.tr("Scale of {board_model} set: {scale:.2f} px/mm.").format(board_model=bm, scale=scale)
        held = self.held_in_px()  # sizes still held in px: AOI-RCP-009 and what to do, as under the scale (S29 review)
        then = self.tr("Sizes are shown in mm.") if held is None else self._with_action(held)
        small = self.recipe.size_notice(scale)  # a size held in mm may span under 4 px now: AOI-RCP-007 (S29 review)
        self.shell.status(" ".join([done, *([] if small is None else [self._with_action(small)]), then]))

    # --- actions ----------------------------------------------------------------
    def test_run(self) -> None:
        if not self.need_board_model():
            return
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        f, _ = QFileDialog.getOpenFileName(
            self, self.tr("Image to try the recipe on"), "", self.tr("Images ({extensions})").format(extensions=exts)
        )
        if f:
            self.run_test(f)

    def run_test(self, path: str) -> None:
        """Inspect `path` with the recipe as edited, on a pool thread (REQ-SET-021); the editor stays usable."""
        if (bm := self.checked_board_model()) is None:
            return
        recipe = copy.deepcopy(self._collect())  # the user may keep editing while the test runs
        if not self.sheet.isHidden():  # the Try shows another board: the points picked go with the sheet (S29 review)
            self._close_sheet()
        self.run_in_background(self._inspect_with, bm, path, recipe, on_result=self._show_test, busy=self.busy)

    def _inspect_with(self, board_model: str, path: str, recipe: Recipe) -> InspectionResult:
        """Pool thread: the engine only, never a widget."""
        return self.ctx.inspector(board_model, recipe=recipe).inspect(self.ctx.load_image(path))

    def _show_test(self, res: InspectionResult) -> None:
        self.view.set_image(res.image, keep_view=True)
        self.view.extra = [(d.x, d.y, d.w, d.h, theme.NG_COLOR, f"{d.no} {d.type}") for d in res.defects]
        self._draw_rois()
        result = self.tr("Try result: {verdict}  ·  {defects} defect(s)  ·  {ms:.0f} ms")
        self.test_verdict.setText(
            result.format(verdict=theme.verdict_label(res.verdict), defects=len(res.defects), ms=res.elapsed_ms)
        )
        self.test_verdict.setStyleSheet(theme.verdict_style(res.verdict, big=False))

    def save(self) -> None:
        if (bm := self.checked_board_model()) is None:
            return
        if (latest := self.ctx.recipe(bm)[0]) != self.rev:  # saved since, on Compare: saving would undo it unseen
            if not self._show_latest(latest):
                self.error(AoiError("AOI-RCP-001", board_model=bm, latest=latest, revision=self.rev))
            return
        rev = self.ctx.save_recipe(self._collect().in_mm(self.px_per_mm))  # under a scale, every size in mm
        saved = self.tr("Saved revision {revision} by {user}.").format(revision=rev, user=self.ctx.user)
        QMessageBox.information(self, self.tr("Recipe"), saved)
        self.load()

    def _show_latest(self, latest: int) -> bool:
        """Load revision `latest`, saved after the one the editor holds, unless that would discard an unsaved change
        the user keeps; True when loaded (#173)."""
        if self._collect().to_dict() != self._loaded and not self._discard_ok(latest):
            return False
        before = self.rev
        self._drop_try()
        self.load()
        shown = self.tr("Revision {latest}, saved after revision {revision}, is shown now.")
        self.shell.status(shown.format(latest=latest, revision=before))
        return True

    def _discard_ok(self, latest: int) -> bool:
        """Ask before unsaved changes are discarded for revision `latest`; No is the default, so Enter keeps them."""
        ask = self.tr(
            "Revision {latest} of {board_model} was saved after revision {revision}, which you are editing. Load "
            "revision {latest} and discard your unsaved changes? With No, they stay on screen, but Save Recipe refuses "
            "them until revision {latest} is loaded."
        ).format(latest=latest, board_model=self.board_model, revision=self.rev)
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        answer = QMessageBox.question(self, self.tr("Recipe"), ask, buttons, QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _drop_try(self) -> None:
        """Cancel a running Try and clear the last Try's verdict: they belong to a recipe no longer shown (#173)."""
        if self._bg is not None:
            self._bg.stop()  # run_in_background drops the result of a cancelled job
            self._bg = None
            self.busy.finish()
        self.test_verdict.clear()
        self.test_verdict.setStyleSheet("")
        self.view.extra = []

    def _draw_rois(self) -> None:
        """The ROIs on the board shown, the selected one with its handles (`RoiEditor`), and the points picked."""
        self.view.marks = self.sheet.points  # none while the sheet is closed
        self.view.show_boxes(self.edited_recipe.rois, self._sel_index())

    def on_board_model_changed(self, name: str | None) -> None:
        self._drop_try()
        self.load()

    def on_show(self) -> None:
        if self.recipe is None or self.recipe.board_model != self.board_model:
            self.load()
            return
        if not self.sheet.isHidden() and self.sheet_user != self.ctx.user:
            self._close_sheet()  # the points picked are another user's: not theirs to set (S29 review)
        if self.golden_board_stamp() != self.golden_seen:  # Set Reference, training, or the file put back, replaced
            self._drop_try()  # or gone since (#176 review): a Try was judged against the Golden board before (#173)
            self._read_golden_board()
            self._close_sheet()  # and points picked on the Golden board before go with it (S29 review)
        else:
            self._show_golden_board()  # the role may have changed since load() built it
        if self.board_model and (latest := self.ctx.recipe(self.board_model)[0]) != self.rev:
            self._show_latest(latest)  # saved since, on Compare: shown, so that Save never reverts it
        self.show_calibrated(self.ai_thr, self.board_model)  # an AI model trained or activated since: its value
