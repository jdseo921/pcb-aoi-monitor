"""About, from the header for every role (REQ-SET-011): the app and its build, the selected board model's AI model and
recipe revision, the database schema, the station's ID, the licence and the third-party notices, with one Copy button
that puts all but the notices on the clipboard for a support ticket."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from . import theme
from .pages.base import button, size_class


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None, facts: dict[str, Any]) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("About"))
        self.setMinimumWidth(theme.CARD_W)
        none = self.tr("none")
        self.rows = [
            (self.tr("App"), facts["app"]),
            (self.tr("Commit"), facts["commit"] or self.tr("none (from source)")),
            (self.tr("Board model"), facts["board_model"] or none),
            (self.tr("AI model"), facts["ai_model"] or self.tr("none active")),
            (self.tr("Recipe revision"), none if facts["recipe_rev"] is None else str(facts["recipe_rev"])),
            (self.tr("Database schema"), str(facts["schema"])),
            (self.tr("Station ID"), facts["station"] or none),
            (self.tr("Licence"), facts["licence"] or self.tr("none yet")),
        ]
        lay = QVBoxLayout(self)
        form = QFormLayout()
        for label, value in self.rows:
            shown = QLabel(value)
            shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label, shown)
        lay.addLayout(form)
        notices = facts["notices"]
        lay.addWidget(QLabel(self.tr("Third-party notices")))
        if notices is None:
            muted = QLabel(self.tr("In THIRD_PARTY_NOTICES.txt beside the app, in an installed build."))
            muted.setObjectName("muted")
            muted.setWordWrap(True)
            lay.addWidget(muted)
        else:
            self.notices = QPlainTextEdit(notices.read_text(encoding="utf-8", errors="replace"))
            self.notices.setReadOnly(True)
            lay.addWidget(self.notices, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        for b in (button(self.tr("Copy"), slot=self.copy), button(self.tr("Close"), "primary", self.accept)):
            row.addWidget(size_class(b, "T"))
        lay.addLayout(row)

    def text(self) -> str:
        return "\n".join(f"{label}: {value}" for label, value in self.rows)

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text())
