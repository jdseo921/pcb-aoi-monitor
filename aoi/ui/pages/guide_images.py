"""Screen 2 of the first-run guide on Home (REQ-TRN-021, REQ-TRN-001, REQ-TRN-003; B5, docs/sketches/first-run-guide.md,
Q69 to Q71): the board model's images, picked as one folder that holds ok/ and ng/<defect type>/, copied in the view
picked as soon as the folder is picked, counted against what a Trial AI model needs (What is missing's first three
lines), and a box drawn on each NG image, the next one with no box opening after each.

The copy is `AppContext.import_files` on a pool thread (REQ-SET-021): the progress pattern's line while it runs, with
Cancel (Esc), which keeps the images copied before it. Images straight in ng/ take the defect type picked from the list
that shows then, and the copy starts on the pick (Q71). Each image not taken is counted, and Show Why lists it with its
code. The box area is always drawing (Q70): a drag stores the box, of the type its folder gave and that type's severity
(`AppContext.set_boxes`), then opens the next NG image with no box, passing over one that cannot be read, which is named
under it; a drag on a box moves it. ← Back (PgUp) opens the one before, for a second box or one to move, and Undo
(Ctrl+Z) takes the last box drawn away again. A refusal is said under the control that raised it, with its code, and a
press on an off control, or its key, says why on the status bar; the screen shows no dialog of its own.

What the screen holds is of the board model shown: another board model, or another user signed in, starts it afresh
(`forget`), and a copy running goes on, its line naming its board model while another one is shown."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ...core import datasets
from ...core.labels import DefectBox
from ...core.sample_import import NG_FOLDERS, ImportFile, ImportReport, folder_files
from ...core.services import GUIDE_IMAGES, ErrorReport
from ...defects import names
from ...errors import AoiError
from ...hal import VIEWS
from .. import theme
from ..errors import phrase_text
from ..widgets.box_editor import BoxEditor
from ..workers import Worker, start
from .base import PressSays, button, size_class, time_left_text, view_text
from .guide_said import Said, said_text
from .missing_list import NAMES
from .training_import import stop_error

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...core.services import AppContext
    from .base import Page

ZOOM_STEP = 1.25  # one Zoom In, as the label editor's
OPENS = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)  # keys that open the closed type list
PASSES = (Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Escape, Qt.Key.Key_F4)  # keys the closed type list keeps


def _read(ctx: AppContext, path: str) -> np.ndarray | AoiError:
    """On a pool thread: an NG image as `load_image` reads it, or the error that refused it."""
    try:
        return ctx.load_image(path)
    except AoiError as e:  # gone or damaged since it was copied: said under the box area
        return e


class _ListOnly(QObject):
    """The type of the images straight in ng is picked in the list, as the copy starts on the pick (Q71): on the closed
    box, the arrows, a letter typed and the wheel, which would move it onto a type, do nothing, and Enter or Space opens
    the list, where a click or Enter picks."""

    def __init__(self, box: QComboBox) -> None:
        super().__init__(box)
        self.box = box
        box.installEventFilter(self)

    def eventFilter(self, watched: QObject, e: QEvent) -> bool:  # noqa: N802 (Qt's name)
        if e.type() == QEvent.Type.Wheel:
            return True
        if isinstance(e, QKeyEvent) and e.type() == QEvent.Type.KeyPress:
            if e.key() in OPENS:
                self.box.showPopup()
                return True
            alt_down = e.key() == Qt.Key.Key_Down and e.modifiers() & Qt.KeyboardModifier.AltModifier
            return not (e.key() in PASSES or alt_down)
        return False


class GuideImages(QWidget):
    """Screen 2 for `board_model` (`show_for`); `changed` follows each copy and each box stored, for the guide to see
    whether screen 2 is done."""

    changed = Signal()

    def __init__(self, page: Page, status: Callable[[str], object]) -> None:
        super().__init__()
        self.page, self.ctx, self.status = page, page.ctx, status
        self.board_model: str | None = None
        self.folder = ""  # the folder picked last, as the line under Pick Folder names it
        self.view_picked = False  # a view button pressed for this board model: kept, never set from its images again
        self.waiting: list[ImportFile] = []  # a pick's files while the type of the images straight in ng is asked
        self.copying: Worker | None = None
        self.copy_for = ""  # the board model the copy running copies into
        self.reading: Worker | None = None
        self.ng: list[dict[str, Any]] = []  # the NG images of the view, oldest first: the box area's order
        self.at = -1  # the one the box area shows, by its place in `ng`
        self.open_uuid: str | None = None  # and by its sample, which a list read again finds by
        self.loaded: dict[str, Any] | None = None  # the sample whose picture the box area holds: a box goes on it
        self.unreadable: dict[str, str] = {}  # NG images that could not be read, skipped: what refused each
        self.undo: list[tuple[str, list[DefectBox]]] = []  # each box drawn: its image and the boxes it had before
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._first(lay)
        self._picker(lay)
        self._lines(lay)
        self._box_area(lay)

    # --- the layout ---------------------------------------------------------------------------------------------
    def _first(self, lay: QVBoxLayout) -> None:
        """Before any image: the board model has none, what it needs, and how the folder is laid out."""
        self.first = QWidget()
        first = QVBoxLayout(self.first)
        first.setContentsMargins(0, 0, 0, 0)
        self.none = QLabel()
        self.none.setObjectName("guideSteps")
        self.none.setWordWrap(True)
        needs = QLabel(phrase_text(datasets.needs(trial=True)))
        needs.setWordWrap(True)
        rule = QLabel(
            self.tr(
                "Pick one folder with two folders in it: ok, with the good boards' images, and ng, with a folder for"
                " each defect named after it, such as {example}."
            ).format(example=str(Path("ng") / "Missing Component"))
        )
        rule.setWordWrap(True)
        for w in (self.none, needs, rule):
            first.addWidget(w)
        lay.addWidget(self.first)

    def _picker(self, lay: QVBoxLayout) -> None:
        """The view, Pick Folder…, the copy's line with Cancel, the type for images straight in ng, and what the copy
        did."""
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("View")))
        self.views = QButtonGroup(self)
        self.views.buttonClicked.connect(self._view_picked)
        self.view_buttons: dict[str, QRadioButton] = {}
        for v in VIEWS:
            b = size_class(QRadioButton(view_text(v)), "T")
            PressSays(b, self._pick_off, self.status)  # off while a copy runs, as Pick Folder… is
            self.views.addButton(b)
            self.view_buttons[v] = b
            row.addWidget(b)
        self.view_buttons["Top"].setChecked(True)
        row.addStretch(1)
        self.btn_pick = size_class(button(self.tr("Pick Folder…  Ctrl+O"), "primary", self.pick_folder), "T")
        PressSays(self.btn_pick, self._pick_off, self.status)
        pick = QAction(self.tr("Pick Folder…"), self)  # its text for F1's list (`keys`)
        pick.setShortcut(QKeySequence("Ctrl+O"))
        pick.triggered.connect(self.pick_folder)
        self.addAction(pick)  # while screen 2 shows
        row.addWidget(self.btn_pick)
        lay.addLayout(row)
        self.typing = QWidget()  # images straight in ng: their defect type, picked before the copy starts (Q71)
        typing = QHBoxLayout(self.typing)
        typing.setContentsMargins(0, 0, 0, 0)
        typing.addWidget(QLabel(self.tr("Defect type for the images in ng")))
        self.ng_type = QComboBox()
        self.ng_type.setMinimumWidth(theme.FIELD_W)
        self.ng_type.addItems(names())
        self.ng_type.setCurrentIndex(-1)
        self.ng_type.activated.connect(self._typed)
        _ListOnly(self.ng_type)
        typing.addWidget(self.ng_type)
        typing.addStretch(1)
        self.typing.hide()
        lay.addWidget(self.typing)
        self.copy_row = QWidget()  # the progress pattern's line while the copy runs, with Cancel
        copy_row = QHBoxLayout(self.copy_row)
        copy_row.setContentsMargins(0, 0, 0, 0)
        self.copy_line = QLabel()
        copy_row.addWidget(self.copy_line, 1)
        self.btn_cancel = button(self.tr("Cancel  Esc"), slot=self.cancel)
        copy_row.addWidget(self.btn_cancel)
        esc = QAction(self.tr("Cancel"), self.copy_row)
        esc.setShortcut(QKeySequence("Esc"))
        esc.triggered.connect(self.cancel)
        self.copy_row.addAction(esc)  # while the copy runs
        self.copy_row.hide()
        lay.addWidget(self.copy_row)
        self.picked = Said()  # a pick refused: no image in ok or ng, a Cancel, or the error the copy stopped at
        lay.addWidget(self.picked)
        taken = QHBoxLayout()
        self.from_line = QLabel()  # "From E:\TBOX-A1, Top view. Not taken: 0."
        self.from_line.setWordWrap(True)
        taken.addWidget(self.from_line, 1)
        self.btn_why = button(self.tr("Show Why"), slot=self._toggle_why)
        taken.addWidget(self.btn_why)
        lay.addLayout(taken)
        self.why = QLabel()  # each image not taken, with its code
        self.why.setWordWrap(True)
        self.why.setObjectName("muted")
        self.why.hide()
        lay.addWidget(self.why)
        self.from_line.hide()
        self.btn_why.hide()

    def _lines(self, lay: QVBoxLayout) -> None:
        """What is missing's first three lines, ✓ when met."""
        self.need_lines: dict[str, QLabel] = {}
        for key in GUIDE_IMAGES:
            line = QLabel()
            line.setWordWrap(True)
            self.need_lines[key] = line
            lay.addWidget(line)

    def _box_area(self, lay: QVBoxLayout) -> None:
        """The NG image, always drawing, and beside it what to do, where it is in the list, and its keys."""
        self.boxes = QWidget()
        grid = QGridLayout(self.boxes)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(0, 1)
        self.editor = BoxEditor(placeholder=self.tr("NG image: drag across the defect"))
        self.editor.setMinimumHeight(theme.GUIDE_IMAGE_H)
        self.editor.moves_while_drawing = True  # always drawing (Q70), and a box still moved by a drag on it
        self.editor.edited.connect(self._edited)
        grid.addWidget(self.editor, 0, 0, 2, 1)
        side = QVBoxLayout()
        self.what = QLabel(self.tr("Draw a box around the defect."))
        self.what.setWordWrap(True)
        self.where = QLabel()  # "Image 4 of 10 · n04.png"
        self.where.setWordWrap(True)
        self.kind = QLabel()  # "Missing Component (its folder)"
        self.kind.setWordWrap(True)
        nxt = QLabel(self.tr("The next image opens after each box."))
        nxt.setWordWrap(True)
        nxt.setObjectName("muted")
        self.box_refused = Said()  # a box not kept, in the guide's words with its code (Q78)
        self.skipped = QLabel()  # the NG images skipped, as they cannot be read: each with its code
        self.skipped.setWordWrap(True)
        self.skipped.hide()
        for w in (self.what, self.where, self.kind, nxt, self.box_refused, self.skipped):
            side.addWidget(w)
        side.addStretch(1)
        keys = QGridLayout()
        presses = (  # each button's words, its key and what it does, the action's text for F1's list (`keys`)
            (self.tr("← Back"), "PgUp", self.back),
            (self.tr("Undo"), "Ctrl+Z", self.undo_box),
            (self.tr("Zoom In"), "+", lambda: self.editor.zoom(ZOOM_STEP)),
            (self.tr("Zoom Out"), "-", lambda: self.editor.zoom(1 / ZOOM_STEP)),
            (self.tr("Fit"), "0", self.editor.fit),
        )
        made = []
        for n, (words, key, slot) in enumerate(presses):
            b = button(self.tr("{action}  {key}").format(action=words, key=key), slot=slot)
            keys.addWidget(b, n // 2, n % 2)
            made.append(b)
            act = QAction(words, self.boxes)
            act.setShortcut(QKeySequence(key))
            act.triggered.connect(slot)
            self.boxes.addAction(act)  # while the box area shows
        self.btn_back, self.btn_undo, self.btn_in, self.btn_out, self.btn_fit = made
        PressSays(self.btn_back, self._back_off, self.status)
        PressSays(self.btn_undo, self._undo_off, self.status)
        side.addLayout(keys)
        grid.addLayout(side, 0, 1)
        self.boxes.hide()
        lay.addWidget(self.boxes)

    # --- what shows --------------------------------------------------------------------------------------------
    def show_for(self, board_model: str) -> None:
        """Screen 2 for `board_model`: its counts read again, and the box area on the image it showed, or the first NG
        image with no box; afresh for another board model (`forget`)."""
        if board_model != self.board_model:
            self.forget()
        self.board_model = board_model
        self.refresh()

    def forget(self) -> None:
        """What the screen held of the board model shown, gone, for another board model or the next user signed in: the
        folder picked and what its copy did, a type still asked for, the view pressed, the image open, the images
        skipped and the boxes Undo would take away. A copy running goes on."""
        self.folder, self.view_picked, self.waiting, self.undo = "", False, [], []
        self.at, self.open_uuid, self.loaded, self.reading = -1, None, None, None
        self.unreadable.clear()
        for w in (self.from_line, self.btn_why, self.why, self.typing, self.skipped):
            w.hide()
        self.picked.clear()
        self.box_refused.clear()
        self.btn_why.setText(self.tr("Show Why"))
        self.editor.set_image(None)
        self.editor.show_boxes([])

    def refresh(self) -> None:
        """The counts, the help before any image, the lines, Pick Folder for a role that may copy, and the box area: on
        the image it shows, found again by its sample in the list read again, or else the first NG image with no box."""
        bm = self.board_model
        if bm is None:
            return
        missing = self.ctx.missing(bm, trial=True)
        needs = {n.key: n for n in missing.needs}
        any_image = needs["ok"].have + needs["ng"].have > 0
        self.first.setVisible(not any_image)
        self.none.setText(self.tr("No images of {board_model} yet").format(board_model=bm))
        if any_image and not self.view_picked:
            self.view_buttons[missing.view].setChecked(True)
        for key, line in self.need_lines.items():
            n = needs[key]
            name = QCoreApplication.translate("MissingList", NAMES[key])
            said = self.tr("{mark} {name}: {have} of {need}").format(
                mark="✓" if n.done else "○", name=name, have=n.have, need=n.need
            )
            if key == "ok" and not n.done and n.have:
                more = self.tr("Add {more} more to the ok folder and pick it again; images already in are skipped.")
                said = f"{said}. {more.format(more=n.need - n.have)}"
            line.setText(said)
        self.ng = [s for s in self.ctx.samples(bm, "NG") if s["side"] == missing.view]
        self.at = next((i for i, s in enumerate(self.ng) if s["uuid"] == self.open_uuid), -1)
        if self.at < 0:
            self.loaded = None  # gone from the list, as when labelled OK on Training: no box goes on it
        self._show_skipped()
        drawing = bool(self.ng) and not needs["ng_boxed"].done and self.copying is None
        self.boxes.setVisible(drawing)
        if drawing and self.at < 0:
            self.open_image(self._next_unboxed(-1))
        elif self.at >= 0:
            self._where()
        self._gate()

    def _gate(self) -> None:
        """Pick Folder, the view and the type list for a role that may copy images, off while a copy runs; the box
        area's keys for one that may draw."""
        busy = self.copying is not None
        gates = self.page.gates
        gates.gate(self.btn_pick, "import_samples", not busy)
        for radio in self.view_buttons.values():
            gates.gate(radio, "import_samples", not busy)
        gates.gate(self.ng_type, "import_samples", not busy)
        gates.gate(self.btn_back, "set_boxes", self._before(self.at) >= 0)
        gates.gate(self.btn_undo, "set_boxes", bool(self.undo))
        self.editor.locked = not gates.may("set_boxes")

    def keys(self) -> list[QAction]:
        """The keys of the parts of screen 2 shown, for F1's list of Home's keys."""
        parts = (self, self.copy_row, self.boxes)
        return [a for part in parts if not part.isHidden() for a in part.actions()]

    def _pick_off(self) -> str:
        """Why Pick Folder… and the view are off, said on a press or on Ctrl+O: the role needed, or a copy running."""
        why = self.page.gates.why.get(self.btn_pick)
        if why:
            return why
        if self.copy_for and self.copy_for != self.board_model:
            return self.tr("A copy into {board_model} is running: Cancel (Esc) stops it.").format(
                board_model=self.copy_for
            )
        return self.tr("A copy is running: Cancel (Esc) stops it.")

    def _back_off(self) -> str:
        return self.page.gates.why.get(self.btn_back) or self.tr("This is the first NG image.")

    def _undo_off(self) -> str:
        return self.page.gates.why.get(self.btn_undo) or self.tr("No box drawn on this screen to undo.")

    def _view_picked(self) -> None:
        self.view_picked = True

    def view(self) -> str:
        return next(v for v, b in self.view_buttons.items() if b.isChecked())

    # --- the copy ----------------------------------------------------------------------------------------------
    def pick_folder(self) -> None:
        """Pick Folder… (Ctrl+O): the folder's images, each labelled and typed by its folders, copied in the view
        picked as soon as it is picked (Q69); a folder with none in ok or ng copies nothing and says how to lay it out.
        Images straight in ng wait for their type (Q71); a folder picked after drops a type still asked for. While a
        copy runs, or for a role that may not copy, the status bar says why and nothing opens."""
        if self.board_model is None:
            return
        if self.copying is not None or not self.btn_pick.isEnabled():
            self.status(self._pick_off())
            return
        drive = self.ctx.usb_drive()  # Q68: the images come on a USB drive
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("Pick the folder with ok and ng in it"), str(drive) if drive else ""
        )
        if not folder:
            return
        self.waiting = []
        self.typing.hide()
        self.folder = folder
        self.picked.clear()
        files = folder_files(folder)
        if not any(f.label for f in files):
            self.picked.say_text(
                self.tr(
                    "No images in ok or ng folders in {folder}. Put the good boards' images in ok and the defective"
                    " ones in ng, in a folder named after the defect, then pick the folder again."
                ).format(folder=folder)
            )
            return
        view = self.view()
        for f in files:
            f.side = view
        if any(self._plain_ng(f) for f in files):
            self.waiting = files
            self.ng_type.setCurrentIndex(-1)
            self.typing.show()
            self.ng_type.setFocus()
            return
        self.copy(files)

    @staticmethod
    def _plain_ng(f: ImportFile) -> bool:
        """An image straight in ng/, not in a folder named after its defect: it takes the type picked for them all."""
        return f.label == "NG" and f.defect_type is None and Path(f.path).parent.name.lower() in NG_FOLDERS

    def _typed(self, index: int) -> None:
        """The type of the images straight in ng picked in the list: they take it, and the copy starts (Q71)."""
        if index < 0 or not self.waiting:
            return
        for f in self.waiting:
            if self._plain_ng(f):
                f.defect_type = self.ng_type.itemText(index)
        files, self.waiting = self.waiting, []
        self.typing.hide()
        self.copy(files)

    def copy(self, files: list[ImportFile]) -> None:
        """Copy `files` into the board model on a pool thread, one `import_samples` call each, so Cancel keeps what
        went in (#194); the line says the image it is at, the percent and the time left. The copy keeps its board
        model, folder and view: what it did is said on the screen of that board model only."""
        bm = self.board_model
        if bm is None or not files:
            return
        folder, view = self.folder, files[0].side
        w = self.copying = Worker(self.ctx.import_files, bm, files, with_progress=True)
        self.copy_for = bm
        w.signals.progress.connect(lambda _done: self._copy_progress(w))
        w.signals.result.connect(lambda report: self._copied(report, len(files), bm, folder, view))
        w.signals.error.connect(lambda e: self._copy_failed(e, bm))
        w.signals.finished.connect(lambda: self._copy_ended(w))
        self.copy_line.setText(self.tr("Copying the images…"))
        self.copy_row.show()
        self.boxes.hide()
        self._gate()
        start(w, self.ctx.jobs)

    def _copy_progress(self, w: Worker) -> None:
        info = w.job.progress()
        if w is not self.copying or not info.total:
            return
        line = self.tr("Copying image {n} of {count} · {percent} % · {left}")
        percent = 100 * info.done // info.total
        said = line.format(n=info.done, count=info.total, percent=percent, left=time_left_text(info.left_s))
        if self.copy_for != self.board_model:  # another board model shown: the line names the copy's
            said = self.tr("{board_model}: {line}").format(board_model=self.copy_for, line=said)
        self.copy_line.setText(said)

    def cancel(self) -> None:
        """Cancel (Esc): the copy stops after the image in hand, the images copied before it kept."""
        if self.copying is not None:
            self.copying.stop()

    def _copied(self, report: ImportReport, total: int, board_model: str, folder: str, view: str) -> None:
        """What the copy did: the line under Pick Folder names the folder and the view and counts the images not taken
        and those already in, which Show Why lists with their codes, with the boxes an annotation file gave; an error
        that stopped it is said there too, logged and alarmed. With another board model shown, the status bar says the
        copy ended."""
        stopped: ErrorReport | str | None = None  # an error that stopped it at an image, or the line of a Cancel
        if (e := stop_error(report, total, board_model)) is not None and report.stopped is not None:
            stopped = self._report(e)  # logged and alarmed whichever board model is shown
        elif report.left:  # Cancel
            at = self.tr("Copying stopped at image {at} of {total}; the ones before it are kept.")
            stopped = at.format(at=total - len(report.left) + 1, total=total)
        already = [(f, e) for f, e in report.refused if e.code == "AOI-TRN-015"]
        not_taken = [(f, e) for f, e in report.refused if e.code != "AOI-TRN-015"]
        if board_model != self.board_model:
            said = self.tr("The copy into {board_model} ended: {added} copied, {count} not taken.")
            self.status(said.format(board_model=board_model, added=len(report.added), count=len(not_taken)))
            return
        line = self.tr("From {folder}, {view} view. Not taken: {count}.").format(
            folder=folder, view=view_text(view), count=len(not_taken)
        )
        already_in = self.tr("Already in: {count}.")
        if already:
            line = f"{line} {already_in.format(count=len(already))}"
        boxed = sum(count for _f, count, _why in report.boxes)
        from_files = self.tr("Boxes from annotation files: {count}.")
        if boxed:
            line = f"{line} {from_files.format(count=boxed)}"
        self.from_line.setText(line)
        self.from_line.show()
        why = [f"{Path(f.path).name}: {said_text(ErrorReport.of(e))}" for f, e in [*not_taken, *already]]
        partly = self.tr("copied, but not every box of its annotation file was stored: {why}.")
        why += [f"{Path(f.path).name}: {partly.format(why=phrase_text(w))}" for f, _n, w in report.boxes if w]
        self.why.setText("\n".join(why))
        self.why.hide()
        self.btn_why.setVisible(bool(why))
        self.btn_why.setText(self.tr("Show Why"))
        if isinstance(stopped, str):
            self.picked.say_text(stopped)
        elif stopped is not None and report.stopped is not None:
            self.picked.say(stopped, f"{Path(report.stopped[0].path).name}:")

    def _copy_failed(self, e: BaseException, board_model: str) -> None:
        said = self._report(e)  # logged and alarmed whichever board model is shown
        if board_model == self.board_model:
            self.picked.say(said)

    def _copy_ended(self, w: Worker) -> None:
        if w is not self.copying:
            return
        self.copying, self.copy_for = None, ""
        self.copy_row.hide()
        self.at, self.open_uuid = -1, None
        self.refresh()
        self.changed.emit()

    def _report(self, e: BaseException) -> ErrorReport:
        """An error the guide says: logged and alarmed (`AppContext.report_error`)."""
        return self.ctx.report_error(e, "Home")

    def _toggle_why(self) -> None:
        shown = not self.why.isVisible()
        self.why.setVisible(shown)
        self.btn_why.setText(self.tr("Hide Why") if shown else self.tr("Show Why"))

    # --- the boxes ---------------------------------------------------------------------------------------------
    def _boxes_of(self, sample: dict[str, Any]) -> list[DefectBox]:
        return [DefectBox(r["x"], r["y"], r["w"], r["h"], r["dct_type"]) for r in self.ctx.boxes(sample["uuid"])]

    def _next_unboxed(self, after: int) -> int:
        """The first NG image with no box after `after`, round to the start, passing over those that cannot be read;
        -1 when there is none."""
        count = len(self.ng)
        for step in range(1, count + 1):
            i = (after + step) % count
            if self.ng[i]["uuid"] not in self.unreadable and not self.ctx.boxes(self.ng[i]["uuid"]):
                return i
        return -1

    def _before(self, at: int) -> int:
        """The NG image before `at` that can be read, or -1."""
        return next((i for i in range(at - 1, -1, -1) if self.ng[i]["uuid"] not in self.unreadable), -1)

    def _where(self) -> None:
        """Where the image shown is in the list, and the type a box drawn on it takes."""
        sample = self.ng[self.at]
        where = self.tr("Image {n} of {count} · {file}")
        self.where.setText(where.format(n=self.at + 1, count=len(self.ng), file=Path(sample["path"]).name))
        self.kind.setText(self.tr("{type} (its folder)").format(type=self.editor.new_type))

    def open_image(self, at: int) -> None:
        """The NG image `at` in the box area, read on a pool thread, with its boxes; one drawn takes its type. Until it
        is read, a drag draws nothing."""
        if not (0 <= at < len(self.ng)):
            return
        self.at = at
        sample = self.ng[at]
        self.open_uuid, self.loaded = sample["uuid"], None
        self.box_refused.clear()
        self.editor.set_image(None)
        self.editor.show_boxes([])
        self.editor.new_type = sample["defect_type"] or names()[0]
        self._where()
        self._gate()
        w = self.reading = Worker(_read, self.ctx, str(sample["path"]))
        w.signals.result.connect(lambda image: self._read(w, sample, image))
        w.signals.error.connect(lambda e: self._read(w, sample, e))
        start(w, self.ctx.jobs)

    def _read(self, w: Worker, sample: dict[str, Any], image: np.ndarray | BaseException) -> None:
        """The image read: shown, always drawing, a drag on a box moving it; one that cannot be read is skipped,
        named with its code under the box area, and the next NG image with no box opens."""
        if w is not self.reading:
            return  # another image was asked for since
        self.reading = None
        if isinstance(image, BaseException):
            self.unreadable[sample["uuid"]] = f"{Path(sample['path']).name}: {said_text(self._report(image))}"
            self._show_skipped()
            self._gate()
            nxt = self._next_unboxed(self.at)
            if nxt >= 0:
                self.open_image(nxt)
            return
        self.loaded = sample
        self.editor.set_image(image)
        self.editor.show_boxes(self._boxes_of(sample))
        self.editor.set_draw_mode(True)

    def _show_skipped(self) -> None:
        """The NG images skipped in the list shown, as they cannot be read, each with its code."""
        names_ = [self.unreadable[s["uuid"]] for s in self.ng if s["uuid"] in self.unreadable]
        head = self.tr("Skipped, as they cannot be read:")
        self.skipped.setText("\n".join([head, *names_]))
        self.skipped.setVisible(bool(names_))

    def _edited(self) -> None:
        """A box drawn, moved or resized on the image shown: stored at once; after a box drawn, the next NG image with
        no box opens."""
        sample = self.loaded
        if sample is None:
            return
        before = self._boxes_of(sample)
        boxes = list(self.editor.boxes)
        try:
            self.ctx.set_boxes(sample["uuid"], boxes)
        except AoiError as e:
            self.box_refused.say(self._report(e))
            self.editor.show_boxes(before)
            return
        self.box_refused.clear()
        if len(boxes) > len(before):
            self.undo.append((sample["uuid"], before))
            self._after_box()

    def _after_box(self) -> None:
        nxt = self._next_unboxed(self.at)
        self.refresh()
        self.changed.emit()
        if nxt >= 0 and self.boxes.isVisible():
            self.open_image(nxt)

    def back(self) -> None:
        """← Back (PgUp): the NG image before the one shown; on the first, the status bar says so."""
        if not self.boxes.isVisible():
            return
        if not self.btn_back.isEnabled():
            self.status(self._back_off())
            return
        self.open_image(self._before(self.at))

    def undo_box(self) -> None:
        """Undo (Ctrl+Z): the last box drawn taken away again, its image shown; with none, the status bar says so."""
        if not self.btn_undo.isEnabled():
            self.status(self._undo_off())
            return
        uuid, before = self.undo.pop()
        try:
            self.ctx.set_boxes(uuid, before)
        except AoiError as e:
            self.box_refused.say(self._report(e))
            return
        self.refresh()
        self.changed.emit()
        at = next((i for i, s in enumerate(self.ng) if s["uuid"] == uuid), -1)
        if at >= 0 and self.boxes.isVisible():
            self.open_image(at)
