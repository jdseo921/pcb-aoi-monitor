"""Training › Datasets' Working set panel, its Freeze sheet and the Versions table (REQ-TRN-005, the screen half;
Datasets stage 4 of 4): the datasets sketch's working set, view by view with its labels checked, the customer whose
dataset store holds the board model and the allowed uses; Freeze Dataset… shows the Freeze sheet in place of the
labeller agreement, the version it would make and a line for each thing a freeze needs, ✓ or ✗ with the fix, and
Freeze freezes the version on the pool, with progress and Cancel. The Versions table lists the board model's frozen
versions; Split and Lock Validation Set… shows its sheet in the same place, Verify Manifest re-hashes the version
picked on the pool, and Export Manifest… writes its files as CSV. Nothing here reads or writes the database itself."""

from __future__ import annotations

import json
import math
import secrets
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIntValidator, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ...core.datasets import ALLOWED_USES, VALIDATION_NG, VALIDATION_OK, mismatch, stratum
from ...errors import AoiError
from ...hal import VIEWS
from ...times import to_local
from ..widgets.busy import BusyOverlay
from ..widgets.empty_state import EmptyState
from .base import QT_TRANSLATE_NOOP, action_button, button, fill_table, make_table

if TYPE_CHECKING:
    from .training import TrainingPage

USES = {  # the sketch's three, own ticked: placeholders until Jay names the uses a customer's contract allows (Q38)
    "own": QT_TRANSLATE_NOOP("WorkingSetPanel", "Their own AI models"),
    "shared": QT_TRANSLATE_NOOP("WorkingSetPanel", "Shared improvement"),
    "demos": QT_TRANSLATE_NOOP("WorkingSetPanel", "Demos"),
}
REVISION_LENGTH = 16  # a board revision is 1 to 16 letters and digits (aoi.core.datasets.REVISION)


