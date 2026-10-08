"""Recipe Editor (spec 4.2): draw ROIs on the golden board and set thresholds."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QRectF, Qt
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
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..widgets.image_view import ImageView
from .base import QT_TRANSLATE_NOOP, Page, button, fill_table, make_table

if TYPE_CHECKING:
    from ..main_window import MainWindow

ROI_TYPE_NAMES = {  # the recipe stores the English type (ROI_TYPES); the editor shows it in the UI language
    "Presence": QT_TRANSLATE_NOOP("RecipeEditorPage", "Presence"),
    "Polarity": QT_TRANSLATE_NOOP("RecipeEditorPage", "Polarity"),
    "Solder Bridge": QT_TRANSLATE_NOOP("RecipeEditorPage", "Solder Bridge"),
    "Height": QT_TRANSLATE_NOOP("RecipeEditorPage", "Height"),
    "Anomaly": QT_TRANSLATE_NOOP("RecipeEditorPage", "Anomaly"),
}


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
        self.view = ImageView(placeholder="")
        self.view_empty = EmptyState(self.view)
        self.view.roiDrawn.connect(self.add_roi)
        self.busy = BusyOverlay(self.view, self.tr("Trying the recipe…"))
        ll.addWidget(self.view, 1)
        split.addWidget(left)

        tabs = QTabWidget()
        # ROI tab
        roi_tab = QWidget()
        roi_tab.setObjectName("page")
        rl = QVBoxLayout(roi_tab)
        headers = [self.tr("Name"), self.tr("Type"), self.tr("X"), self.tr("Y"), self.tr("W"), self.tr("H")]
        self.roi_table = make_table([*headers, self.tr("AI score")], sortable=False)  # literals, so lupdate finds them
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
        f.addRow(self.tr("AI score (× AI model threshold)"), self.r_ai)
        f.addRow(self.tr("Height min / max (Stage 2)"), self._pair(self.r_hmin, self.r_hmax))
        f.addRow(self.tr("Volume min / max (Stage 2)"), self._pair(self.r_vmin, self.r_vmax))
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
        self.ai_thr = QDoubleSpinBox()
        self.ai_thr.setRange(0, 1e4)
        self.ai_thr.setDecimals(3)
        self.ai_thr.setSpecialValueText(self.tr("AI model default"))
        self.warn = QDoubleSpinBox()
        self.warn.setRange(0.1, 1)
        self.warn.setSingleStep(0.05)
        self.diff = QSpinBox()
        self.diff.setRange(1, 255)
        self.area = QSpinBox()
        self.area.setRange(1, 100000)
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
            (self.warn, self.tr("WARN band (fraction of the threshold)")),
            (self.use_cmp, None),
            (self.diff, self.tr("Pixel difference (0-255)")),
            (self.area, self.tr("Minimum defect area (px)")),
            (self.ssim, self.tr("Similarity minimum (SSIM)")),
            (self.chg, self.tr("Maximum changed area %")),
            (self.maxreg, self.tr("Allowed difference regions")),
        ):
            tf.addRow(label, w) if label else tf.addRow(w)
        tabs.addTab(thr_tab, self.tr("Thresholds"))

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
            self.view_empty.show_state(*self.no_board_model())
            return
        self.rev, r = self.ctx.recipe(self.board_model)
        self.recipe = r
        self._read_golden_board()
        self.use_ai.setChecked(r.use_ai)
        self.use_cmp.setChecked(r.use_compare)
        self.ai_thr.setValue(r.anomaly_threshold or 0)
        self.warn.setValue(r.warn_ratio)
        self.diff.setValue(r.diff_threshold)
        self.area.setValue(r.min_defect_area)
        self.ssim.setValue(r.ssim_min)
        self.chg.setValue(r.changed_pct_max)
        self.maxreg.setValue(r.max_diff_regions)
        fill_table(
            self.history,
            [[h["revision"], h["user"], to_local(h["created_at"])] for h in self.ctx.recipe_history(self.board_model)],
        )
        self._refresh_rois()
        self._loaded = self._collect().to_dict()  # as the form shows it, rounded to its spin boxes

    def _read_golden_board(self) -> None:
        """Read the board model's Golden board into the view. A file gone or damaged must not stop the window opening
        on this board model (#176): its error is kept for the pane, logged and alarmed (#195)."""
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

    def _refresh_rois(self) -> None:
        r = self.edited_recipe
        fill_table(self.roi_table, [[x.name, x.type, x.x, x.y, x.w, x.h, x.ai_score] for x in r.rois])
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
        if i < 0:
            return
        self.view.clear_overlays()
        for j, r in enumerate(rois):
            color = theme.ROI_SELECTED if j == i else theme.ROI_COLOR
            self.view.add_box(r.x, r.y, r.w, r.h, color, f"{r.name} [{self._type_text(r.type)}]")

    def apply_roi(self) -> None:
        i = self._sel_index()
        if i < 0:
            return
        x = self.edited_recipe.rois[i]
        limits = [self._limit(w) for w in (self.r_hmin, self.r_hmax, self.r_vmin, self.r_vmax)]
        height, volume = QT_TRANSLATE_NOOP("Errors", "Height"), QT_TRANSLATE_NOOP("Errors", "Volume")
        for quantity, (low, high) in ((height, limits[:2]), (volume, limits[2:])):
            negative = any(v is not None and v < 0 for v in (low, high))
            if negative or (low is not None and high is not None and low > high):
                shown = ["—" if v is None else f"{v:g}" for v in (low, high)]
                self.error(AoiError("AOI-RCP-002", roi=x.name, quantity=quantity, low=shown[0], high=shown[1]))
                return  # nothing applied: a Stage 2 check would fail every board on these limits (#173)
        x.name, x.type, x.ai_score, x.enabled = (
            self.r_name.text(),
            self.r_type.currentData(),
            self.r_ai.value(),
            self.r_enabled.isChecked(),
        )
        x.height_min, x.height_max, x.volume_min, x.volume_max = limits
        self._refresh_rois()

    @staticmethod
    def _limit(w: QDoubleSpinBox) -> float | None:
        """A Stage 2 limit: None only at the spin box's own "—" (its minimum, -1); any other number is kept as typed."""
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
        r.anomaly_threshold = self.ai_thr.value() or None
        r.warn_ratio, r.diff_threshold, r.min_defect_area = self.warn.value(), self.diff.value(), self.area.value()
        r.ssim_min, r.changed_pct_max, r.max_diff_regions = self.ssim.value(), self.chg.value(), self.maxreg.value()
        return r

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
        self.run_in_background(self._inspect_with, bm, path, recipe, on_result=self._show_test, busy=self.busy)

    def _inspect_with(self, board_model: str, path: str, recipe: Recipe) -> InspectionResult:
        """Pool thread: the engine only, never a widget."""
        return self.ctx.inspector(board_model, recipe=recipe).inspect(self.ctx.load_image(path))

    def _show_test(self, res: InspectionResult) -> None:
        self.view.set_image(res.image, keep_view=True)
        for d in res.defects:
            self.view.add_box(d.x, d.y, d.w, d.h, theme.NG_COLOR, f"{d.no} {d.type}")
        for x in self.edited_recipe.rois:
            self.view.add_box(x.x, x.y, x.w, x.h, theme.ROI_COLOR, dashed=True)
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
        rev = self.ctx.save_recipe(self._collect())
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

    def _draw_rois(self) -> None:
        self.view.clear_overlays()
        sel = self._sel_index()
        for i, x in enumerate(self.edited_recipe.rois):
            # spec: yellow = active (being edited), green = saved
            color = theme.ROI_SELECTED if i == sel else theme.ROI_COLOR if x.enabled else theme.ROI_DISABLED
            self.view.add_box(x.x, x.y, x.w, x.h, color, f"{x.name} [{self._type_text(x.type)}]")

    def on_board_model_changed(self, name: str | None) -> None:
        self._drop_try()
        self.load()

    def on_show(self) -> None:
        if self.recipe is None or self.recipe.board_model != self.board_model:
            self.load()
            return
        if self.golden_board_stamp() != self.golden_seen:  # Set Reference, training, or the file put back, replaced
            self._drop_try()  # or gone since (#176 review): a Try was judged against the Golden board before (#173)
            self._read_golden_board()
            self._draw_rois()
        else:
            self._show_golden_board()  # the role may have changed since load() built it
        if self.board_model and (latest := self.ctx.recipe(self.board_model)[0]) != self.rev:
            self._show_latest(latest)  # saved since, on Compare: shown, so that Save never reverts it
