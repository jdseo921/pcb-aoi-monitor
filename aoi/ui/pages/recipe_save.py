"""Save Recipe's confirmation sheet on the Recipe Editor (REQ-RCP-004, REQ-RCP-005; recipe-editor sketch): inline under
the tabs, never a dialog over a dialog. It names the revision a save makes, lists what it changes from the latest one,
before → after, and the mandatory AOI checks the recipe leaves uncovered, for which it asks a reason; the reason is kept
with the revision, in the audit entry of its save. Also the Revisions tab's pane that opens a revision read-only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from ...core.recipe import ADDED, REMOVED, Change, Recipe
from ...times import to_local
from .base import QT_TRANSLATE_NOOP, button, fill_table, make_table

SETTINGS = {  # a Change's field as the sheet and the Revisions tab name it; a field not here is shown as stored
    "use_ai": QT_TRANSLATE_NOOP("SaveSheet", "AI check"),
    "anomaly_threshold": QT_TRANSLATE_NOOP("SaveSheet", "AI score threshold"),
    "warn_ratio": QT_TRANSLATE_NOOP("SaveSheet", "WARN band"),
    "use_compare": QT_TRANSLATE_NOOP("SaveSheet", "Golden board comparison"),
    "diff_threshold": QT_TRANSLATE_NOOP("SaveSheet", "Pixel difference"),
    "min_defect_area": QT_TRANSLATE_NOOP("SaveSheet", "Minimum defect area (px)"),
    "min_defect_mm": QT_TRANSLATE_NOOP("SaveSheet", "Minimum defect size (mm)"),
    "ssim_min": QT_TRANSLATE_NOOP("SaveSheet", "Similarity minimum (SSIM)"),
    "changed_pct_max": QT_TRANSLATE_NOOP("SaveSheet", "Maximum changed area %"),
    "max_diff_regions": QT_TRANSLATE_NOOP("SaveSheet", "Allowed difference regions"),
    "type": QT_TRANSLATE_NOOP("SaveSheet", "type"),
    "x": QT_TRANSLATE_NOOP("SaveSheet", "X (px)"),
    "y": QT_TRANSLATE_NOOP("SaveSheet", "Y (px)"),
    "w": QT_TRANSLATE_NOOP("SaveSheet", "W (px)"),
    "h": QT_TRANSLATE_NOOP("SaveSheet", "H (px)"),
    "mm": QT_TRANSLATE_NOOP("SaveSheet", "box in mm"),
    "ai_score": QT_TRANSLATE_NOOP("SaveSheet", "AI score"),
    "height_min": QT_TRANSLATE_NOOP("SaveSheet", "height min"),
    "height_max": QT_TRANSLATE_NOOP("SaveSheet", "height max"),
    "volume_min": QT_TRANSLATE_NOOP("SaveSheet", "volume min"),
    "volume_max": QT_TRANSLATE_NOOP("SaveSheet", "volume max"),
    "side": QT_TRANSLATE_NOOP("SaveSheet", "side"),
    "enabled": QT_TRANSLATE_NOOP("SaveSheet", "enabled"),
}


class SaveSheet(QGroupBox):
    """The sheet: what the save changes and the checks left uncovered, a reason (required while a Stage 1 check is
    uncovered), Cancel and Save Revision n+1, a plain button, as the page keeps one blue primary. Save Revision is off
    while nothing changes, as a revision never repeats the one before it; Esc in the sheet or Cancel closes it.
    `confirm` saves, with the reason typed in `reason`."""

    def __init__(self, confirm: Callable[[], None], type_text: Callable[[str], str]) -> None:
        super().__init__()
        self.setTitle(self.tr("Save Recipe"))
        self._confirm, self._type_text = confirm, type_text
        self.shown: tuple[list[str], list[str]] = ([], [])  # the lines and the checks the sheet shows
        self.restoring: tuple[int, Recipe] | None = None  # Restore as New Revision's revision, while the sheet is open
        lay = QVBoxLayout(self)
        self.heading, self.changes, self.missing = QLabel(), QLabel(), QLabel()
        self.missing.setObjectName("badge")  # amber, as AOI-RCP-009 is under the scale
        for label in (self.heading, self.changes, self.missing):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)  # an ROI's or a board model's name is never read as markup
            lay.addWidget(label)
        form = QFormLayout()
        self.reason, self.reason_label = QLineEdit(), QLabel()
        self.reason.textChanged.connect(self._sync)
        self.reason.returnPressed.connect(self.confirm)
        form.addRow(self.reason_label, self.reason)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button(self.tr("Cancel"), slot=self.close_sheet))
        self.btn_save = button(self.tr("Save Revision"), slot=self.confirm)  # named with its revision on open
        row.addWidget(self.btn_save)
        lay.addLayout(row)
        esc = QAction(self, shortcut=QKeySequence(Qt.Key.Key_Escape))
        esc.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.triggered.connect(self.close_sheet)
        self.addAction(esc)
        self.hide()

    def open_for(
        self,
        board_model: str,
        revision: int,
        changes: list[Change],
        uncovered: list[str],
        restoring: tuple[int, Recipe] | None = None,
    ) -> None:
        """Show the sheet for a save of `board_model`'s recipe after `revision`, which it never replaces: the recipe as
        edited, or with `restoring`, a revision and its recipe as stored, a copy of that revision (Q24)."""
        lines = [self.line(c) for c in changes]
        self.shown, self.restoring = (lines, uncovered), restoring
        if restoring is None:
            ask = self.tr(
                "Save the recipe of {board_model} as revision {next}? Revision {revision} stays as it was saved."
            )
        else:
            ask = self.tr(
                "Restore revision {old} of {board_model} as revision {next}? Revision {revision} stays as it was saved."
            )
        old = restoring[0] if restoring else None
        self.heading.setText(ask.format(board_model=board_model, next=revision + 1, revision=revision, old=old))
        none = self.tr("Nothing changed since revision {revision}.").format(revision=revision)
        self.changes.setText("\n".join(lines) or none)
        said = self.tr("Not covered: {checks}. A reason is needed to save without them, and is kept with the revision.")
        self.missing.setText(said.format(checks=", ".join(uncovered)))
        self.missing.setVisible(bool(uncovered))
        self.reason_label.setText(self.tr("Reason (required)") if uncovered else self.tr("Reason"))
        self.btn_save.setText(self.tr("Save Revision {next}").format(next=revision + 1))
        self.reason.clear()
        self.show()
        self.reason.setFocus()
        self._sync()

    def line(self, c: Change) -> str:
        """One change as the sheet and the Revisions tab say it."""
        if c.field in (ADDED, REMOVED):
            added = c.field == ADDED
            return (self.tr("ROI {roi} added") if added else self.tr("ROI {roi} removed")).format(roi=c.roi)
        what = self.name(c.field)
        if c.roi is not None:
            what = self.tr("ROI {roi}, {setting}").format(roi=c.roi, setting=what)
        before, after = (self.value(c.field, v) for v in (c.before, c.after))
        return self.tr("{setting}: {before} → {after}").format(setting=what, before=before, after=after)

    def name(self, field: str) -> str:
        return self.tr(SETTINGS[field]) if field in SETTINGS else field

    def value(self, field: str, v: object) -> str:
        """A setting's value as stored, as the sheet and the Revisions tab show it."""
        if v is None:
            return "—"
        if isinstance(v, bool):
            return self.tr("on") if v else self.tr("off")
        if isinstance(v, float):
            return f"{v:g}"
        if isinstance(v, list):  # an ROI's box in mm: x, y, w, h
            return ", ".join(f"{x:.2f}" for x in v)
        return self._type_text(str(v)) if field == "type" else str(v)

    def _sync(self, *_: object) -> None:
        lines, uncovered = self.shown
        self.btn_save.setEnabled(bool(lines) and (not uncovered or bool(self.reason.text().strip())))

    def confirm(self) -> None:
        if self.btn_save.isEnabled():
            self._confirm()

    def close_sheet(self) -> None:
        self.hide()
        self.reason.clear()
        self.restoring = None


