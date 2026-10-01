"""Side-by-side Compare page.

Optional page (reachable from the sidebar or "Compare with Golden" on the
Inspection screen) that shows the golden reference next to a test board and
every metric that decided OK / WARN / NG, with what-if thresholds.
"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
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
from ...core.imaging import IMAGE_EXTS, heat_overlay, load_image
from ...errors import AoiError
from .. import theme
from ..widgets.busy import BusyOverlay
from ..widgets.image_view import ImageView
from .base import Page, button, fill_table, make_table

MODES = ["Side by side", "Difference heatmap", "AI anomaly heatmap", "Defect boxes only"]


class ComparePage(Page):
    title = "Compare"
    subtitle = "Golden reference vs. test board, with the metrics behind the verdict"

    def __init__(self, ctx, shell):
        super().__init__(ctx, shell)
        self.test_path: str | None = None
        self.ref_override: str | None = None
        self.res = None
        self._fitted = False

        bar = QHBoxLayout()
        bar.addWidget(button("Test Image…", slot=self.pick_test))
        bar.addWidget(button("Use Last Inspected", slot=self.use_last))
        bar.addWidget(button("Reference…", slot=self.pick_ref))
        bar.addWidget(button("Golden Template", slot=self.use_golden))
        bar.addWidget(QLabel("Show:"))
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        self.mode.currentIndexChanged.connect(self.render)
        bar.addWidget(self.mode)
        bar.addStretch(1)
        self.root.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        views = QWidget()
        vl = QHBoxLayout(views)
        vl.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        right = QVBoxLayout()
        self.ref_label = QLabel("Reference (golden)")
        self.ref_label.setObjectName("muted")
        self.test_label = QLabel("Test board")
        self.test_label.setObjectName("muted")
        self.ref_view = ImageView(placeholder="Golden reference")
        self.test_view = ImageView(placeholder="Pick a test image")
        self.ref_view.link(self.test_view)  # zoom/pan stay in sync
        self.busy = BusyOverlay(self.test_view, self.tr("Inspecting…"))  # where the result will appear
        left.addWidget(self.ref_label)
        left.addWidget(self.ref_view, 1)
        right.addWidget(self.test_label)
        right.addWidget(self.test_view, 1)
        vl.addLayout(left, 1)
        vl.addLayout(right, 1)
        split.addWidget(views)

        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(8, 0, 0, 0)
        self.verdict = QLabel("—")
        self.verdict.setStyleSheet(theme.verdict_style("INFO"))
        self.verdict.setMinimumHeight(theme.BANNER_H)
        pl.addWidget(self.verdict)
        self.metrics = make_table(["Check", "Source", "Value", "Thr.", "Rule", "Result"], sortable=False)
        hh = self.metrics.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        self.metrics.setWordWrap(True)
        pl.addWidget(self.metrics, 2)
        self.why = QTextEdit()
        self.why.setReadOnly(True)
        self.why.setMaximumHeight(150)
        pl.addWidget(self.why)

        g = QGroupBox("What-if thresholds (not saved until you press Save to Recipe)")
        f = QFormLayout(g)
        self.ai_thr = QDoubleSpinBox()
        self.ai_thr.setDecimals(3)
        self.ai_thr.setRange(0, 1e4)
        self.ai_thr.setSpecialValueText("model default")
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
        f.addRow("AI anomaly threshold", self.ai_thr)
        f.addRow("Pixel difference (0-255)", self.diff_thr)
        f.addRow("Min defect area (px)", self.min_area)
        f.addRow("SSIM minimum", self.ssim_min)
        f.addRow("Allowed difference regions", self.max_regions)
        row = QHBoxLayout()
        row.addWidget(button("Re-evaluate", "primary", self.run))
        self.btn_save = button("Save to Recipe", slot=self.save_recipe)
        row.addWidget(self.btn_save)
        f.addRow(row)
        pl.addWidget(g)
        split.addWidget(panel)
        split.setSizes([980, 740])
        self.root.addWidget(split, 1)

    # --- inputs ------------------------------------------------------------------
    def set_test(self, path: str):
        self.test_path = path
        self._fitted = False
        self.run()

    def pick_test(self):
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        f, _ = QFileDialog.getOpenFileName(self, "Test image", "", f"Images ({exts})")
        if f:
            self.set_test(f)

    def use_last(self):
        if self.shell.last_inspected:
            self.set_test(self.shell.last_inspected[0])

    def pick_ref(self):
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        f, _ = QFileDialog.getOpenFileName(self, "Reference image", "", f"Images ({exts})")
        if f:
            self.ref_override = f
            self.run()

    def use_golden(self):
        self.ref_override = None
        self.run()

    def _load_recipe_into_form(self):
        if not self.board_model:
            return
        _, r = self.ctx.recipe(self.board_model)
        self.ai_thr.setValue(r.anomaly_threshold or 0)
        self.diff_thr.setValue(r.diff_threshold)
        self.min_area.setValue(r.min_defect_area)
        self.ssim_min.setValue(r.ssim_min)
        self.max_regions.setValue(r.max_diff_regions)

    def _form_recipe(self):
        _, r = self.ctx.recipe(self.board_model)
        r = copy.deepcopy(r)
        r.anomaly_threshold = self.ai_thr.value() or None
        r.diff_threshold = self.diff_thr.value()
        r.min_defect_area = self.min_area.value()
        r.ssim_min = self.ssim_min.value()
        r.max_diff_regions = self.max_regions.value()
        return r

    # --- evaluate ----------------------------------------------------------------
    def run(self):
        """Load the reference and inspect the test image on a pool thread (REQ-SET-021); the form is read here."""
        if not self.board_model:
            return
        if self.test_path:
            self.test_label.setText(f"Test: {Path(self.test_path).name}")
        recipe = self._form_recipe() if self.test_path else None
        self.run_in_background(
            self._evaluate, self.board_model, self.test_path, self.ref_override, recipe,
            on_result=self._on_evaluated, busy=self.busy if self.test_path else None,
        )  # fmt: skip

    def _evaluate(self, board_model, test_path, ref_path, recipe):
        """Pool thread: files and the engine only, never a widget."""
        ref = load_image(ref_path) if ref_path else self.ctx.inspector(board_model).reference
        res = self.ctx.inspect(board_model, load_image(test_path), recipe, reference=ref) if test_path else None
        return ref, res

    def _on_evaluated(self, out):
        ref, res = out
        self.ref_label.setText(
            "Reference: "
            + (
                Path(self.ref_override).name
                if self.ref_override
                else "golden template"
                if ref is not None
                else "none set"
            )
        )
        self.ref_view.set_image(ref)
        if res is None:
            return
        self.res = r = res
        self.verdict.setText(r.verdict)
        self.verdict.setStyleSheet(theme.verdict_style(r.verdict))
        rows, colors = [], []
        for c in r.checks:
            rows.append([c.name, c.source, float(c.value), float(c.threshold), c.rule, c.verdict])
            colors.append(None if c.verdict in ("OK", "INFO") else theme.VERDICT_COLORS[c.verdict])
        rows.append(
            [
                "Inspection time (ms)",
                "System",
                float(r.elapsed_ms),
                1000.0,
                "spec < 1 s",
                "OK" if r.elapsed_ms < 1000 else "WARN",
            ]
        )
        colors.append(None)
        fill_table(self.metrics, rows, colors)
        self.why.setHtml(self._explain())
        self.render()

    def _explain(self) -> str:
        r = self.res
        failing = [c for c in r.checks if c.verdict in ("NG", "WARN")]
        lines = [f"<b>Verdict {r.verdict}</b>: "]
        if not failing:
            lines.append("every check is inside its threshold.")
        else:
            lines.append(
                "decided by "
                + "; ".join(
                    f"<b>{c.name}</b> = {c.value:.3g} (threshold {c.threshold:.3g}, rule {c.rule})" for c in failing
                )
                + "."
            )
        if r.defects:
            lines.append(
                "<br>Regions: "
                + ", ".join(f"#{d.no} {d.type} at ({d.x},{d.y}) {d.w}×{d.h}px [{d.source}]" for d in r.defects)
            )
        for n in r.notes:
            lines.append(f"<br><i>{n}</i>")
        return "".join(lines)

    def render(self):
        r = self.res
        if r is None:
            return
        mode = self.mode.currentText()
        img = r.image
        if mode == "Difference heatmap" and r.compare is not None:
            img = heat_overlay(r.image, r.compare.diff_map, vmax=max(1, 1.5 * self.diff_thr.value()))
        elif mode == "AI anomaly heatmap" and r.anomaly_map is not None:
            thr = r.checks and next((c.threshold for c in r.checks if c.source == "AI"), None)
            img = heat_overlay(r.image, r.anomaly_map, vmax=(thr or float(np.max(r.anomaly_map))) * 1.5)
        self.test_view.set_image(img, keep_view=self._fitted)
        self._fitted = True
        for d in r.defects:
            sev = taxonomy.BY_NAME.get(d.type, taxonomy.ANOMALY).severity
            color = theme.SEVERITY_COLORS.get(sev, theme.NG_COLOR)
            self.test_view.add_box(d.x, d.y, d.w, d.h, color, f"{d.no} {d.type}")
            self.ref_view.add_box(d.x, d.y, d.w, d.h, color, f"{d.no}", dashed=True)

    def save_recipe(self):
        if self.ctx.role == "Operator":
            return self.error(AoiError("AOI-USR-001", what="Changing recipes", roles="Engineer or Admin"))
        rev = self.ctx.save_recipe(self._form_recipe())
        self.shell.status(f"Recipe saved as revision {rev}")

    def on_board_model_changed(self, name):
        self.res = None
        self._load_recipe_into_form()
        if name:
            self.run()

    def on_show(self):
        self.btn_save.setEnabled(self.ctx.role != "Operator")
        if self.ai_thr.value() == 0 and self.diff_thr.value() == 1:
            self._load_recipe_into_form()
