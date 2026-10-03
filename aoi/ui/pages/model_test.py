"""AI Model Test Screen (spec 4.3): batch-validate the active model on a labelled folder."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QBuffer, QIODevice, QMarginsF, Qt
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
from ...errors import AoiError
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
        self.folder: str | None = None  # the folder picked, to run next
        self.rows: list[dict[str, Any]] = []
        self.metrics: dict[str, Any] = {}
        self.run_folder = ""  # the folder the rows and metrics came from, which the report names (#174)
        self.run_board_model: str | None = None  # and the board model they were run for, while shown (#180)

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
            self.btn_run.setText(self.tr("Run Test Again") if self.rows else self.tr("Run Test"))
            self.bar.setVisible(False)

        w.signals.progress.connect(on_progress)
        w.signals.result.connect(lambda out: self._show(out, folder, bm))  # folder and board model go with them
        w.signals.error.connect(self.error)
        w.signals.finished.connect(finished)
        start(w, self.ctx.jobs)

    def _show(self, out: tuple[dict[str, Any], list[dict[str, Any]]], folder: str, board_model: str) -> None:
        if board_model != self.board_model:  # the header changed while it ran: its rows are not shown under the
            status = self.tr(  # new board model's name (#180); the run is stored, as every run
                "The AI model test of {board_model} is stored; its results are not shown here, since the board model"
                " changed while it ran."
            )
            self.shell.status(status.format(board_model=board_model))
            return
        self.metrics, self.rows = out
        self.run_folder, self.run_board_model = folder, board_model
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
        if not rows or (bm := self.run_board_model) is None:
            return  # a row is judged under the board model of its run (#180), never the header's after a switch
        path = cell_item(self.table, rows[0].row(), 0).toolTip()
        self._clear_preview()  # the row before never stands beside this one, even when it cannot be inspected (#182)
        self.run_in_background(
            self.ctx.inspect_file, bm, path, save=False,
            on_result=lambda res: self._show_preview(path, res, bm), busy=self.busy,
            on_error=lambda e: self.not_inspected(self.preview_verdict, Path(path).name, e, big=False),
        )  # fmt: skip

    def _clear_preview(self) -> None:
        self.preview_verdict.setText("—")
        self.preview_verdict.setStyleSheet(theme.verdict_style("INFO", big=False))
        self.view.set_image(None)

    def _show_preview(self, path: str, res: InspectionResult, board_model: str) -> None:
        if board_model != self.run_board_model or board_model != self.board_model:
            return  # the run went with a board model change while this row was inspected (#180)
        self.preview_verdict.setText(theme.verdict_label(res.verdict))
        self.preview_verdict.setStyleSheet(theme.verdict_style(res.verdict, big=False))
        self.view.set_image(res.image)
        for d in res.defects:
            sev = taxonomy.BY_NAME.get(d.type, taxonomy.ANOMALY).severity
            self.view.add_box(d.x, d.y, d.w, d.h, theme.SEVERITY_COLORS.get(sev, theme.NG_COLOR), f"{d.no} {d.type}")
        self.shell.last_inspected = (path, res, None)  # a preview is not recorded

    def on_board_model_changed(self, name: str | None) -> None:
        if self.run_board_model not in (None, name):  # another board model's run is not shown, previewed or reported
            self._clear_run()  # under this one's name (#180)

    def _clear_run(self) -> None:
        self.rows, self.metrics, self.run_folder, self.run_board_model = [], {}, "", None
        for t in self.tiles.values():
            t.set(None)
        self.confusion.clear()
        fill_table(self.table, [])
        self._clear_preview()
        self.btn_run.setText(self.tr("Run Test"))

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
        if not f or self.run_board_model is None:
            return
        doc = QTextDocument()
        doc.setHtml(self._report_html())
        buf = QBuffer()  # rendered in memory, then written whole or not at all by the service layer (#180)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        w = QPdfWriter(buf)
        page = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait, QMarginsF(15, 15, 15, 15)
        )
        w.setPageLayout(page)
        doc.print_(w)
        del w
        run = self.rows[0]
        try:
            self.ctx.export_report(
                f, bytes(buf.data().data()), self.run_board_model, run.get("run_uuid"), run.get("model_version")
            )
        except AoiError as e:  # AOI-LOG-002 (not written) or AOI-USR-001 (role): no "Report saved"
            self.error(e)
            return
        self.shell.status(self.tr("Report saved: {file}").format(file=f))

    def _report_html(self) -> str:
        """The validation report: every sentence through tr(), the markup and the numbers from the code."""
        m = self.metrics
        bm = self.run_board_model or ""  # the board model the run was for (#180)
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
            folder=html.escape(self.run_folder),
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
