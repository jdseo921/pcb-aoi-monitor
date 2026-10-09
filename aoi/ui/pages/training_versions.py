"""Training › Datasets' Working set panel (REQ-TRN-005, the screen half; Datasets stage 4 of 4): the datasets sketch's
working set, view by view with its labels checked, the customer whose dataset store holds the board model and the
allowed uses a freeze names. Nothing here reads or writes the database itself."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
)

from ...core.datasets import ALLOWED_USES
from ...hal import VIEWS
from .base import QT_TRANSLATE_NOOP, button

if TYPE_CHECKING:
    from .training import TrainingPage

USES = {  # the sketch's three, own ticked: placeholders until Jay names the uses a customer's contract allows (Q38)
    "own": QT_TRANSLATE_NOOP("WorkingSetPanel", "Their own AI models"),
    "shared": QT_TRANSLATE_NOOP("WorkingSetPanel", "Shared improvement"),
    "demos": QT_TRANSLATE_NOOP("WorkingSetPanel", "Demos"),
}


class WorkingSetPanel(QGroupBox):
    """The board model's labels view by view, its customer and the uses a freeze allows."""

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
        form.addRow(self.tr("Customer"), top)
        uses = QHBoxLayout()
        self.uses: dict[str, QCheckBox] = {}
        for use in ALLOWED_USES:
            box = self.uses[use] = QCheckBox(self.tr(USES[use]))
            box.setChecked(use == "own")
            uses.addWidget(box)
        uses.addStretch(1)
        form.addRow(self.tr("Allowed uses"), uses)

    def show_board_model(self, board_model: str | None, samples: list[dict[str, Any]]) -> None:
        """Each view's labels and checks, and the store's customer."""
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
