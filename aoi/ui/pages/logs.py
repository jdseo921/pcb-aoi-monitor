"""Log & Export Screen (spec 4.4)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateEdit, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QSplitter

from ...core.services import AppContext
from ...times import to_local
from .. import theme
from ..widgets.empty_state import EmptyState
from ..widgets.image_view import ImageView
from .base import QT_TRANSLATE_NOOP, Page, button, cell_text, fill_table, make_table

if TYPE_CHECKING:
    from ..main_window import MainWindow


class LogsPage(Page):
    title = QT_TRANSLATE_NOOP("Page", "Logs & Export")

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        self.rows: list[dict[str, Any]] = []
        f = QHBoxLayout()
        self.d_from = QDateEdit(QDate.currentDate().addDays(-7))
        self.d_to = QDateEdit(QDate.currentDate())
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")  # ISO dates everywhere (REQ-SET-017), not the locale's short form
        self.model = QComboBox()
        self.operator = QComboBox()
        self.archived = QCheckBox(self.tr("Include archived"))
        fields = (
            (self.tr("From"), self.d_from),
            (self.tr("To"), self.d_to),
            (self.tr("Board model"), self.model),
            (self.tr("Operator"), self.operator),
        )
        for label, w in fields:
            f.addWidget(QLabel(label))
            f.addWidget(w)
        f.addWidget(self.archived)
        f.addWidget(button(self.tr("Filter"), "primary", self.refresh))
        f.addStretch(1)
        self.root.addLayout(f)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.table = make_table(
            [
                self.tr("ID"),
                self.tr("Time"),
                self.tr("Board model"),
                self.tr("Result"),
                self.tr("Defects"),
                self.tr("Score"),
                self.tr("Operator"),
                self.tr("Image"),
            ]
        )
        self.table.verticalHeader().setDefaultSectionSize(theme.TARGET_H)  # a history row is an operator target
        self.table.itemSelectionChanged.connect(self._preview)
        self.empty = EmptyState(self.table)
        split.addWidget(self.table)
        self.view = ImageView(placeholder=self.tr("Select a row to see its overlay"))
        split.addWidget(self.view)
        split.setSizes([1000, 600])
        self.root.addWidget(split, 1)

        b = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        b.addWidget(self.summary, 1)
        self.btn_csv = button(self.tr("Export CSV"), slot=self.export_csv)
        self.btn_img = button(self.tr("Export Image Overlays"), slot=self.export_overlays)
        archive = self.tr("Archive older than {days} days").format(days=ctx.settings.log_retention_days)
        self.btn_arch = button(archive, slot=self.archive)
        for x in (self.btn_csv, self.btn_img, self.btn_arch):
            b.addWidget(x)
        self.root.addLayout(b)

    def refresh(self) -> None:
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
                    theme.verdict_label(r["result"]),
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
        self.summary.setText(
            self.tr("{count} inspections · {ng} NG · yield {rate:.1%}").format(count=n, ng=ng, rate=(n - ng) / n)
            if n
            else self.tr("No records")
        )
        if n:
            self.empty.hide()
        elif self.ctx.inspections(include_archived=True):
            self.empty.show_state(
                self.tr("No records match"),
                self.tr("Widen the dates or the filters."),
                self.tr("Reset Filters"),
                self.reset_filters,
            )
        else:
            step = self.empty_step(self.tr("Run boards on Inspection."), "Inspection")
            self.empty.show_state(self.tr("No inspections yet"), *step)

    def reset_filters(self) -> None:
        self.d_from.setDate(QDate.currentDate().addDays(-7))
        self.d_to.setDate(QDate.currentDate())
        self.model.setCurrentIndex(0)
        self.operator.setCurrentIndex(0)
        self.archived.setChecked(False)
        self.refresh()

    def _preview(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            iid = int(cell_text(self.table, rows[0].row(), 0))
            r = next(x for x in self.rows if x["id"] == iid)
            if r["overlay_path"] and Path(r["overlay_path"]).exists():
                self.view.set_image(self.ctx.load_image(r["overlay_path"]))

    def _confirm(self, question: str) -> bool:
        return QMessageBox.question(self, self.tr("Confirm export"), question) == QMessageBox.StandardButton.Yes

    def export_csv(self) -> None:
        if not self.rows or not self._confirm(
            self.tr("Export CSV for {count} record(s)?").format(count=len(self.rows))
        ):
            return
        f, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export CSV"), str(self.ctx.settings.exports_dir / "inspections.csv"), self.tr("CSV (*.csv)")
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
        self.shell.status(self.tr("Exported {count} rows to {file}").format(count=len(out), file=f))

    def export_overlays(self) -> None:
        question = self.tr("Export overlay images for {count} record(s)?").format(count=len(self.rows))
        if not self.rows or not self._confirm(question):
            return
        d = QFileDialog.getExistingDirectory(self, self.tr("Export overlays to"), str(self.ctx.settings.exports_dir))
        if not d:
            return
        n = self.ctx.export_overlays(self.rows, d)
        self.shell.status(self.tr("Copied {count} overlay image(s) to {folder}").format(count=n, folder=d))

    def archive(self) -> None:
        n = self.ctx.archive_old()
        self.shell.status(self.tr("Archived {count} record(s)").format(count=n))
        self.refresh()

    def on_show(self) -> None:
        admin_or_eng = self.ctx.role in ("Engineer", "Admin")
        for b in (self.btn_csv, self.btn_img, self.btn_arch):
            b.setEnabled(admin_or_eng)  # spec 8: Admin exports logs (Engineer allowed for PoC)
        for combo, values in (
            (self.model, self.ctx.board_models()),
            (self.operator, [u["name"] for u in self.ctx.users()]),
        ):
            cur = combo.currentData()
            combo.clear()
            combo.addItem(self.tr("All"), None)
            for v in values:
                combo.addItem(v, v)
            i = combo.findData(cur)
            combo.setCurrentIndex(max(0, i))
        self.refresh()
