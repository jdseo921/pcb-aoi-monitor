"""Training › Datasets' Working set panel and its Freeze sheet (REQ-TRN-005, the screen half; Datasets stage 4 of 4):
the datasets sketch's working set, view by view with its labels checked, the customer whose dataset store holds the
board model and the allowed uses; Freeze Dataset… shows the Freeze sheet in place of the panels under it, the version
it would make and a line for each thing a freeze needs, ✓ or ✗ with the fix. Nothing here reads or writes the database
itself."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ...core.datasets import ALLOWED_USES
from ...hal import VIEWS
from .base import QT_TRANSLATE_NOOP, action_button, button

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

    def show_board_model(self, board_model: str | None, samples: list[dict[str, Any]]) -> None:
        """Each view's labels and checks, the store's customer; a sheet of another board model closes."""
        if board_model != self.board_model:
            self.sheet.close_sheet()
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

    def _sync(self) -> None:
        """Freeze Dataset… needs a view with an image labelled OK or NG, and no job of the page's running."""
        idle = self.page.idle()
        self.act_freeze.setEnabled(bool(self.views) and idle and not self.sheet.isVisible())
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
    """The Freeze sheet: the view and board revision, the version a freeze makes, what it needs, and Cancel."""

    def __init__(self, panel: WorkingSetPanel) -> None:
        super().__init__()
        self.setTitle(self.tr("Freeze dataset"))
        self.panel, self.page, self.ctx = panel, panel.page, panel.ctx
        self.board_model: str | None = None
        self.gate: dict[str, Any] | None = None
        esc = QAction(self, shortcut=QKeySequence(Qt.Key.Key_Escape))
        esc.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.triggered.connect(self.close_sheet)
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
        self.btn_cancel = button(self.tr("Cancel"), slot=self.close_sheet)
        row.addWidget(self.btn_cancel)
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
        self.page.show_freeze_sheet(True)  # the panels under it hidden first, so the page keeps its height
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
        """The view and the revision, fixed while a job of the page's runs."""
        self.revision.setEnabled(self.page.idle())
        self.view_box.setEnabled(self.page.idle())

    def close_sheet(self) -> None:
        if not self.isVisible():
            return
        self.hide()
        self.gate = None
        self.page.show_freeze_sheet(False)
        self.panel.sync()