class WorkingSetPanel(QGroupBox):
    """The board model's labels view by view, its customer and the uses a freeze allows, and Freeze Dataset…."""

    def __init__(self, page: TrainingPage) -> None:
        super().__init__()
        self.setTitle(self.tr("Working set"))
        self.page, self.ctx = page, page.ctx
        self.board_model: str | None = None
        self.views: list[str] = []  # the views with an image labelled OK or NG, as Top, Side, Bottom
        form = QFormLayout(self)
        self.counts = QLabel()  # a line per view: its labels and the checks a freeze needs
        self.counts.setWordWrap(True)
        form.addRow(self.counts)
        self.btn_samples = button(self.tr("Open Samples ›"), slot=lambda: self.page.tabs.setCurrentIndex(0))
        form.addRow(self.btn_samples)
        top = QHBoxLayout()
        self.customer = QLabel()  # the customer whose dataset store holds the board model: the freeze names it
        top.addWidget(self.customer, 1)
        self.act_freeze = page.dataset_action(self.tr("Freeze Dataset…"), "Ctrl+F", self.open_sheet)
        self.btn_freeze = action_button(self.act_freeze, show_key=False)  # plain: Start Training is the blue one
        top.addWidget(self.btn_freeze)
        form.addRow(self.tr("Customer"), top)
        uses = QHBoxLayout()
        self.uses: dict[str, QCheckBox] = {}
        for use in ALLOWED_USES:
            box = self.uses[use] = QCheckBox(self.tr(USES[use]))
            box.setChecked(use == "own")
            box.toggled.connect(self._sync)
            uses.addWidget(box)
        uses.addStretch(1)
        form.addRow(self.tr("Allowed uses"), uses)
        self.sheet = FreezeSheet(self)
        self.busy = BusyOverlay(self.sheet, self.tr("Freezing the dataset version…"))

    def show_board_model(self, board_model: str | None, samples: list[dict[str, Any]]) -> None:
        """Each view's labels and checks, the store's customer; a sheet of another board model closes."""
        if board_model != self.board_model:
            self.sheet.leave()
        self.board_model = board_model
        n = Counter((s["side"], s["label"]) for s in samples)
        self.views = [v for v in VIEWS if n[v, "OK"] + n[v, "NG"]]
        lines = []
        for v in self.views:
            st = self.ctx.label_check_status(board_model or "", v)
            line = self.tr(
                "{view}: {ok} OK · {ng} NG · {unsure} UNSURE · {ng_checked} of {ng} NG checked · {ok_checked} of"
                " {need} OK checked (10 %)"
            ).format(
                view=v, ok=st["ok"], ng=st["ng"], unsure=n[v, "UNSURE"], ng_checked=st["ng"] - len(st["ng_unchecked"]),
                ok_checked=min(len(st["ok_checked"]), st["ok_needed"]), need=st["ok_needed"],
            )  # fmt: skip
            lines.append(self.tr("{line} ✓").format(line=line) if st["ready"] else line)
        if board_model is not None and not self.views:
            lines = [self.tr("No samples labelled OK or NG yet. Add OK boards on the Samples tab.")]
        self.counts.setText("\n".join(lines))
        self.btn_samples.setVisible(board_model is not None and not self.views)
        store = self.ctx.store_of(board_model) if board_model else None
        if store is None:
            self.customer.setText(self.tr("in no customer's dataset store yet"))
        else:
            self.customer.setText(store["customer"])
        if self.sheet.isVisible():
            self.sheet.read_gate()
        self._sync()

    def picked_uses(self) -> list[str]:
        return [use for use, box in self.uses.items() if box.isChecked()]

    def _sync(self) -> None:
        """Freeze Dataset… needs a view with an image labelled OK or NG, and no job of the page's running."""
        idle = self.page.idle()
        self.act_freeze.setEnabled(bool(self.views) and idle and not self.page.sheet_open())
        self.btn_freeze.setToolTip("" if self.views else self.tr("Label images OK or NG on the Samples tab first"))
        for box in self.uses.values():
            box.setEnabled(idle)
        self.sheet.sync()

    def sync(self) -> None:
        self._sync()

    def open_sheet(self) -> None:
        if self.board_model is None or not self.views or not self.page.idle():
            return
        self.sheet.open_for(self.board_model, self.views)


