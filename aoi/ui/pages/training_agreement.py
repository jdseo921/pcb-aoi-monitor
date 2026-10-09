"""Training › Datasets' Labeller agreement panel (REQ-TRN-016, the screen half; Datasets stage 2 of 4): the labels
sketch's panel, on the Datasets tab beside what a freeze needs (sketch decision Q60). New Set makes a calibration set
of 100 labelled images (proposed) that AppContext draws; the panel says who has labelled how many of its images blind;
Label Blind… shows the set's images one by one in the blind panel, which takes the tabs' place; Run Agreement Check
compares two users who have labelled every image of it, and the newest check of the set is shown against its targets.
Nothing here reads or writes the database itself."""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core import labels
from ...defects import names
from ...errors import AoiError
from ...times import to_local
from .. import theme
from ..widgets.busy import BusyOverlay
from ..widgets.image_view import ImageView
from ..workers import Worker, start
from .base import action_button, button

if TYPE_CHECKING:
    import numpy as np

    from ...core.services import AppContext
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
        run = QHBoxLayout()  # the sketch's [Label Blind…]  [Run Agreement Check]
        self.btn_blind = button(self.tr("Label Blind…"), slot=self._label_blind)
        run.addWidget(self.btn_blind)
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
        """Label Blind… needs a set with images the user has not labelled blind yet; Run Agreement Check needs two
        different users who have each labelled every image of the set blind."""
        uid = self.sets.currentData()
        mine = self.ctx.blind_labelled(uid).get(str(self.ctx.user_uuid), []) if uid else []
        done = uid is not None and len(mine) == len(self._images.get(uid, []))
        self.btn_blind.setEnabled(uid is not None and not done)
        self.btn_blind.setToolTip(self.tr("You have labelled every image of this set blind") if done else "")
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

    def _label_blind(self) -> None:
        """The blind panel takes the tabs' place, from the set's first image the user has not labelled blind."""
        uid = self.sets.currentData()
        if uid is None or self.board_model is None:
            return
        paths = {s["uuid"]: str(s["path"]) for s in self.ctx.samples(self.board_model)}
        self.page.open_blind(uid, self._images[uid], paths)

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


def _load(ctx: AppContext, path: str) -> np.ndarray | AoiError:
    """On a pool thread: the image, or the error that refused it, said under the heading with no dialog."""
    try:
        return ctx.load_image(path)
    except AoiError as e:
        return e


