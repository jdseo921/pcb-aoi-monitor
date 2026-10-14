"""The first-run guide's refusal line (REQ-TRN-021; B5, docs/sketches/first-run-guide.md, "Errors", Q78): under the
control that raised it, the catalogue's title, the guide's line for the code (`aoi.errors.GUIDE`) and the code, with
the catalogue's own text, which names the Engineering pages, behind Show Details. A code the guide has no line for is
said as the catalogue says it, and a line of the guide's own, such as a Cancel's, with no code."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.services import ErrorReport
from ..errors import phrase_text
from .base import button


def said_text(report: ErrorReport) -> str:
    """`report` as one line of the guide, in the UI language: its title, the guide's line or else what happened and what
    to do, and its code."""
    line = phrase_text(report.guide) if report.guide else f"{phrase_text(report.what)} {phrase_text(report.action)}"
    said = QCoreApplication.translate("Said", "{title}: {line} ({code})")
    return said.format(title=phrase_text(report.title), line=line, code=report.code)


class Said(QWidget):
    """One refusal, or one line of the guide's own, hidden until said; Show Details opens the catalogue's text under it,
    for a code the guide has a line for."""

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.line = QLabel()
        self.line.setWordWrap(True)
        row.addWidget(self.line, 1)
        self.btn_details = button(self.tr("Show Details"), slot=self._details)
        self.btn_details.hide()
        row.addWidget(self.btn_details, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(row)
        self.details = QLabel()  # the catalogue's what happened and what to do
        self.details.setObjectName("muted")
        self.details.setWordWrap(True)
        self.details.hide()
        lay.addWidget(self.details)
        self.code: str | None = None  # the code said, None for a line of the guide's own
        self.hide()

    def say(self, report: ErrorReport, before: str = "") -> None:
        """Say `report`, after `before` when it is given (the file the refusal is of), Show Details closed."""
        line = said_text(report)
        self.line.setText(f"{before} {line}" if before else line)
        self.code = report.code
        self.details.setText(f"{phrase_text(report.what)} {phrase_text(report.action)}" if report.guide else "")
        self._shown(False)
        self.btn_details.setVisible(bool(report.guide))
        self.show()

    def say_text(self, text: str) -> None:
        """Say a line of the guide's own, with no code and nothing behind Show Details."""
        self.line.setText(text)
        self.code = None
        self.details.clear()
        self._shown(False)
        self.btn_details.hide()
        self.show()

    def text(self) -> str:
        """The line said."""
        return self.line.text()

    def clear(self) -> None:
        """Nothing said: hidden."""
        self.line.clear()
        self.details.clear()
        self.code = None
        self._shown(False)
        self.hide()

    def _details(self) -> None:
        self._shown(self.details.isHidden())

    def _shown(self, on: bool) -> None:
        self.details.setVisible(on)
        self.btn_details.setText(self.tr("Hide Details") if on else self.tr("Show Details"))