class FreezeSheet(QGroupBox):
    """The Freeze sheet: the view and board revision, the version a freeze makes, what it needs, Cancel and Freeze."""

    def __init__(self, panel: WorkingSetPanel) -> None:
        super().__init__()
        self.setTitle(self.tr("Freeze dataset"))
        self.panel, self.page, self.ctx = panel, panel.page, panel.ctx
        self.board_model: str | None = None
        self.gate: dict[str, Any] | None = None
        self.running = False  # a freeze of this sheet's runs on the pool
        self.left = False  # a sign-in or another board model came while it ran: the sheet closes as it ends
        esc = QAction(self, shortcut=QKeySequence(Qt.Key.Key_Escape))
        esc.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.triggered.connect(self.cancel)
        self.addAction(esc)
        lay = QVBoxLayout(self)
        fields = QHBoxLayout()
        fields.addWidget(QLabel(self.tr("View")))
        self.view_box = QComboBox()
        self.view_box.currentIndexChanged.connect(self.read_gate)
        fields.addWidget(self.view_box)
        fields.addWidget(QLabel(self.tr("Board revision")))
        self.revision = QLineEdit()
        self.revision.setMaxLength(REVISION_LENGTH)
        self.revision.textChanged.connect(self.read_gate)
        self.revision.returnPressed.connect(self.freeze)
        fields.addWidget(self.revision, 1)
        lay.addLayout(fields)
        self.name_line = QLabel()
        self.name_line.setWordWrap(True)
        lay.addWidget(self.name_line)
        self.lines = [QLabel() for _ in range(4)]  # NG checked, OK checked, customer, agreement check
        for line in self.lines:
            line.setWordWrap(True)
            lay.addWidget(line)
        self.files_line = QLabel()
        self.files_line.setObjectName("muted")
        self.files_line.setWordWrap(True)
        lay.addWidget(self.files_line)
        self.refused = QLabel()  # the coded refusal no line above names: a version of that name exists, say
        self.refused.setWordWrap(True)
        lay.addWidget(self.refused)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = button(self.tr("Cancel"), slot=self.cancel)
        self.btn_now = button(self.tr("Freeze"), slot=self.freeze)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_now)
        lay.addLayout(row)
        lay.addStretch(1)
        self.hide()

    def open_for(self, board_model: str, views: list[str]) -> None:
        """The sheet in place of the panels under the working set, for the view picked before while it has images,
        the board revision the board model's newest version names, if any."""
        self.board_model = board_model
        kept = self.view_box.currentText()
        self.view_box.blockSignals(True)
        self.view_box.clear()
        self.view_box.addItems(views)
        self.view_box.setCurrentIndex(max(self.view_box.findText(kept), 0))
        self.view_box.blockSignals(False)
        versions = self.ctx.datasets(board_model)
        self.revision.blockSignals(True)
        self.revision.setText(versions[0]["revision"] if versions else "")
        self.revision.blockSignals(False)
        self.page.show_sheet(self)  # the agreement hidden first, so the page keeps its height
        self.read_gate()
        self.revision.setFocus()
        self.panel.sync()

    def read_gate(self) -> None:
        """What a freeze of the view and revision needs now, as AppContext.freeze_gate reads it, line by line."""
        if self.board_model is None or not self.view_box.count():
            return
        view, revision = self.view_box.currentText(), self.revision.text().strip()
        g = self.gate = self.ctx.freeze_gate(self.board_model, view, revision)
        if g["name"] is None:
            self.name_line.setText(self.tr("Name: type the board revision, 1 to 16 letters and digits, such as R3"))
        else:
            self.name_line.setText(self.tr("Name {name}").format(name=g["name"]))
        st, check, store = g["labels"], g["check"], g["store"]
        unchecked, n = len(st["ng_unchecked"]), {"n": len(st["ok_checked"]), "need": st["ok_needed"], "ok": st["ok"]}
        customer = store["customer"] if store is not None and not store["shredded_at"] else None
        ok_line = self.tr("{n} of {need} OK labels checked (10 % of {ok})")
        said = [
            (not unchecked, self.tr("Every NG label checked by a second user"),
             self.tr("{n} of {ng} NG labels not checked: check them on the Samples tab").format(
                 n=unchecked, ng=st["ng"])),
            (n["n"] >= n["need"], ok_line.format(**n),
             self.tr("{line}: draw and check them on the Samples tab").format(line=ok_line.format(**n))),
            (customer is not None,
             self.tr("Customer {customer}, whose dataset store holds it").format(customer=customer),
             self.tr("In no customer's dataset store: an Admin moves it in on Settings")),
            (check is not None and check["agreed"], self.tr("Agreement check reached its targets"),
             self.tr("No agreement check of this view reached its targets: run one under Labeller agreement")),
        ]  # fmt: skip
        for line, (ok, yes, no) in zip(self.lines, said, strict=True):
            line.setText(self.tr("✓ {line}").format(line=yes) if ok else self.tr("✗ {line}").format(line=no))
        files = self.tr("{files} files · a SHA-256 manifest is written · the version never changes afterwards")
        self.files_line.setText(files.format(files=g["files"]))
        other = g["refused"] is not None and g["name"] is not None and all(ok for ok, _, _ in said)
        self.refused.setText(self.page.coded_text(g["refused"]) if other else "")
        self.refused.setVisible(other)
        self.sync()

    def sync(self) -> None:
        """Freeze needs every line ✓, no refusal, an allowed use ticked and no job of the page's running."""
        uses = self.panel.picked_uses()
        ready = self.gate is not None and self.gate["refused"] is None and bool(uses)
        self.btn_now.setEnabled(ready and self.page.idle())
        self.btn_now.setToolTip("" if uses else self.tr("Tick at least one allowed use"))
        self.revision.setEnabled(self.page.idle())
        self.view_box.setEnabled(self.page.idle())

    def cancel(self) -> None:
        """Cancel or Esc: the panels back; a freeze that runs is stopped instead, nothing written, the sheet kept."""
        if self.running:
            self.panel.busy.cancel_button.click()  # the job asked to stop, as the busy overlay's Cancel does
            return
        self.close_sheet()

    def leave(self) -> None:
        """A sign-in or another board model: the sheet closes, or, while its freeze runs, once that freeze ends."""
        if self.running:
            self.left = True
        else:
            self.close_sheet()

    def close_sheet(self) -> None:
        self.left = False
        if not self.isVisible():
            return
        self.hide()
        self.gate = None
        self.page.show_sheet(None)
        self.panel.sync()

    def freeze(self) -> None:
        """Freeze the view as the gate named it, for the store's customer and the uses ticked, on the pool."""
        g, bm = self.gate, self.board_model
        if g is None or bm is None or g["store"] is None or not self.btn_now.isEnabled():
            return
        view, revision, name = self.view_box.currentText(), self.revision.text().strip(), g["name"]

        def done(version: dict[str, Any] | None) -> None:
            self.running = False
            self.close_sheet()
            self.page.refresh()
            if version is not None:
                self.page.versions.show_board_model(bm, version["uuid"])  # picked, as the newest
                said = self.tr("Froze {name}: {files} files and their manifest")
                self.page.shell.status(said.format(name=version["name"], files=g["files"]))

        def stopped(version: dict[str, Any] | None) -> None:  # a Cancel after the last file hashed comes too late
            if version is not None or self.left:
                done(version)
            else:
                self.running = False
                self.read_gate()
            if version is None:
                self.page.shell.status(self.tr("Freeze of {name} cancelled: nothing was written").format(name=name))

        def failed(_e: BaseException) -> None:
            self.running = False
            self.page.refresh()
            if self.left:
                self.close_sheet()
            elif self.isVisible():
                self.read_gate()

        self.running = True
        self.page.run_in_background(
            self.ctx.freeze_dataset, bm, view, revision, g["store"]["customer"], self.panel.picked_uses(),
            with_progress=True, on_result=done, on_cancel=stopped, on_error=failed, busy=self.panel.busy,
        )  # fmt: skip
        self.sync()


