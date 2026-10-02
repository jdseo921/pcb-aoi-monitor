"""Side-by-side Compare page.

Optional page (reachable from the sidebar or "Compare with Golden" on the
Inspection screen) that shows the golden reference next to a test board and
every metric that decided OK / WARN / NG, with what-if thresholds.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import TYPE_CHECKING

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
from ...core.imaging import IMAGE_EXTS, heat_overlay
from ...core.inspector import Check, InspectionResult
from ...core.recipe import Recipe
from ...core.services import AppContext
from ...errors import AoiError
from .. import theme
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..widgets.image_view import ImageView
from .base import QT_TRANSLATE_NOOP, Page, button, fill_table, make_table

if TYPE_CHECKING:
    from ..main_window import MainWindow

MODES = [  # the Show combo, in this order; shown through tr()
    QT_TRANSLATE_NOOP("ComparePage", "Side by side"),
    QT_TRANSLATE_NOOP("ComparePage", "Difference heatmap"),
    QT_TRANSLATE_NOOP("ComparePage", "AI score heatmap"),
    QT_TRANSLATE_NOOP("ComparePage", "Defect boxes only"),
]
MODE_DIFF, MODE_AI = 1, 2

# The engine names its checks, their sources and rules in English and stores them with the result; the page shows
# them in the UI language. An ROI check is named after the ROI and shows as the engine wrote it.
CHECK_NAMES = {
    "SSIM similarity": QT_TRANSLATE_NOOP("ComparePage", "Similarity (SSIM)"),
    "Changed area %": QT_TRANSLATE_NOOP("ComparePage", "Changed area %"),
    "Difference regions": QT_TRANSLATE_NOOP("ComparePage", "Difference regions"),
    "Alignment inliers": QT_TRANSLATE_NOOP("ComparePage", "Alignment inliers"),
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
        self.res: InspectionResult | None = None
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
        vl = QHBoxLayout(views)
        vl.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        right = QVBoxLayout()
        self.ref_label = QLabel(self.tr("Golden board"))
        self.ref_label.setObjectName("muted")
        self.test_label = QLabel(self.tr("Test board"))
        self.test_label.setObjectName("muted")
        self.ref_view = ImageView(placeholder="")
        self.test_view = ImageView(placeholder="")
        self.ref_empty, self.test_empty = EmptyState(self.ref_view), EmptyState(self.test_view)
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
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
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
        split.setSizes([980, 740])
        self.root.addWidget(split, 1)

    # --- inputs ------------------------------------------------------------------
    def set_test(self, path: str) -> None:
        self.test_path = path
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
        if self.shell.last_inspected:
            self.set_test(self.shell.last_inspected[0])

    def pick_ref(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        f, _ = QFileDialog.getOpenFileName(
            self, self.tr("Reference image"), "", self.tr("Images ({extensions})").format(extensions=exts)
        )
        if f:
            self.ref_override = f
            self.run()

    def use_golden(self) -> None:
        self.ref_override = None
        self.run()

    def _load_recipe_into_form(self) -> None:
        if not self.board_model:
            return
        _, r = self.ctx.recipe(self.board_model)
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
        bm = self.board_model
        if not bm:
            return
        if self.test_path:
            self.test_label.setText(self.tr("Test board: {file}").format(file=Path(self.test_path).name))
        recipe = self._form_recipe(bm) if self.test_path else None
        self.run_in_background(
            self._evaluate, bm, self.test_path, self.ref_override, recipe,
            on_result=self._on_evaluated, busy=self.busy if self.test_path else None,
        )  # fmt: skip

    def _evaluate(
        self, board_model: str, test_path: str | None, ref_path: str | None, recipe: Recipe | None
    ) -> tuple[np.ndarray | None, InspectionResult | None]:
        """Pool thread: files and the engine only, never a widget."""
        ref = self.ctx.load_image(ref_path) if ref_path else self.ctx.inspector(board_model).reference
        test = self.ctx.load_image(test_path) if test_path else None
        res = self.ctx.inspect(board_model, test, recipe, reference=ref) if test is not None else None
        return ref, res

    def _on_evaluated(self, out: tuple[np.ndarray | None, InspectionResult | None]) -> None:
        ref, res = out
        if self.ref_override:
            self.ref_label.setText(self.tr("Reference: {file}").format(file=Path(self.ref_override).name))
        elif ref is not None:
            self.ref_label.setText(self.tr("Reference: Golden board"))
        else:
            self.ref_label.setText(self.tr("Reference: none set"))
        self.ref_view.set_image(ref)
        if ref is None and self.board_model:
            step = self.empty_step(self.tr("Train an AI model on Training."), "Training")
            heading = self.tr("No Golden board for {board_model} yet").format(board_model=self.board_model)
            self.ref_empty.show_state(heading, *step)
        else:
            self.ref_empty.hide()
        if res is None:
            return
        self.res = r = res
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
        self.redraw()

    def _check_text(self, c: Check) -> tuple[str, str, str]:
        """A check's name, source and rule in the UI language (CHECK_NAMES, SOURCES, RULES)."""
        name = self.tr(CHECK_NAMES[c.name]) if c.name in CHECK_NAMES else c.name
        return name, self.tr(SOURCES.get(c.source, c.source)), self.tr(RULES.get(c.rule, c.rule))

    def _explain(self, r: InspectionResult) -> str:
        failing = [c for c in r.checks if c.verdict in ("NG", "WARN")]
        if not failing:
            lines = [
                self.tr("<b>Verdict {verdict}</b>: every check is inside its threshold.").format(verdict=r.verdict)
            ]
        else:
            parts = []
            for c in failing:
                name, _, rule = self._check_text(c)
                parts.append(
                    self.tr("<b>{check}</b> = {value:.3g} (threshold {threshold:.3g}, rule {rule})").format(
                        check=name, value=c.value, threshold=c.threshold, rule=rule
                    )
                )
            checks = "; ".join(parts)
            lines = [self.tr("<b>Verdict {verdict}</b>: decided by {checks}.").format(verdict=r.verdict, checks=checks)]
        if r.defects:
            regions = ", ".join(
                self.tr("#{no} {type} at ({x},{y}) {w}×{h} px [{source}]").format(
                    no=d.no, type=d.type, x=d.x, y=d.y, w=d.w, h=d.h, source=d.source
                )
                for d in r.defects
            )
            lines.append(self.tr("<br>Regions: {regions}").format(regions=regions))
        for n in r.notes:
            lines.append(f"<br><i>{n}</i>")
        return "".join(lines)

    def redraw(self) -> None:
        r = self.res
        if r is None:
            return
        mode = self.mode.currentIndex()
        img = r.image  # typed Optional; the engine always sets it, so the guards below narrow for mypy only
        if img is not None and mode == MODE_DIFF and r.compare is not None and r.compare.diff_map is not None:
            img = heat_overlay(img, r.compare.diff_map, vmax=max(1, 1.5 * self.diff_thr.value()))
        elif img is not None and mode == MODE_AI and r.anomaly_map is not None:
            thr = next((c.threshold for c in r.checks if c.source == "AI"), None)
            img = heat_overlay(img, r.anomaly_map, vmax=(thr or float(np.max(r.anomaly_map))) * 1.5)
        self.test_view.set_image(img, keep_view=self._fitted)
        self._fitted = True
        for d in r.defects:
            sev = taxonomy.BY_NAME.get(d.type, taxonomy.ANOMALY).severity
            color = theme.SEVERITY_COLORS.get(sev, theme.NG_COLOR)
            self.test_view.add_box(d.x, d.y, d.w, d.h, color, f"{d.no} {d.type}")
            self.ref_view.add_box(d.x, d.y, d.w, d.h, color, f"{d.no}", dashed=True)

    def save_recipe(self) -> None:
        if self.ctx.role == "Operator":
            self.error(AoiError("AOI-USR-001", what="Changing recipes", roles="Engineer or Admin"))
            return
        if (bm := self.checked_board_model()) is None:
            return
        rev = self.ctx.save_recipe(self._form_recipe(bm))
        self.shell.status(self.tr("Recipe saved as revision {revision}").format(revision=rev))

    def on_board_model_changed(self, name: str | None) -> None:
        self.res = None
        self._load_recipe_into_form()
        if name:
            self.run()

    def on_show(self) -> None:
        self.btn_save.setEnabled(self.ctx.role != "Operator")
        if self.res is None and self.test_path is None:
            step = self.empty_step(self.tr("Inspect a board on Inspection, or pick a test image."), "Inspection")
            self.test_empty.show_state(self.tr("No board to compare yet"), *step)
        if self.ai_thr.value() == 0 and self.diff_thr.value() == 1:
            self._load_recipe_into_form()
