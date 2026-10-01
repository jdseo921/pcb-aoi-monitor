"""3D Profile Viewer (spec 4.5). Needs Stage 2 3D camera data; laid out now so
the navigation and the Accept/Reject review flow are fixed early."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .base import Page, button, make_table


class Profile3DPage(Page):
    title = "3D Profile"
    subtitle = "Height & coplanarity · available after Stage 2 (3D camera integration)"
    roles = ("Engineer", "Admin")

    def __init__(self, ctx, shell):
        super().__init__(ctx, shell)
        body = QHBoxLayout()
        canvas = QLabel("3D height map\n\nConnect a 3D camera (Stage 2) to view\n"
                        "colour-coded height maps, rotate / zoom / pan,\nand height-slice graphs with peak markers.")
        canvas.setAlignment(Qt.AlignCenter)
        canvas.setStyleSheet("background:#0f161d; border:1px dashed #3f5a75; color:#6c7c8c; border-radius:8px;")
        body.addWidget(canvas, 3)
        side = QWidget(); sl = QVBoxLayout(side)
        t = make_table(["Type", "Height", "Volume"]); sl.addWidget(t, 1)
        row = QHBoxLayout()
        a = button("Accept Defect", "start"); r = button("Reject Defect", "stop")
        a.setEnabled(False); r.setEnabled(False)
        row.addWidget(a); row.addWidget(r); sl.addLayout(row)
        body.addWidget(side, 1)
        self.root.addLayout(body, 1)