class BlindPanel(QWidget):
    """Blind labelling of a calibration set (REQ-TRN-016): its images one by one, each the next the user has not
    labelled blind, shown with no file name, label, defect box or history; Label OK (O), or Label NG (N) with a defect
    type, records the user's own label through `AppContext.label_blind` and shows the next; Stop (Esc) leaves, keeping
    every label made. The panel takes the Samples and Datasets tabs' place while it is shown, so none of their keys
    acts; each image is read on a pool thread."""

    closed = Signal()

    def __init__(self, page: TrainingPage) -> None:
        super().__init__()
        self.page, self.ctx = page, page.ctx
        self.set_uuid: str | None = None
        self.shown: str | None = None  # the image on screen, once read
        self._todo: list[str] = []  # the set's images the user has not labelled blind yet, in the set's order
        self._paths: dict[str, str] = {}
        self._size = 0
        self._reading: Worker | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, theme.SPACE_S, 0, 0)
        head = QHBoxLayout()
        self.heading = QLabel()  # "Image 12 of 100": never its file name, which can name its label
        head.addWidget(self.heading, 1)
        self.act_stop = self._action(self.tr("Stop"), "Esc", self.stop)
        head.addWidget(action_button(self.act_stop, show_key=False))
        lay.addLayout(head)
        note = QLabel(
            self.tr(
                "Label each image as you see it. Its file name, label, defect boxes and history stay hidden, and only"
                " the agreement check counts these labels."
            )
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.unread = QLabel()  # the coded line of an image that cannot be read
        self.unread.setWordWrap(True)
        self.unread.hide()
        lay.addWidget(self.unread)
        self.view = ImageView(placeholder="")
        lay.addWidget(self.view, 1)
        self.busy = BusyOverlay(self.view, self.tr("Opening the image…"))
        row = QHBoxLayout()
        self.act_ok = self._action(self.tr("Label OK"), "O", lambda: self._label("OK"))
        self.act_ng = self._action(self.tr("Label NG"), "N", lambda: self._label("NG"))
        row.addWidget(action_button(self.act_ok, show_key=False))
        row.addWidget(QLabel(self.tr("Type")))
        self.type_box = QComboBox()  # the label editor's 33 types, by category; none picked for each new image
        self.type_box.setMinimumContentsLength(14)
        self.type_box.addItem(self.tr("Pick its defect type"), None)
        for name in names():
            self.type_box.addItem(name, name)
        self.type_box.currentIndexChanged.connect(self._sync)
        row.addWidget(self.type_box, 1)
        self.btn_ng = action_button(self.act_ng, show_key=False)
        self._ng_key = self.btn_ng.toolTip()  # "N", as action_button gives it
        self.type_box.activated.connect(lambda _i: self.btn_ng.setFocus())  # then N, Enter or Space labels it NG
        row.addWidget(self.btn_ng)
        lay.addLayout(row)
        self._sync()

    def _action(self, text: str, key: str, slot: Callable[[], object]) -> QAction:
        """A key of the panel's, acting only while the panel is shown, with the button that shares it."""
        a = QAction(text, self)
        a.setShortcut(QKeySequence(key))
        a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        a.triggered.connect(slot)
        self.addAction(a)
        return a

    def label_set(self, set_uuid: str, images: list[str], paths: dict[str, str]) -> None:
        """Label the set's `images` blind, from the first the user has not labelled; `paths` by sample UUID."""
        mine = set(self.ctx.blind_labelled(set_uuid).get(str(self.ctx.user_uuid), []))
        self.set_uuid, self._paths, self._size = set_uuid, paths, len(images)
        self._todo = [u for u in images if u not in mine]
        self._next()

    def _next(self) -> None:
        """The next image to label, read on a pool thread; with none left the panel closes and says so."""
        self.shown = None
        self.view.set_image(None)
        self.unread.hide()
        self.type_box.setCurrentIndex(0)
        if not self._todo:
            done = self.tr("You have labelled all {size} images of the set blind").format(size=self._size)
            self._close(done)
            return
        uuid = self._todo[0]
        self.heading.setText(self.tr("Image {n} of {size}").format(n=self._size - len(self._todo) + 1, size=self._size))
        if self._reading is not None:
            self._reading.stop()
        w = self._reading = Worker(_load, self.ctx, self._paths[uuid])
        ref = weakref.ref(w)  # the slots hold the worker weakly, as Page.run_in_background's do (#132)

        def result(image: np.ndarray | AoiError) -> None:
            if ref() is self._reading:
                self._show(uuid, image)

        def finished() -> None:
            if ref() is self._reading:
                self._reading = None
                self.busy.finish()
                self._sync()

        w.signals.result.connect(result)
        w.signals.error.connect(self.page.error)
        w.signals.finished.connect(finished)
        self.busy.watch(w.job)
        start(w, self.ctx.jobs)
        self._sync()

    def _show(self, uuid: str, image: np.ndarray | AoiError) -> None:
        if isinstance(image, AoiError):  # not labelled unseen: Stop, and the image is put right or the set made again
            self.unread.setText(self.page.coded_text(image))
            self.unread.show()
            return
        self.shown = uuid
        self.view.set_image(image)
        if self.isVisible():  # the focus on the image: O and N label it, even after a type typed in the Type list
            self.view.setFocus()

    def _sync(self) -> None:
        """Label OK needs the image read; Label NG its defect type too, its tooltip saying so."""
        self.act_ok.setEnabled(self.shown is not None)
        typed = self.type_box.currentData() is not None
        self.act_ng.setEnabled(self.shown is not None and typed)
        self.btn_ng.setToolTip(self._ng_key if typed else self.tr("Pick its defect type first"))

    def _label(self, label: str) -> None:
        """Record the user's blind label of the image shown, then show the next."""
        if self.shown is None or self.set_uuid is None:
            return
        dtype = self.type_box.currentData() if label == "NG" else None
        try:
            self.ctx.label_blind(self.set_uuid, self.shown, label, dtype)
        except AoiError as e:
            self.page.error(e)
            return
        self._todo.pop(0)
        self._next()

    def stop(self) -> None:
        """Leave, every label made kept; Label Blind… goes on from the next image."""
        left = self.tr("Stopped with {n} of {size} images labelled blind").format(
            n=self._size - len(self._todo), size=self._size
        )
        self._close(left)

    def _close(self, said: str) -> None:
        if self._reading is not None:
            self._reading.stop()
            self._reading = None
            self.busy.finish()
        self.set_uuid, self.shown, self._todo = None, None, []
        self.view.set_image(None)
        self.closed.emit()
        self.page.shell.status(said)
