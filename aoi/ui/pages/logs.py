"""Log & Export Screen (spec 4.4)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateEdit, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QSplitter

from ...core.imaging import load_image
from ...times import to_local
from .. import theme
from ..widgets.image_view import ImageView
from .base import Page, button, fill_table, make_table


class LogsPage(Page):
    title = "Logs & Export"

    def __init__(self, ctx, shell):
        super().__init__(ctx, shell)
        self.rows: list[dict] = []
        f = QHBoxLayout()
        self.d_from = QDateEdit(QDate.currentDate().addDays(-7))
        self.d_from.setCalendarPopup(True)
        self.d_to = QDateEdit(QDate.currentDate())
        self.d_to.setCalendarPopup(True)
        self.model = QComboBox()
        self.operator = QComboBox()
        self.archived = QCheckBox("Include archived")
        for label, w in (("From", self.d_from), ("To", self.d_to), ("Model", self.model), ("Operator", self.operator)):
            f.addWidget(QLabel(label))
            f.addWidget(w)
        f.addWidget(self.archived)
        f.addWidget(button("Filter", "primary", self.refresh))
        f.addStretch(1)
        self.root.addLayout(f)

        split = QSplitter(Qt.Horizontal)
        self.table = make_table(["ID", "Time", "Model", "Result", "Defects", "Score", "Operator", "Image"])
        self.table.itemSelectionChanged.connect(self._preview)
        split.addWidget(self.table)
        self.view = ImageView(placeholder="Select a log row to see its overlay")
        split.addWidget(self.view)
        split.setSizes([1000, 600])
        self.root.addWidget(split, 1)

        b = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        b.addWidget(self.summary, 1)
        self.btn_csv = button("Export CSV", slot=self.export_csv)
        self.btn_img = button("Export Image Overlays", slot=self.export_overlays)
        self.btn_arch = button(f"Archive > {ctx.settings.log_retention_days} days", slot=self.archive)
        for x in (self.btn_csv, self.btn_img, self.btn_arch):
            b.addWidget(x)
        self.root.addLayout(b)

    def refresh(self):
        self.rows = self.ctx.inspections(
            self.d_from.date().toString("yyyy-MM-dd"),
            self.d_to.date().toString("yyyy-MM-dd"),
            self.model.currentData(),
            self.operator.currentData(),
            self.archived.isChecked(),
        )
        fill_table(
            self.table,
            [
                [
                    r["id"],
                    to_local(r["time"]),
                    r["board_model"],
                    r["result"],
                    r["defect_count"],
                    r["score"] or 0.0,
                    r["operator"],
                    Path(r["image_path"]).name,
                ]
                for r in self.rows
            ],
            [theme.VERDICT_COLORS[r["result"]] if r["result"] != "OK" else None for r in self.rows],
        )
        n = len(self.rows)
        ng = sum(r["result"] == "NG" for r in self.rows)
        self.summary.setText(f"{n} inspections · {ng} NG · yield {(n - ng) / n:.1%}" if n else "No records")

    def _preview(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            iid = int(self.table.item(rows[0].row(), 0).text())
            r = next(x for x in self.rows if x["id"] == iid)
            if r["overlay_path"] and Path(r["overlay_path"]).exists():
                self.view.set_image(load_image(r["overlay_path"]))

    def _confirm(self, what: str) -> bool:
        return (
            QMessageBox.question(self, "Confirm export", f"Export {what} for {len(self.rows)} record(s)?")
            == QMessageBox.Yes
        )

    def export_csv(self):
        if not self.rows or not self._confirm("CSV"):
            return
        f, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", str(self.ctx.settings.exports_dir / "inspections.csv"), "CSV (*.csv)"
        )
        if not f:
            return
        out = []
        for r in self.rows:
            ds = self.ctx.defects_for(r["id"])
            out.append(
                {
                    "id": r["id"],
                    "time": r["time"],
                    "board_model": r["board_model"],
                    "model_version": r["model_version"],
                    "recipe_rev": r["recipe_rev"],
                    "result": r["result"],
                    "score": r["score"],
                    "defects": len(ds),
                    "defect_types": ";".join(sorted({d["type"] for d in ds})),
                    "operator": r["operator"],
                    "image": r["image_path"],
                    "overlay": r["overlay_path"],
                }
            )
        self.ctx.export_csv(f, out)
        self.shell.status(f"Exported {len(out)} rows to {f}")

    def export_overlays(self):
        if not self.rows or not self._confirm("overlay images"):
            return
        d = QFileDialog.getExistingDirectory(self, "Export overlays to", str(self.ctx.settings.exports_dir))
        if not d:
            return
        n = self.ctx.export_overlays(self.rows, d)
        self.shell.status(f"Copied {n} overlay image(s) to {d}")

    def archive(self):
        n = self.ctx.archive_old()
        self.shell.status(f"Archived {n} record(s)")
        self.refresh()

    def on_show(self):
        admin_or_eng = self.ctx.role in ("Engineer", "Admin")
        for b in (self.btn_csv, self.btn_img, self.btn_arch):
            b.setEnabled(admin_or_eng)  # spec 8: Admin exports logs (Engineer allowed for PoC)
        for combo, values in (
            (self.model, self.ctx.board_models()),
            (self.operator, [u["name"] for u in self.ctx.users()]),
        ):
            cur = combo.currentData()
            combo.clear()
            combo.addItem("All", None)
            for v in values:
                combo.addItem(v, v)
            i = combo.findData(cur)
            combo.setCurrentIndex(max(0, i))
        self.refresh()
