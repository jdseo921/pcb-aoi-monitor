from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.services import AppContext


class Page(QWidget):
    """Base for every navigation page."""

    title = "Page"
    subtitle = ""
    roles = ("Operator", "Engineer", "Admin")  # who may open it (spec 8)

    def __init__(self, ctx: AppContext, shell):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        self.shell = shell  # MainWindow: navigation + shared state
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(20, 14, 20, 14)
        head = QHBoxLayout()
        t = QLabel(self.title)
        t.setObjectName("h1")
        head.addWidget(t)
        if self.subtitle:
            s = QLabel(self.subtitle)
            s.setObjectName("muted")
            head.addWidget(s, 1, Qt.AlignBottom)
        else:
            head.addStretch(1)
        self.head = head
        self.root.addLayout(head)

    @property
    def board_model(self) -> str | None:
        return self.shell.board_model

    # Hooks called by the shell.
    def on_show(self) -> None: ...
    def on_board_model_changed(self, name: str | None) -> None: ...

    def need_board_model(self) -> bool:
        if not self.board_model:
            QMessageBox.information(self, "Board model", "Create or select a board model in the top bar first.")
            return False
        return True

    def error(self, msg: str) -> None:
        QMessageBox.critical(self, "Error", msg[:2000])


def button(text: str, kind: str = "", slot=None) -> QPushButton:
    b = QPushButton(text.replace("&", "&&"))
    if kind:
        b.setObjectName(kind)
    if slot:
        b.clicked.connect(slot)
    return b


def make_table(headers: list[str], sortable: bool = True) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setStretchLastSection(True)
    t.setSortingEnabled(sortable)
    return t


def fill_table(t: QTableWidget, rows: list[list], colors: list[str | None] | None = None) -> None:
    sortable = t.isSortingEnabled()
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            it = QTableWidgetItem()
            if isinstance(v, float):
                it.setData(Qt.DisplayRole, round(v, 4))
            elif isinstance(v, int):
                it.setData(Qt.DisplayRole, v)
            else:
                it.setText("" if v is None else str(v))
            if colors and colors[i]:
                it.setBackground(QColor(colors[i]))
                it.setForeground(QColor("#1f2a36" if colors[i] in ("#fdd835",) else "white"))
            t.setItem(i, j, it)
    t.resizeColumnsToContents()
    t.setSortingEnabled(sortable)