class RevisionPane(QGroupBox):
    """Open on the Revisions tab (REQ-RCP-004): a revision read-only beside the recipe as edited, as stored: its
    settings, its ROIs, and what the recipe as edited changes from it. Nothing in it can be edited or saved."""

    def __init__(self, sheet: SaveSheet) -> None:
        super().__init__()
        self._sheet = sheet  # its wording of a setting and of a change
        lay = QVBoxLayout(self)
        self.settings, self.against = QLabel(), QLabel()
        for label in (self.settings, self.against):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            lay.addWidget(label)
        self.rois = make_table([], sortable=False)  # read-only: make_table's cells take no edit
        lay.addWidget(self.rois, 1)
        self.hide()

    def show_revision(
        self, rev: dict[str, Any], headers: list[str], rois: list[list[object]], against: list[Change]
    ) -> None:
        """Show `rev`, a row of `AppContext.recipe_revisions`, with its ROIs as `rois` under `headers`, as the ROIs tab
        shows them, and `against`, the changes from it to the recipe as edited."""
        n, recipe = rev["revision"], rev["recipe"]
        title = self.tr("Revision {revision}, read-only: saved by {user}, {saved}")
        self.setTitle(title.format(revision=n, user=rev["user"], saved=to_local(rev["created_at"])))
        stored = {k: v for k, v in recipe.to_dict().items() if k not in ("board_model", "rois")}
        one = self.tr("{setting}: {value}")
        said = [one.format(setting=self._sheet.name(k), value=self._sheet.value(k, v)) for k, v in stored.items()]
        self.settings.setText("  ·  ".join(said))
        lines = [self._sheet.line(c) for c in against]
        head = self.tr("What the recipe as edited changes from revision {revision}:").format(revision=n)
        same = self.tr("The recipe as edited is the same as revision {revision}.").format(revision=n)
        self.against.setText("\n".join([head, *lines]) if lines else same)
        self.rois.setColumnCount(len(headers))
        self.rois.setHorizontalHeaderLabels(headers)
        fill_table(self.rois, rois)
        self.show()