USES_SHORT = {  # the Versions table's Uses cell, as the sketch writes it
    "own": QT_TRANSLATE_NOOP("VersionsPanel", "own"),
    "shared": QT_TRANSLATE_NOOP("VersionsPanel", "shared"),
    "demos": QT_TRANSLATE_NOOP("VersionsPanel", "demos"),
}
FOUND_SHOWN = 5  # the changed or missing files named under the table; the rest are counted
MANIFEST_COLUMNS = ["path", "sha256", "label", "defect_type", "boxes", "labelled_by", "checked_by", "part"]
SEED_TOP = 2**31 - 1  # a split's seed is 0 to this, as AppContext.lock_validation_set draws one


class VersionsPanel(QGroupBox):
    """The board model's frozen versions, newest first: what each holds, its locked validation set and what Verify
    Manifest found this session; Verify Manifest re-hashes the one picked on the pool, with progress and Cancel."""

    def __init__(self, page: TrainingPage) -> None:
        super().__init__()
        self.setTitle(self.tr("Versions"))
        self.page, self.ctx = page, page.ctx
        self.board_model: str | None = None
        self.rows: list[dict[str, Any]] = []
        self.counts: dict[str, dict[str, int]] = {}  # dataset_counts, by version UUID
        self.verified: dict[str, dict[str, Any]] = {}  # what Verify Manifest found, by version UUID, this session
        lay = QVBoxLayout(self)
        heads = [self.tr("Version"), self.tr("Frozen"), self.tr("By"), self.tr("OK"), self.tr("NG")]
        heads += [self.tr("Validation OK / NG"), self.tr("Customer"), self.tr("Uses"), self.tr("Manifest")]
        self.table = make_table(heads, sortable=False)  # newest first, as Self-training's Dataset version list
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.show_found)
        lay.addWidget(self.table, 1)
        self.empty = EmptyState(self.table)
        self.empty.link.setEnabled(page.working.act_freeze.isEnabled())
        page.working.act_freeze.enabledChanged.connect(self.empty.link.setEnabled)  # on and off as Freeze Dataset… is
        self.found = QLabel()  # what Verify Manifest found wrong in the version picked: the coded line and the files
        self.found.setWordWrap(True)
        self.found.hide()
        lay.addWidget(self.found)
        row = QHBoxLayout()
        self.btn_split = button(self.tr("Split and Lock Validation Set…"), slot=self.open_split)
        self.btn_verify = button(self.tr("Verify Manifest"), slot=self.verify)
        self.btn_export = button(self.tr("Export Manifest…"), slot=self.export_manifest)
        for b in (self.btn_split, self.btn_verify, self.btn_export):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.busy = BusyOverlay(self.table, self.tr("Checking each file against its manifest…"))
        self.split = SplitSheet(self)  # the page lays it out in the labeller agreement's place

    def show_board_model(self, board_model: str | None, picked: str | None = None) -> None:
        """The board model's versions: `picked` selected, else the one picked before while the board model is the
        same, else the newest."""
        if board_model == self.board_model and picked is None:
            picked = self.picked()
        self.board_model = board_model
        self.rows = self.ctx.datasets(board_model) if board_model else []
        counts = self.counts = self.ctx.dataset_counts(board_model) if board_model else {}
        names = {u["uuid"]: u["name"] for u in self.ctx.users()}
        table = []
        for v in self.rows:
            n = counts.get(v["uuid"], {"ok": 0, "ng": 0, "val_ok": 0, "val_ng": 0, "locked": False})
            val = (
                self.tr("{ok} / {ng}").format(ok=n["val_ok"], ng=n["val_ng"]) if n["locked"] else self.tr("not locked")
            )
            uses = ", ".join(self.tr(USES_SHORT[u]) for u in v["allowed_uses"] if u in USES_SHORT)
            by = names.get(v["frozen_by"], v["frozen_by"])
            table.append([v["name"], to_local(v["frozen_at"]), by, n["ok"], n["ng"], val, v["customer"], uses,
                          self._manifest(v["uuid"])])  # fmt: skip
        self.table.blockSignals(True)  # the pick shown once the table is whole, by show_found below
        fill_table(self.table, table)
        if self.rows:
            self.empty.hide()
            self.table.selectRow(next((i for i, v in enumerate(self.rows) if v["uuid"] == picked), 0))
        elif board_model is not None:
            none = self.tr("No frozen dataset for {board_model} yet").format(board_model=board_model)
            then = self.tr("Check the labels, Freeze Dataset, then split and lock its validation set.")
            link = self.tr("Freeze Dataset…") if self.page.working.views else ""
            self.empty.show_state(none, then, link, self.page.working.open_sheet)
        else:
            self.empty.hide()
        self.table.blockSignals(False)
        self.show_found()

    def picked(self) -> str | None:
        """The UUID of the version picked in the table, if any."""
        rows = self.table.selectionModel().selectedRows()
        return self.rows[rows[0].row()]["uuid"] if rows and rows[0].row() < len(self.rows) else None

    def _manifest(self, uuid: str) -> str:
        """The Manifest cell: blank until Verify Manifest has checked the version this session."""
        r = self.verified.get(uuid)
        if r is None:
            return ""
        if self._mismatch(uuid) is None:
            return self.tr("✓ {n}/{files}").format(n=len(r["matched"]), files=r["files"])
        return self.tr("✗ {changed} changed, {missing} missing").format(
            changed=len(r["changed"]), missing=len(r["missing"])
        )

    def _mismatch(self, uuid: str) -> AoiError | None:
        """AOI-TRN-023 for a version Verify Manifest found changed this session, or None."""
        r = self.verified.get(uuid)
        return None if r is None else mismatch(next(v["name"] for v in self.rows if v["uuid"] == uuid), r)

    def show_found(self) -> None:
        """Under the table, what Verify Manifest found wrong in the version picked, if anything: the coded line and
        the files changed or missing, the first few named."""
        uuid = self.picked()
        if self.split.version is not None and self.split.version["uuid"] != uuid:
            self.split.close_sheet()  # the sheet splits the version picked, and only that one
        e = self._mismatch(uuid) if uuid is not None else None
        if e is not None:
            r = self.verified[uuid or ""]
            bad = [Path(p).name for p in r["changed"] + r["missing"]]
            files = ", ".join(bad[:FOUND_SHOWN])
            if len(bad) > FOUND_SHOWN:
                files = self.tr("{files} and {n} more").format(files=files, n=len(bad) - FOUND_SHOWN)
            said = self.tr("{line} Changed or missing: {files}").format(line=self.page.coded_text(e), files=files)
            self.found.setText(said if bad else self.page.coded_text(e))
        self.found.setVisible(e is not None)
        self.sync()

    def sync(self) -> None:
        """Verify Manifest and Export Manifest… need a version picked and no job of the page's running; Split and Lock
        Validation Set…, a version not split, and no sheet of the tab open."""
        uuid, idle = self.picked(), self.page.idle()
        self.btn_verify.setEnabled(uuid is not None and idle)
        self.btn_export.setEnabled(uuid is not None and idle)
        self.btn_export.setVisible(self.page.ctx.role == "Admin")  # an export is an Admin's (Q58, #151)
        locked = uuid is not None and bool(self.counts.get(uuid, {}).get("locked"))
        self.btn_split.setEnabled(uuid is not None and not locked and idle and not self.page.sheet_open())
        said = self.tr("Its validation set is locked: a new split needs a new dataset version")
        self.btn_split.setToolTip(said if locked else "")
        self.split.sync()

    def open_split(self) -> None:
        uuid = self.picked()
        if uuid is not None and self.btn_split.isEnabled():
            self.split.open_for(next(v for v in self.rows if v["uuid"] == uuid), self.counts[uuid])

    def verify(self) -> None:
        """Re-hash the version picked and each of its files on the pool; a Cancel marks nothing."""
        uuid = self.picked()
        if uuid is None or not self.btn_verify.isEnabled():
            return
        name = next(v["name"] for v in self.rows if v["uuid"] == uuid)

        def checked(r: dict[str, Any]) -> None:
            if r["left"]:  # stopped: the files not hashed may differ too
                said = self.tr("Verify Manifest of {name} stopped after {done} of {files} files; nothing was marked")
                self.page.shell.status(said.format(name=name, done=r["files"] - r["left"], files=r["files"]))
                return
            self.verified[uuid] = r
            self.show_board_model(self.board_model)
            if self._mismatch(uuid) is None:
                self.page.shell.status(self.tr("{name}: all {files} files match its manifest").format(
                    name=name, files=r["files"]))  # fmt: skip

        def stopped(r: dict[str, Any] | None) -> None:
            if r is None:
                said = self.tr("Verify Manifest of {name} stopped; nothing was marked")
                self.page.shell.status(said.format(name=name))
            else:
                checked(r)

        self.page.run_in_background(
            self.ctx.verify_dataset, uuid, with_progress=True, on_result=checked, on_cancel=stopped, busy=self.busy,
        )  # fmt: skip
        self.sync()

    def export_manifest(self) -> None:
        """Export Manifest…: once a question naming the version and its file count is answered Yes, the version
        picked as CSV, one row per file as its manifest lists it: path, SHA-256, label, defect type, boxes, labeller and
        checker by name, and its part of the split ("train" or "validation", blank while it is not split). Audited as
        an export; a file that cannot be written is the coded error's dialog, and nothing is written."""
        uuid = self.picked()
        if uuid is None or not self.btn_export.isEnabled():
            return
        version = next(v for v in self.rows if v["uuid"] == uuid)
        items = self.ctx.dataset_items(uuid)
        question = self.tr("Export the manifest of {name}: {files} files, one row each?")
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        asked = question.format(name=version["name"], files=len(items))
        if QMessageBox.question(self, self.tr("Confirm export"), asked, yes | no, yes) != yes:
            return
        start = str(self.ctx.settings.exports_dir / f"{version['name']}.csv")
        f, _ = QFileDialog.getSaveFileName(self, self.tr("Export Manifest"), start, self.tr("CSV (*.csv)"))
        if not f:
            return
        names = {u["uuid"]: u["name"] for u in self.ctx.users()}
        split = self.ctx.validation_split(uuid) or {}
        part = {i: p for p in ("train", "validation") for i in split.get(p, [])}

        def who(user: str | None) -> str:
            return names.get(user, user) if user else ""  # a label carried over by migration 0014 names nobody

        rows = [
            {"path": i["path"], "sha256": i["sha256"], "label": i["label"], "defect_type": stratum(i),
             "boxes": json.dumps(i["boxes"], sort_keys=True), "labelled_by": who(i["labelled_by"]),
             "checked_by": who(i["checked_by"]), "part": part.get(i["uuid"], "")}
            for i in items
        ]  # fmt: skip
        try:
            self.ctx.export_csv(f, rows, "dataset manifest", MANIFEST_COLUMNS)
        except AoiError as e:
            self.page.error(e)
            return
        said = self.tr("Exported the manifest of {name}: {files} files to {file}")
        self.page.shell.status(said.format(name=version["name"], files=len(rows), file=Path(f).name))


