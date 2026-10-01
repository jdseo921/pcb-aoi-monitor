"""System settings, users and hardware status (Admin)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...config import APP_VERSION
from .base import Page, button, fill_table, make_table

HARDWARE = [
    ["Image files (folder camera)", "Stage 1", "Ready"],
    ["GigE / USB3 Vision camera", "Stage 2", "Not connected"],
    ["Lighting controller (serial / Ethernet)", "Stage 2", "Not connected"],
    ["Robot controller (Ethernet / RS-485)", "Stage 3", "Not connected"],
    ["MES / ERP (REST / OPC UA)", "Stage 4", "Not connected"],
]


class SettingsPage(Page):
    title = "Settings"
    subtitle = f"Version {APP_VERSION}"
    roles = ("Admin",)

    def __init__(self, ctx, shell):
        super().__init__(ctx, shell)
        body = QHBoxLayout()
        g = QGroupBox("System")
        f = QFormLayout(g)
        s = ctx.settings
        self.ws = QLineEdit(s.workspace)
        ws_row = QWidget()
        wl = QHBoxLayout(ws_row)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self.ws)
        wl.addWidget(button("Browse…", slot=self._browse))
        self.device = QComboBox()
        self.device.addItems(["auto", "cpu", "cuda"])
        self.device.setCurrentText(s.device)
        self.size = QComboBox()
        self.size.addItems(["128", "256", "384", "512"])
        self.size.setCurrentText(str(s.image_size))
        self.epochs = QSpinBox()
        self.epochs.setRange(5, 1000)
        self.epochs.setValue(s.default_epochs)
        self.ret = QSpinBox()
        self.ret.setRange(1, 3650)
        self.ret.setValue(s.log_retention_days)
        self.lang = QComboBox()
        self.lang.addItems(["en", "ko"])
        self.lang.setCurrentText(s.language)
        f.addRow("Workspace (images, models, DB)", ws_row)
        f.addRow("AI device", self.device)
        f.addRow("Default input size", self.size)
        f.addRow("Default epochs", self.epochs)
        f.addRow("Log retention (days)", self.ret)
        f.addRow("Language", self.lang)
        f.addRow(button("Save Settings", "primary", self.save))
        body.addWidget(g, 1)

        right = QVBoxLayout()
        ug = QGroupBox("Users & roles")
        ul = QVBoxLayout(ug)
        self.users = make_table(["Name", "Role"])
        ul.addWidget(self.users)
        ul.addWidget(button("Add / Change User", slot=self.add_user))
        right.addWidget(ug, 1)
        hg = QGroupBox("Hardware interfaces")
        hl = QVBoxLayout(hg)
        self.hw = make_table(["Interface", "Stage", "Status"])
        hl.addWidget(self.hw)
        right.addWidget(hg, 1)
        body.addLayout(right, 1)
        self.root.addLayout(body, 1)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Workspace folder", self.ws.text())
        if d:
            self.ws.setText(d)

    def save(self):
        s = self.ctx.settings
        moved = s.workspace != self.ws.text()
        s.workspace, s.device = self.ws.text(), self.device.currentText()
        s.image_size, s.default_epochs = int(self.size.currentText()), self.epochs.value()
        s.log_retention_days, s.language = self.ret.value(), self.lang.currentText()
        s.save()
        QMessageBox.information(self, "Settings", "Saved." + (" Restart the app to switch workspace." if moved else ""))

    def add_user(self):
        name, ok = QInputDialog.getText(self, "User", "User name")
        if ok and name:
            role, ok = QInputDialog.getItem(self, "Role", "Role", ["Operator", "Engineer", "Admin"], 0, False)
            if ok:
                self.ctx.db.add_user(name, role)
                self.on_show()

    def on_show(self):
        fill_table(self.users, [[u["name"], u["role"]] for u in self.ctx.db.users()])
        fill_table(self.hw, HARDWARE)
