"""Training › Datasets' Labeller agreement panel (REQ-TRN-016, the screen half; Datasets stage 2 of 4): the labels
sketch's panel, on the Datasets tab beside what a freeze needs (sketch decision Q60). New Set makes a calibration set
of 100 labelled images (proposed) that AppContext draws; the panel says who has labelled how many of its images blind;
Run Agreement Check compares two users who have labelled every image of it, and the newest check of the set is shown
against its targets. Nothing here reads or writes the database itself."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel

from ...core import labels
from ...errors import AoiError
from ...times import to_local
from .base import button

if TYPE_CHECKING:
    from .training import TrainingPage


def _percent(n: int, of: int) -> int:
    """`n` of `of` in whole percent, rounded down, so a count short of a target never shows as reaching it."""
    return 100 * n // of if of else 0


class AgreementPanel(QGroupBox):
    """The board model's calibration sets, the blind labels of the set picked and its newest agreement check."""

    def __init__(self, page: TrainingPage) -> None:
        super().__init__()
        self.setTitle(self.tr("Labeller agreement"))
        self.page, self.ctx = page, page.ctx
        self.board_model: str | None = None
        self._images: dict[str, list[str]] = {}  # each set's images, by its UUID
        form = QFormLayout(self)
        top = QHBoxLayout()
        self.sets = QComboBox()  # the board model's calibration sets, newest first
        self.sets.currentIndexChanged.connect(self.show_set)
        top.addWidget(self.sets, 1)
        self.btn_new = button(self.tr("New Set"), slot=self._new_set)
        top.addWidget(self.btn_new)
        form.addRow(self.tr("Set"), top)
        self.progress = QLabel()  # who has labelled how many of the set's images blind
        self.progress.setObjectName("muted")
        self.progress.setWordWrap(True)
        form.addRow(self.progress)
        pair = QHBoxLayout()
        self.labeller_a, self.labeller_b = QComboBox(), QComboBox()  # users who labelled every image of the set blind
        for box in (self.labeller_a, self.labeller_b):
            box.currentIndexChanged.connect(self._sync)
            pair.addWidget(box, 1)
        form.addRow(self.tr("Labellers"), pair)
        self.ok_ng_line, self.type_line, self.by_line = QLabel(), QLabel(), QLabel()  # the newest check of the set
        for line in (self.ok_ng_line, self.type_line, self.by_line):
            line.setWordWrap(True)
            form.addRow(line)
        self.by_line.setObjectName("muted")
        run = QHBoxLayout()
        self.btn_run = button(self.tr("Run Agreement Check"), slot=self._run)
        run.addWidget(self.btn_run)
        run.addStretch(1)
        form.addRow(run)

    # --- what is shown -------------------------------------------------------------
    def show_board_model(self, board_model: str | None, samples: list[dict[str, Any]]) -> None:
        """The board model's sets, the one picked kept; New Set is off, saying why, below 100 images labelled OK or
        NG. `samples` are the board model's, as the page read them."""
        self.board_model = board_model
        sets = self.ctx.calibration_sets(board_model) if board_model else []
        self._images = {c["uuid"]: c["sample_uuids"] for c in sets}
        picked = self.sets.currentData()
        self.sets.blockSignals(True)
        self.sets.clear()
        names = {u["uuid"]: u["name"] for u in self.ctx.users()}
        for c in sets:
            when, user = to_local(c["at_utc"]), names.get(c["made_by"], c["made_by"])
            self.sets.addItem(self.tr("{when} · made by {user}").format(when=when, user=user), c["uuid"])
        self.sets.setCurrentIndex(max(self.sets.findData(picked), 0))
        self.sets.blockSignals(False)
        labelled = sum(s["label"] in ("OK", "NG") for s in samples)
        self.btn_new.setEnabled(board_model is not None and labelled >= labels.CALIBRATION_IMAGES)
        why = self.tr("Needs {size} images labelled OK or NG; {n} are").format(
            size=labels.CALIBRATION_IMAGES, n=labelled
        )
        self.btn_new.setToolTip("" if self.btn_new.isEnabled() else why)
        self.show_set()

    def show_set(self) -> None:
        """The picked set's blind labels so far, its labellers and its newest agreement check, or the empty state."""
        uid = self.sets.currentData()
        self.sets.setEnabled(uid is not None)
        size = len(self._images.get(uid, []))
        done = self.ctx.blind_labelled(uid) if uid else {}
        names = {u["uuid"]: u["name"] for u in self.ctx.users()}
        if uid is None:
            none = self.tr("No calibration set yet: New Set draws {size} images labelled OK or NG.")
            self.progress.setText(none.format(size=labels.CALIBRATION_IMAGES))
        elif not done:
            self.progress.setText(self.tr("Nobody has labelled this set blind yet."))
        else:
            each = [
                self.tr("{user} {n} of {size}").format(user=names.get(u, u), n=len(d), size=size)
                for u, d in done.items()
            ]
            self.progress.setText(self.tr("Labelled blind: {each}").format(each=" · ".join(each)))
        whole = [u for u, s in done.items() if len(s) == size]
        for n, box in enumerate((self.labeller_a, self.labeller_b)):
            box.blockSignals(True)
            box.clear()
            for u in whole:
                box.addItem(names.get(u, u), u)
            box.setCurrentIndex(min(n, box.count() - 1))
            box.setEnabled(box.count() > 0)
            box.blockSignals(False)
        checks = [c for c in self.ctx.agreement_checks(self.board_model or "") if c["set_uuid"] == uid]
        self._show_check(checks[0] if checks else None, names)
        self._sync()

    def _show_check(self, check: dict[str, Any] | None, names: dict[str, str]) -> None:
        """The check's two lines against their targets and who ran it when, or the sketch's empty state."""
        self.type_line.setVisible(check is not None)
        self.by_line.setVisible(check is not None)
        if check is None:
            self.ok_ng_line.setText(
                self.tr("No agreement check yet. Pick a set of 100 labelled images and two labellers.")
            )
            return
        lines = (("ok_ng_agree", "images", "ok_ng_target"), ("type_agree", "both_ng", "type_target"))
        marks = ["✓" if check[of] and 100 * check[n] >= check[target] * check[of] else "✗" for n, of, target in lines]
        ok_ng = self.tr("OK/NG agreement {n} of {of} ({percent} %) {mark} target {target} %")
        n, of = check["ok_ng_agree"], check["images"]
        self.ok_ng_line.setText(
            ok_ng.format(n=n, of=of, percent=_percent(n, of), mark=marks[0], target=check["ok_ng_target"])
        )
        n, of = check["type_agree"], check["both_ng"]
        if of:
            types = self.tr("Defect type {n} of {of} ({percent} %) {mark} target {target} %")
            types = types.format(n=n, of=of, percent=_percent(n, of), mark=marks[1], target=check["type_target"])
        else:
            types = self.tr("Defect type: no image both labelled NG ✗ target {target} %").format(
                target=check["type_target"]
            )
        self.type_line.setText(types)
        a, b, by = (names.get(check[k], check[k]) for k in ("labeller_a", "labeller_b", "run_by"))
        by_line = self.tr("{a} and {b}, checked {when} by {user}")
        self.by_line.setText(by_line.format(a=a, b=b, when=to_local(check["at_utc"]), user=by))

    def _sync(self) -> None:
        """Run Agreement Check needs two different users who have each labelled every image of the set blind."""
        a, b = self.labeller_a.currentData(), self.labeller_b.currentData()
        why = ""
        if self.labeller_b.count() < 2:
            why = self.tr("Two users must each label every image of the set blind first")
        elif a == b:
            why = self.tr("Pick two different labellers")
        self.btn_run.setEnabled(not why)
        self.btn_run.setToolTip(why)

    # --- actions -------------------------------------------------------------------
    def _new_set(self) -> None:
        """Make a set of the images AppContext draws; it is picked, and the status line says what it holds."""
        bm = self.board_model
        if bm is None:
            return
        try:
            uid = self.ctx.make_calibration_set(bm, self.ctx.propose_calibration_set(bm))
        except AoiError as e:
            self.page.error(e)
            return
        self.page.refresh()
        self.sets.setCurrentIndex(self.sets.findData(uid))
        made = self.tr("Made a calibration set of {size} images. Each labeller now labels it blind.")
        self.page.shell.status(made.format(size=labels.CALIBRATION_IMAGES))

    def _run(self) -> None:
        """Compare the two labellers' blind labels of the set; the check is stored and shown."""
        uid, a, b = self.sets.currentData(), self.labeller_a.currentData(), self.labeller_b.currentData()
        try:
            check = self.ctx.run_agreement_check(uid, a, b)
        except AoiError as e:
            self.page.error(e)
            return
        self.show_set()
        said = self.tr("The labellers agree") if check["agreed"] else self.tr("The labellers fall short of the targets")
        self.page.shell.status(said)
