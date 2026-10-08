"""AI Model Test Screen (spec 4.3): batch-validate the active model on a labelled folder."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QMarginsF, Qt
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ... import defects as taxonomy
from ...core.inspector import InspectionResult
from ...core.services import AppContext
from .. import theme
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from ..widgets.image_view import ImageView
from ..workers import Worker, start
from .base import QT_TRANSLATE_NOOP, Page, button, cell_item, fill_table, make_table

if TYPE_CHECKING:
    from ..main_window import MainWindow


class MetricTile(QLabel):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("tile")
        self.setMinimumHeight(theme.BANNER_H)
        self.set(None)

    def set(self, v: float | None) -> None:
        val = "—" if v is None else f"{v * 100:.1f}%"
        self.setText(
            f"<div style='font-size:{theme.FONT_PT}pt;color:{theme.TEXT_MUTED}'>{self.name}</div>"
            f"<div style='font-size:{theme.FONT_TILE_PT}pt;font-weight:700'>{val}</div>"
        )


class ModelTestPage(Page):
    title = QT_TRANSLATE_NOOP("Page", "AI Model Test")
    subtitle = QT_TRANSLATE_NOOP("Page", "Labels come from the sub-folder names: ok/ and ng/")
    roles = ("Engineer", "Admin")

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        self.folder: str | None = None
        self.rows: list[dict[str, Any]] = []
        self.metrics: dict[str, Any] = {}

        bar = QHBoxLayout()
        bar.addWidget(button(self.tr("Select Test Folder…"), slot=self.pick))
        self.btn_run = button(self.tr("Run Test"), "primary", self.run)
        bar.addWidget(self.btn_run)
        bar.addWidget(button(self.tr("Export CSV"), slot=self.export_csv))
        bar.addWidget(button(self.tr("Export Report"), slot=self.export_report))
        self.folder_label = QLabel(self.tr("No folder selected"))
        self.folder_label.setObjectName("muted")
        bar.addWidget(self.folder_label, 1)
        self.root.addLayout(bar)

        tiles = QGridLayout()
        self.tiles = {
            k: MetricTile(n)
            for k, n in (
                ("accuracy", self.tr("Accuracy")),
                ("precision", self.tr("Precision")),
                ("recall", self.tr("Recall")),
                ("false_call_rate", self.tr("False call rate")),
            )
        }
        for i, t in enumerate(self.tiles.values()):
            tiles.addWidget(t, 0, i)
        self.root.addLayout(tiles)
        self.confusion = QLabel("")
        self.confusion.setObjectName("muted")
        self.root.addWidget(self.confusion)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.root.addWidget(self.bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.headers = [
            self.tr("Image"),
            self.tr("Label"),
            self.tr("Verdict"),
            self.tr("AI score"),
            self.tr("Pass/Fail", "whether the verdict matches the label"),
        ]
        self.table = make_table(self.headers)
        self.table.itemSelectionChanged.connect(self._preview)
        self.empty = EmptyState(self.table)
        split.addWidget(self.table)
        preview = QWidget()
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(0, 0, 0, 0)
        self.preview_verdict = QLabel("—")  # the previewed board's verdict: colour, shape and word (REQ-INSP-002)
        self.preview_verdict.setStyleSheet(theme.verdict_style("INFO", big=False))
        self.view = ImageView(placeholder=self.tr("Select a row to preview"))
        self.busy = BusyOverlay(self.view, self.tr("Inspecting…"))
        pl.addWidget(self.preview_verdict)
        pl.addWidget(self.view, 1)
        split.addWidget(preview)
        split.setSizes([800, 800])
        self.root.addWidget(split, 1)

    def pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.tr("Validation folder (with ok/ and ng/ sub-folders)"))
        if d:
            self.folder = d
            self.folder_label.setText(d)

    def run(self) -> None:
        if (bm := self.checked_board_model()) is None:
            return
        folder = self.folder
        if not folder:
            self.pick()
            folder = self.folder
            if not folder:
                return
        if not self.ctx.active_model(bm):
            QMessageBox.information(
                self,
                self.tr("No AI model"),
                self.tr("No AI model yet: the results use the Golden board comparison only."),
            )
        self.btn_run.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)

        def progress(done: int, total: int) -> None:
            report((done, total))  # the worker's emit, bound below before the job starts

        w = Worker(self.ctx.batch_test, bm, folder, progress=progress)
        report = w.signals.progress.emit  # the job holds this emit, never the worker or its signals (#132)

        def on_progress(a: tuple[int, int]) -> None:
            self.bar.setMaximum(a[1])
            self.bar.setValue(a[0])

        def finished() -> None:
            self.btn_run.setEnabled(True)
            self.btn_run.setText(self.tr("Run Test Again"))
            self.bar.setVisible(False)

        w.signals.progress.connect(on_progress)
        w.signals.result.connect(self._show)
        w.signals.error.connect(self.error)
        w.signals.finished.connect(finished)
        start(w, self.ctx.jobs)

    def _show(self, out: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
        self.metrics, self.rows = out
        self.empty.hide()
        m = self.metrics
        for k, t in self.tiles.items():
            t.set(m[k])
        counts = self.tr(
            "{labelled} labelled of {images} images  ·  TP {tp}  FN {fn}  FP {fp}  TN {tn}  ·  WARN counts as NG"
        )
        self.confusion.setText(
            counts.format(labelled=m["labelled"], images=m["samples"], tp=m["TP"], fn=m["FN"], fp=m["FP"], tn=m["TN"])
        )
        rows = [
            [Path(r["image"]).name, r["gt"], theme.verdict_label(r["ai_result"]), r["score"], r["pass_fail"]]
            for r in self.rows
        ]
        colors = [theme.NG_COLOR if r["pass_fail"] == "FAIL" else None for r in self.rows]
        fill_table(self.table, rows, colors, [r["image"] for r in self.rows])

    def _preview(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or (bm := self.board_model) is None:
            return  # the rows come from a run, which needed a board model (#110: a switch after the run)
        path = cell_item(self.table, rows[0].row(), 0).toolTip()
        self.run_in_background(
            self.ctx.inspect_file, bm, path, save=False,
            on_result=lambda res: self._show_preview(path, res), busy=self.busy,
        )  # fmt: skip

    def _show_preview(self, path: str, res: InspectionResult) -> None:
        self.preview_verdict.setText(theme.verdict_label(res.verdict))
        self.preview_verdict.setStyleSheet(theme.verdict_style(res.verdict, big=False))
        self.view.set_image(res.image)
        for d in res.defects:
            sev = taxonomy.BY_NAME.get(d.type, taxonomy.ANOMALY).severity
            self.view.add_box(d.x, d.y, d.w, d.h, theme.SEVERITY_COLORS.get(sev, theme.NG_COLOR), f"{d.no} {d.type}")
        self.shell.last_inspected = (path, res, None)  # a preview is not recorded

    def on_show(self) -> None:
        bm = self.board_model
        if self.rows:
            self.empty.hide()
        elif not bm:
            self.empty.show_state(*self.no_board_model())
        elif not self.ctx.active_model(bm):
            heading = self.tr("No AI model for {board_model} yet").format(board_model=bm)
            self.empty.show_state(heading, *self.empty_step(self.tr("Train one on Training."), "Training"))
        else:
            what = self.tr("Select a folder with ok/ and ng/ sub-folders, then press Run Test.")
            heading = self.tr("No validation run for {board_model} yet").format(board_model=bm)
            self.empty.show_state(heading, what, self.tr("Select Test Folder…"), self.pick)

    def export_csv(self) -> None:
        if not self.rows:
            return
        f, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export CSV"), str(self.ctx.settings.exports_dir / "model_test.csv"), self.tr("CSV (*.csv)")
        )
        if f:
            self.ctx.export_csv(f, self.rows, "test results")

    def export_report(self) -> None:
        if not self.rows:
            return
        f, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export report"),
            str(self.ctx.settings.exports_dir / "model_test_report.pdf"),
            self.tr("PDF (*.pdf)"),
        )
        if not f:
            return
        doc = QTextDocument()
        doc.setHtml(self._report_html())
        w = QPdfWriter(f)
        page = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait, QMarginsF(15, 15, 15, 15)
        )
        w.setPageLayout(page)
        doc.print_(w)
        self.shell.status(self.tr("Report saved: {file}").format(file=f))

    def _report_html(self) -> str:
        """The validation report: every sentence through tr(), the markup and the numbers from the code."""
        m = self.metrics
        bm = self.board_model or ""  # the rows come from a run, which needs a board model
        run = self.rows[0] if self.rows else {}  # each row names the run and the AI model it tested (REQ-SET-017)
        title = self.tr("AI Model Validation Report")
        head = self.tr(
            "Board model: <b>{board_model}</b> · AI model: {version} · Date: {date}<br>Validation folder: {folder}"
            "<br>Validation run UUID: {run_uuid} · AI model UUID: {model_uuid}"
        )
        head = head.format(
            board_model=html.escape(bm),
            version=html.escape(run.get("model_version") or self.tr("none")),
            date=f"{datetime.now():%Y-%m-%d %H:%M}",
            folder=html.escape(self.folder or ""),
            run_uuid=run.get("run_uuid") or "—",
            model_uuid=run.get("model_uuid") or self.tr("none"),
        )
        tiles = "".join(f"<th>{t.name}</th>" for t in self.tiles.values())
        values = "".join(f"<td>{m[k]:.1%}</td>" for k in self.tiles)
        counts = self.tr("TP {tp} · FN {fn} · FP {fp} · TN {tn} (NG = positive class; WARN counted as NG)")
        counts = counts.format(tp=m["TP"], fn=m["FN"], fp=m["FP"], tn=m["TN"])
        headers = "".join(f"<th>{h}</th>" for h in self.headers)
        rows = "".join(
            f"<tr style='color:{theme.NG_COLOR if r['pass_fail'] == 'FAIL' else theme.PRINT_TEXT}'>"
            f"<td>{html.escape(Path(r['image']).name)}</td><td>{r['gt']}</td><td>{r['ai_result']}</td>"
            f"<td>{r['score']}</td><td>{r['pass_fail']}</td></tr>"
            for r in self.rows
        )
        return (
            f"<h2>{title}</h2><p>{head}</p>"
            f"<table border=1 cellpadding=4 cellspacing=0><tr>{tiles}</tr><tr>{values}</tr></table>"
            f"<p>{counts}</p>"
            f"<table border=1 cellpadding=3 cellspacing=0><tr>{headers}</tr>{rows}</table>"
        )
