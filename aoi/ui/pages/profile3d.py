"""3D Profile Viewer (spec 4.5). Needs Stage 2 3D camera data: until then the page is one card that says so and
leads to the Recipe Editor, where height and volume limits are already entered per ROI (sketch profile3d-card.md)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt

from ...core.services import AppContext
from .. import theme
from ..widgets.empty_state import EmptyState
from .base import QT_TRANSLATE_NOOP, Page, button

if TYPE_CHECKING:
    from ..main_window import MainWindow


class Profile3DPage(Page):
    title = QT_TRANSLATE_NOOP("Page", "3D Profile")
    subtitle = QT_TRANSLATE_NOOP("Page", "Height and coplanarity · available after Stage 2 (3D camera integration)")
    roles = ("Engineer", "Admin")

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        self.card = EmptyState(kind="primary")  # the page's one button is its primary
        self.card.setMaximumWidth(theme.CARD_W)
        self.root.addWidget(self.card, 0, Qt.AlignmentFlag.AlignHCenter)
        self.root.addWidget(
            button(self.tr("Back to Home"), slot=lambda: shell.navigate("Home")), 0, Qt.AlignmentFlag.AlignHCenter
        )
        self.root.addStretch(1)

    def on_show(self) -> None:
        what = self.tr(
            "Height and coplanarity need the 3D camera. Height and volume limits can be entered per ROI in the "
            "Recipe Editor; they are stored now and checked from Stage 2."
        )
        self.card.show_state(self.tr("3D Profile arrives with Stage 2"), *self.empty_step(what, "Recipe Editor"))
