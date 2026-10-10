"""3D Profile Viewer (spec 4.5). Needs Stage 2 3D camera data: until then the page is the sketch's one card, "Coming in
Stage 2" (profile3d-card.md, REQ-P3D-001): what the page will show, where the height and volume thresholds are entered
now, and two buttons, to the Recipe Editor and back to Home. Nothing else is drawn, so no control looks usable before
Stage 2: no image area, no table, no Accept or Reject button and no disabled control."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ...core.services import AppContext
from .. import theme
from .base import QT_TRANSLATE_NOOP, Page, action_button

if TYPE_CHECKING:
    from ..main_window import MainWindow


class Stage2Card(QFrame):
    """The empty-state pattern as one card CARD_W px wide (REQ-SET-019): a 20 pt heading, what is missing and why
    (`sentence`), what to do until then (`until`), and the page's two buttons in a row, its one blue primary first."""

    def __init__(self, heading: str, sentence: str, until: str, link: QPushButton, back: QPushButton) -> None:
        super().__init__()
        self.setObjectName("empty")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(theme.CARD_W)  # the sketch's 720 px: every page is wider than that (#104)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(2 * theme.SPACE,) * 4)
        layout.setSpacing(theme.SPACE)
        self.heading, self.sentence, self.until = QLabel(heading), QLabel(sentence), QLabel(until)
        self.heading.setObjectName("h1")
        for label in (self.heading, self.sentence, self.until):
            label.setWordWrap(True)
            layout.addWidget(label)
        self.link, self.back = link, back
        row = QHBoxLayout()
        row.addWidget(link)
        row.addStretch(1)
        row.addWidget(back)
        layout.addSpacing(theme.SPACE_S)
        layout.addLayout(row)


class Profile3DPage(Page):
    title = QT_TRANSLATE_NOOP("Page", "3D Profile")
    subtitle = QT_TRANSLATE_NOOP("Page", "Stage 2")
    roles = ("Engineer", "Admin")
    badge = QT_TRANSLATE_NOOP("Page", "Stage 2")  # the entry stays, so nobody looks for the page elsewhere (Q9)
    badge_tip = QT_TRANSLATE_NOOP("Page", "Available with the 3D camera in Stage 2")

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        to_editor = self.action(self.tr("Open Recipe Editor ›"), "Return", lambda: shell.navigate("Recipe Editor"))
        to_editor.setShortcuts([QKeySequence("Return"), QKeySequence("Enter")])  # the main keys' and the number pad's
        back = self.action(self.tr("Back to Home"), "Esc", lambda: shell.navigate("Home"))
        self.card = Stage2Card(
            self.tr("Coming in Stage 2"),
            self.tr(
                "This page needs the 3D camera of Stage 2. It will show the height map of a board, the four AOI checks"
                " that need height data (Shield Can Gap, Connector Pin Height, 3D Coplanarity, Solder Volume), and"
                " Accept / Reject for each height defect."
            ),
            self.tr(
                "Height and volume thresholds (min and max) can be entered per ROI in the Recipe Editor until then;"
                " they are stored now and checked from Stage 2."
            ),
            action_button(to_editor, "primary", show_key=False),  # the page's one blue primary
            action_button(back, show_key=False),
        )
        row = QHBoxLayout()  # centred between stretches, not by alignment: an aligned item's height is worked out at
        row.addStretch(1)  # the page's width, too few lines for the card's text at its own (as #245 found for
        row.addWidget(self.card)  # the empty state)
        row.addStretch(1)
        self.root.addStretch(1)
        self.root.addLayout(row)
        self.root.addStretch(2)