class SplitSheet(QGroupBox):
    """Split and Lock Validation Set…'s sheet: what the version picked holds against what a validation set takes, the
    seed, random and editable, Cancel and Lock, which splits the version once, for good."""

    def __init__(self, panel: VersionsPanel) -> None:
        super().__init__()
        self.panel, self.page, self.ctx = panel, panel.page, panel.ctx
        self.version: dict[str, Any] | None = None
        self.enough = False  # the version holds the OK files a validation set takes
        esc = QAction(self, shortcut=QKeySequence(Qt.Key.Key_Escape))
        esc.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.triggered.connect(self.close_sheet)
        self.addAction(esc)
        lay = QVBoxLayout(self)
        self.what = QLabel()  # the version's OK and NG files and what its validation set takes, or why it cannot
        self.what.setWordWrap(True)
        lay.addWidget(self.what)
        self.kinds = QLabel()  # its NG files by defect type, which the validation set's NG are spread over
        self.kinds.setWordWrap(True)
        lay.addWidget(self.kinds)
        fields = QHBoxLayout()
        fields.addWidget(QLabel(self.tr("Seed")))
        self.seed = QLineEdit()
        self.seed.setValidator(QIntValidator(0, SEED_TOP, self))
        self.seed.textChanged.connect(self.sync)
        self.seed.returnPressed.connect(self.lock)
        fields.addWidget(self.seed, 1)
        lay.addLayout(fields)
        once = QLabel(
            self.tr(
                "The lock is audited and never undone: a version is split once, and a new split needs a new dataset"
                " version. Training reads only the training set."
            )
        )
        once.setObjectName("muted")
        once.setWordWrap(True)
        lay.addWidget(once)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button(self.tr("Cancel"), slot=self.close_sheet))
        self.btn_lock = button(self.tr("Lock"), slot=self.lock)
        row.addWidget(self.btn_lock)
        lay.addLayout(row)
        lay.addStretch(1)
        self.busy = BusyOverlay(self, self.tr("Locking the validation set…"))
        self.hide()

    def open_for(self, version: dict[str, Any], counts: dict[str, int]) -> None:
        """The sheet for `version` in the labeller agreement's place, with a new random seed, the focus on it."""
        self.version = version
        self.setTitle(self.tr("Split and lock the validation set of {name}").format(name=version["name"]))
        n = {"ok": counts["ok"], "ng_all": counts["ng"], "least": VALIDATION_OK, "share": round(VALIDATION_NG * 100)}
        self.enough = counts["ok"] >= VALIDATION_OK
        if self.enough:
            what = self.tr(
                "✓ {ok} OK and {ng_all} NG files. The validation set takes {least} OK and {ng} NG ({share} % of the NG,"
                " rounded up), by defect type where it can, and the training set the rest."
            )
        else:
            what = self.tr(
                "✗ {ok} OK and {ng_all} NG files: a validation set takes {least} OK files. Freeze a version with more"
                " OK images, then split that."
            )
        self.what.setText(what.format(ng=math.ceil(VALIDATION_NG * counts["ng"]), **n))
        types = Counter(stratum(i) for i in self.ctx.dataset_items(version["uuid"]) if i["label"] == "NG")
        untyped = self.tr("no type")
        kinds = ", ".join(f"{kind or untyped} {k}" for kind, k in sorted(types.items()))
        self.kinds.setText(self.tr("NG by defect type: {kinds}").format(kinds=kinds))
        self.kinds.setVisible(bool(types))
        self.seed.setText(str(secrets.randbelow(SEED_TOP + 1)))
        self.page.show_sheet(self)
        self.seed.setFocus()
        self.seed.selectAll()

    def sync(self) -> None:
        """Lock needs enough OK files, a seed and no job of the page's running."""
        ready = self.version is not None and self.enough and self.seed.hasAcceptableInput()
        self.btn_lock.setEnabled(ready and self.page.idle())

    def close_sheet(self) -> None:
        if not self.isVisible():
            return
        self.version = None
        self.page.show_sheet(None)

    def lock(self) -> None:
        """Split and lock on the pool, the busy overlay over the sheet; the sheet closes and the status line counts both
        sets. A Cancel before the lock began writes nothing and keeps the sheet for another try, as the Freeze sheet
        does; the lock checks no Cancel, so one after it began comes too late, and the lock is said as without it."""
        v = self.version
        if v is None or not self.btn_lock.isEnabled():
            return
        seed = int(self.seed.text())

        def locked(split: dict[str, Any] | None) -> None:
            if not split:  # stopped before it began, or refused after a Cancel: nothing written
                self.page.shell.status(self.tr("Lock of {name} cancelled: nothing was written").format(name=v["name"]))
                return
            self.close_sheet()
            self.page.refresh()
            n = self.ctx.dataset_counts(v["board_model"])[v["uuid"]]  # the page may show another board model by now
            said = self.tr(
                "Locked the validation set of {name}: {val_ok} OK / {val_ng} NG, the training set {ok} OK / {ng} NG,"
                " seed {seed}"
            )
            self.page.shell.status(said.format(
                name=v["name"], val_ok=n["val_ok"], val_ng=n["val_ng"], ok=n["ok"] - n["val_ok"],
                ng=n["ng"] - n["val_ng"], seed=seed,
            ))  # fmt: skip

        def failed(_e: BaseException) -> None:
            self.close_sheet()  # the coded dialog says what to do; the version may be split by now
            self.page.refresh()

        self.page.run_in_background(
            self.ctx.lock_validation_set, v["uuid"], seed, on_result=locked, on_cancel=locked, on_error=failed,
            busy=self.busy,
        )  # fmt: skip
        self.sync()
