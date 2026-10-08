"""AI Model Test Screen (spec 4.3): batch-validate the active model on a labelled folder."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QMarginsF, Qt
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QSplitter

from ... import defects as taxonomy
from ..widgets.image_view import ImageView
from ..workers import Worker, start
from .base import Page, button, fill_table, make_table


class MetricTile(QLabel):
    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(90)
        self.setStyleSheet("background:#26323f; border-radius:8px; padding:8px;")
        self.set(None)

    def set(self, v: float | None):
        val = "—" if v is None else f"{v * 100:.1f}%"
        self.setText(
            f"<div style='font-size:12pt;color:#9fb0c0'>{self.name}</div>"
            f"<div style='font-size:26pt;font-weight:700'>{val}</div>"
        )


class ModelTestPage(Page):
    title = "AI Model Test"
    subtitle = "Ground truth from sub-folder names: ok/ and ng/"
    roles = ("Engineer", "Admin")

    def __init__(self, ctx, shell):
        super().__init__(ctx, shell)
        self.folder: str | None = None
        self.rows: list[dict] = []
        self.metrics: dict = {}

        bar = QHBoxLayout()
        bar.addWidget(button("Select Test Folder…", slot=self.pick))
        self.btn_run = button("Run Test", "primary", self.run)
        bar.addWidget(self.btn_run)
        bar.addWidget(button("Export CSV", slot=self.export_csv))
        bar.addWidget(button("Export Report", slot=self.export_report))
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setObjectName("muted")
        bar.addWidget(self.folder_label, 1)
        self.root.addLayout(bar)

        tiles = QGridLayout()
        self.tiles = {
            k: MetricTile(n)
            for k, n in (
                ("accuracy", "Accuracy"),
                ("precision", "Precision"),
                ("recall", "Recall"),
                ("false_call_rate", "False Call Rate"),
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

        split = QSplitter(Qt.Horizontal)
        self.table = make_table(["Image", "GT", "AI Result", "Score", "Pass/Fail"])
        self.table.itemSelectionChanged.connect(self._preview)
        split.addWidget(self.table)
        self.view = ImageView(placeholder="Select a row to preview")
        split.addWidget(self.view)
        split.setSizes([800, 800])
        self.root.addWidget(split, 1)

    def pick(self):
        d = QFileDialog.getExistingDirectory(self, "Test folder (with ok/ and ng/ sub-folders)")
        if d:
            self.folder = d
            self.folder_label.setText(d)

    def run(self):
        if not self.need_board_model():
            return
        if not self.folder:
            return self.pick() or (self.folder and self.run())
        if not self.ctx.active_model(self.board_model):
            QMessageBox.information(self, "No model", "No trained model yet: results use golden comparison only.")
        self.btn_run.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        w = Worker(
            self.ctx.batch_test, self.board_model, self.folder, progress=lambda i, n: w.signals.progress.emit((i, n))
        )
        w.signals.progress.connect(lambda a: (self.bar.setMaximum(a[1]), self.bar.setValue(a[0])))
        w.signals.result.connect(self._show)
        w.signals.error.connect(self.error)
        w.signals.finished.connect(
            lambda: (self.btn_run.setEnabled(True), self.btn_run.setText("Run Test Again"), self.bar.setVisible(False))
        )
        start(w, self.ctx.jobs)

    def _show(self, out):
        self.metrics, self.rows = out
        m = self.metrics
        for k, t in self.tiles.items():
            t.set(m[k])
        self.confusion.setText(
            f"{m['labelled']} labelled of {m['samples']} images  ·  TP {m['TP']}  FN {m['FN']}  "
            f"FP {m['FP']}  TN {m['TN']}  ·  WARN counts as flagged (NG)"
        )
        fill_table(
            self.table,
            [[Path(r["image"]).name, r["gt"], r["ai_result"], r["score"], r["pass_fail"]] for r in self.rows],
            ["#c62828" if r["pass_fail"] == "FAIL" else None for r in self.rows],
        )
        for i, r in enumerate(self.rows):
            self.table.item(i, 0).setToolTip(r["image"])

    def _preview(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        path = self.table.item(rows[0].row(), 0).toolTip()
        res = self.ctx.inspect_file(self.board_model, path, save=False)
        self.view.set_image(res.image)
        for d in res.defects:
            sev = taxonomy.BY_NAME.get(d.type, taxonomy.ANOMALY).severity
            self.view.add_box(d.x, d.y, d.w, d.h, taxonomy.SEVERITY_COLOR.get(sev, "#e53935"), f"{d.no} {d.type}")
        self.shell.last_inspected = (path, res)

    def export_csv(self):
        if not self.rows:
            return
        f, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", str(self.ctx.settings.exports_dir / "model_test.csv"), "CSV (*.csv)"
        )
        if f:
            self.ctx.export_csv(f, self.rows, "test results")

    def export_report(self):
        if not self.rows:
            return
        f, _ = QFileDialog.getSaveFileName(
            self, "Export report", str(self.ctx.settings.exports_dir / "model_test_report.pdf"), "PDF (*.pdf)"
        )
        if not f:
            return
        m = self.metrics
        active = self.ctx.active_model(self.board_model)
        rows = "".join(
            f"<tr style='color:{'#c62828' if r['pass_fail'] == 'FAIL' else '#000'}'>"
            f"<td>{html.escape(Path(r['image']).name)}</td><td>{r['gt']}</td><td>{r['ai_result']}</td><td>{r['score']}</td><td>{r['pass_fail']}</td></tr>"
            for r in self.rows
        )
        doc = QTextDocument()
        doc.setHtml(f"""<h2>AI Model Validation Report</h2>
            <p>Board model: <b>{html.escape(self.board_model)}</b> · Model: {active["version"] if active else "none"}
            · Date: {datetime.now():%Y-%m-%d %H:%M}<br>Test folder: {html.escape(self.folder or "")}</p>
            <table border=1 cellpadding=4 cellspacing=0>
            <tr><th>Accuracy</th><th>Precision</th><th>Recall</th><th>False Call Rate</th></tr>
            <tr><td>{m["accuracy"]:.1%}</td><td>{m["precision"]:.1%}</td><td>{m["recall"]:.1%}</td>
            <td>{m["false_call_rate"]:.1%}</td></tr></table>
            <p>TP {m["TP"]} · FN {m["FN"]} · FP {m["FP"]} · TN {m["TN"]} (NG = positive class; WARN counted as NG)</p>
            <table border=1 cellpadding=3 cellspacing=0><tr><th>Image</th><th>GT</th><th>AI Result</th>
            <th>Score</th><th>Pass/Fail</th></tr>{rows}</table>""")
        w = QPdfWriter(f)
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(15, 15, 15, 15)))
        doc.print_(w)
        self.shell.status(f"Report saved: {f}")
