"""Recipe Editor (spec 4.2): draw ROIs on the golden board and set thresholds."""

from __future__ import annotations

from PySide6.QtCore import Qt
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
from ...core.imaging import IMAGE_EXTS, load_image
from ...core.recipe import ROI, ROI_TYPES, Recipe
from ..theme import verdict_style
from ..widgets.image_view import ImageView
from .base import Page, button, fill_table, make_table


def _opt_spin(maxv=1e4):
    s = QDoubleSpinBox()
    s.setRange(-1, maxv)
    s.setDecimals(3)
    s.setSpecialValueText("—")
    s.setValue(-1)
    return s


class RecipeEditorPage(Page):
    title = "Recipe Editor"
    subtitle = "Draw ROIs on the golden board · zoom with the wheel · double-click to fit"
    roles = ("Engineer", "Admin")

    def __init__(self, ctx, shell):
        super().__init__(ctx, shell)
        self.recipe: Recipe | None = None
        self.rev = 0
        self.ref = None

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.draw_btn = button("Draw ROI", "primary", self.toggle_draw)
        self.draw_btn.setCheckable(True)
        tools.addWidget(self.draw_btn)
        tools.addWidget(QLabel("Type:"))
        self.roi_type = QComboBox()
        self.roi_type.addItems(ROI_TYPES)
        tools.addWidget(self.roi_type)
        tools.addStretch(1)
        ll.addLayout(tools)
        self.view = ImageView(placeholder="Train a model or set a reference image first")
        self.view.roiDrawn.connect(self.add_roi)
        ll.addWidget(self.view, 1)
        split.addWidget(left)

        tabs = QTabWidget()
        # ROI tab
        roi_tab = QWidget()
        roi_tab.setObjectName("page")
        rl = QVBoxLayout(roi_tab)
        self.roi_table = make_table(["Name", "Type", "X", "Y", "W", "H", "AI Score"], sortable=False)
        self.roi_table.itemSelectionChanged.connect(self._select_roi)
        rl.addWidget(self.roi_table, 1)
        g = QGroupBox("Selected ROI")
        f = QFormLayout(g)
        self.r_name = QLineEdit()
        self.r_type = QComboBox()
        self.r_type.addItems(ROI_TYPES)
        self.r_ai = QDoubleSpinBox()
        self.r_ai.setRange(0.05, 100)
        self.r_ai.setSingleStep(0.1)
        self.r_hmin, self.r_hmax, self.r_vmin, self.r_vmax = (_opt_spin() for _ in range(4))
        self.r_enabled = QCheckBox("Enabled")
        f.addRow("Name", self.r_name)
        f.addRow("ROI type", self.r_type)
        f.addRow("AI Score (× model threshold)", self.r_ai)
        f.addRow("Height Min / Max (Stage 2)", self._pair(self.r_hmin, self.r_hmax))
        f.addRow("Volume Min / Max (Stage 2)", self._pair(self.r_vmin, self.r_vmax))
        f.addRow(self.r_enabled)
        row = QHBoxLayout()
        row.addWidget(button("Apply", slot=self.apply_roi))
        row.addWidget(button("Delete", slot=self.delete_roi))
        f.addRow(row)
        rl.addWidget(g)
        tabs.addTab(roi_tab, "ROIs")

        # Global thresholds tab
        thr_tab = QWidget()
        thr_tab.setObjectName("page")
        tf = QFormLayout(thr_tab)
        self.use_ai = QCheckBox("Use self-trained AI model")
        self.use_cmp = QCheckBox("Use golden comparison")
        self.ai_thr = QDoubleSpinBox()
        self.ai_thr.setRange(0, 1e4)
        self.ai_thr.setDecimals(3)
        self.ai_thr.setSpecialValueText("model default")
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
            (self.ai_thr, "AI anomaly threshold"),
            (self.warn, "Warning band (fraction of threshold)"),
            (self.use_cmp, None),
            (self.diff, "Pixel difference (0-255)"),
            (self.area, "Min defect area (px)"),
            (self.ssim, "SSIM minimum"),
            (self.chg, "Max changed area %"),
            (self.maxreg, "Allowed difference regions"),
        ):
            tf.addRow(label, w) if label else tf.addRow(w)
        tabs.addTab(thr_tab, "Thresholds")

        # Mandatory defect set tab (classification table §4)
        mand = QWidget()
        mand.setObjectName("page")
        ml = QVBoxLayout(mand)
        ml.addWidget(QLabel("Mandatory AOI defect set (must be covered by every recipe):"))
        self.mand_list = QListWidget()
        ml.addWidget(self.mand_list, 1)
        tabs.addTab(mand, "Mandatory Set")

        # History tab
        hist = QWidget()
        hist.setObjectName("page")
        hl = QVBoxLayout(hist)
        self.history = make_table(["Revision", "User", "Saved"])
        hl.addWidget(self.history)
        tabs.addTab(hist, "Revisions")

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)
        rv.addWidget(tabs, 1)
        self.test_verdict = QLabel("")
        self.test_verdict.setMinimumHeight(40)
        rv.addWidget(self.test_verdict)
        b = QHBoxLayout()
        b.addWidget(button("Test Run…", slot=self.test_run))
        b.addWidget(button("Save Recipe", "primary", self.save))
        rv.addLayout(b)
        split.addWidget(right)
        split.setSizes([1000, 640])
        self.root.addWidget(split, 1)

    @staticmethod
    def _pair(a, b):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.addWidget(a)
        l.addWidget(b)
        return w

    # --- load / show ------------------------------------------------------------
    def load(self):
        if not self.board_model:
            return
        self.rev, self.recipe = self.ctx.recipe(self.board_model)
        ref_path = self.ctx.db.reference(self.board_model)
        self.ref = load_image(ref_path) if ref_path else None
        self.view.set_image(self.ref)
        r = self.recipe
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
            [[h["revision"], h["user"], h["created_at"]] for h in self.ctx.db.recipe_history(self.board_model)],
        )
        self._refresh_rois()

    def _refresh_rois(self):
        r = self.recipe
        fill_table(self.roi_table, [[x.name, x.type, x.x, x.y, x.w, x.h, x.ai_score] for x in r.rois])
        self.view.clear_overlays()
        sel = self._sel_index()
        for i, x in enumerate(r.rois):
            # spec: yellow = active (being edited), green = saved
            color = "#fdd835" if i == sel else "#43a047" if x.enabled else "#6c7c8c"
            self.view.add_box(x.x, x.y, x.w, x.h, color, f"{x.name} [{x.type}]")
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
                mark = "◌  needs Stage 2 (3D / side camera)"
            elif roi_for.get(name) in covered:
                mark = "✓  ROI defined"
            else:
                mark = "•  covered by whole-board AI + compare"
            self.mand_list.addItem(f"{name:<24}  {mark}")

    def _sel_index(self) -> int:
        rows = self.roi_table.selectionModel().selectedRows() if self.roi_table.selectionModel() else []
        return rows[0].row() if rows else -1

    # --- ROI editing ------------------------------------------------------------
    def toggle_draw(self):
        self.view.set_draw_mode(self.draw_btn.isChecked())

    def add_roi(self, rect):
        n = len(self.recipe.rois) + 1
        self.recipe.rois.append(
            ROI(
                f"R{n}",
                self.roi_type.currentText(),
                int(rect.x()),
                int(rect.y()),
                int(rect.width()),
                int(rect.height()),
            )
        )
        self._refresh_rois()
        self.roi_table.selectRow(len(self.recipe.rois) - 1)

    def _select_roi(self):
        i = self._sel_index()
        if i < 0:
            return
        x = self.recipe.rois[i]
        self.r_name.setText(x.name)
        self.r_type.setCurrentText(x.type)
        self.r_ai.setValue(x.ai_score)
        for w, v in (
            (self.r_hmin, x.height_min),
            (self.r_hmax, x.height_max),
            (self.r_vmin, x.volume_min),
            (self.r_vmax, x.volume_max),
        ):
            w.setValue(-1 if v is None else v)
        self.r_enabled.setChecked(x.enabled)
        self.view.clear_overlays()
        for j, r in enumerate(self.recipe.rois):
            self.view.add_box(r.x, r.y, r.w, r.h, "#fdd835" if j == i else "#43a047", f"{r.name} [{r.type}]")

    def apply_roi(self):
        i = self._sel_index()
        if i < 0:
            return
        x = self.recipe.rois[i]
        x.name, x.type, x.ai_score, x.enabled = (
            self.r_name.text(),
            self.r_type.currentText(),
            self.r_ai.value(),
            self.r_enabled.isChecked(),
        )
        opt = lambda w: None if w.value() < 0 else w.value()
        x.height_min, x.height_max, x.volume_min, x.volume_max = (
            opt(self.r_hmin),
            opt(self.r_hmax),
            opt(self.r_vmin),
            opt(self.r_vmax),
        )
        self._refresh_rois()

    def delete_roi(self):
        i = self._sel_index()
        if i >= 0:
            del self.recipe.rois[i]
            self._refresh_rois()

    def _collect(self) -> Recipe:
        r = self.recipe
        r.use_ai, r.use_compare = self.use_ai.isChecked(), self.use_cmp.isChecked()
        r.anomaly_threshold = self.ai_thr.value() or None
        r.warn_ratio, r.diff_threshold, r.min_defect_area = self.warn.value(), self.diff.value(), self.area.value()
        r.ssim_min, r.changed_pct_max, r.max_diff_regions = self.ssim.value(), self.chg.value(), self.maxreg.value()
        return r

    # --- actions ----------------------------------------------------------------
    def test_run(self):
        if not self.need_board_model():
            return
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        f, _ = QFileDialog.getOpenFileName(self, "Test image", "", f"Images ({exts})")
        if not f:
            return
        insp = self.ctx.inspector(self.board_model, recipe=self._collect())
        res = insp.inspect(load_image(f))
        self.view.set_image(res.image, keep_view=True)
        for d in res.defects:
            self.view.add_box(d.x, d.y, d.w, d.h, "#e53935", f"{d.no} {d.type}")
        for x in self.recipe.rois:
            self.view.add_box(x.x, x.y, x.w, x.h, "#43a047", dashed=True)
        self.test_verdict.setText(
            f"Test run: {res.verdict}  ·  {len(res.defects)} defect(s)  ·  {res.elapsed_ms:.0f} ms"
        )
        self.test_verdict.setStyleSheet(verdict_style(res.verdict, big=False))

    def save(self):
        if not self.need_board_model():
            return
        rev = self.ctx.save_recipe(self._collect())
        QMessageBox.information(self, "Recipe", f"Saved revision {rev} by {self.ctx.user}.")
        self.load()

    def on_board_model_changed(self, name):
        self.load()

    def on_show(self):
        if self.recipe is None or self.recipe.board_model != self.board_model:
            self.load()
