"""System settings, users and hardware status (Admin)."""

from __future__ import annotations

from PySide6.QtCore import QT_TRANSLATE_NOOP
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
from .base import ROLES, Page, button, fill_table, make_table, role_text

_S1, _S2, _S3, _S4 = (QT_TRANSLATE_NOOP("SettingsPage", s) for s in ("Stage 1", "Stage 2", "Stage 3", "Stage 4"))
_NOT_CONNECTED = QT_TRANSLATE_NOOP("SettingsPage", "Not connected")
HARDWARE = [  # (interface, stage, status), shown through tr()
    (QT_TRANSLATE_NOOP("SettingsPage", "Image files (folder camera)"), _S1, QT_TRANSLATE_NOOP("SettingsPage", "Ready")),
    (QT_TRANSLATE_NOOP("SettingsPage", "GigE / USB3 Vision camera"), _S2, _NOT_CONNECTED),
    (QT_TRANSLATE_NOOP("SettingsPage", "Lighting controller (serial / Ethernet)"), _S2, _NOT_CONNECTED),
    (QT_TRANSLATE_NOOP("SettingsPage", "Robot controller (Ethernet / RS-485)"), _S3, _NOT_CONNECTED),
    (QT_TRANSLATE_NOOP("SettingsPage", "MES / ERP (REST / OPC UA)"), _S4, _NOT_CONNECTED),
]
LANGUAGES = (("en", "English"), ("ko", "한국어"))  # a language is named in its own language, so these stay as they are


class SettingsPage(Page):
    title = QT_TRANSLATE_NOOP("Page", "Settings")
    subtitle = QT_TRANSLATE_NOOP("SettingsPage", "Version {version}")
    roles = ("Admin",)

    def subtitle_text(self) -> str:
        return self.tr(self.subtitle).format(version=APP_VERSION)

    def __init__(self, ctx, shell):
        super().__init__(ctx, shell)
        body = QHBoxLayout()
        g = QGroupBox(self.tr("System"))
        f = QFormLayout(g)
        s = ctx.settings
        self.ws = QLineEdit(s.workspace)
        ws_row = QWidget()
        wl = QHBoxLayout(ws_row)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self.ws)
        wl.addWidget(button(self.tr("Browse…"), slot=self._browse))
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
        for code, name in LANGUAGES:
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(s.language)))
        f.addRow(self.tr("Workspace (images, AI models, database)"), ws_row)
        f.addRow(self.tr("AI device"), self.device)
        f.addRow(self.tr("Default input size"), self.size)
        f.addRow(self.tr("Default epochs"), self.epochs)
        f.addRow(self.tr("Log retention (days)"), self.ret)
        f.addRow(self.tr("Language"), self.lang)
        f.addRow(button(self.tr("Save Settings"), "primary", self.save))
        body.addWidget(g, 1)

        right = QVBoxLayout()
        ug = QGroupBox(self.tr("Users & roles"))
        ul = QVBoxLayout(ug)
        self.users = make_table([self.tr("Name"), self.tr("Role")])
        ul.addWidget(self.users)
        ul.addWidget(button(self.tr("Add / Change User"), slot=self.add_user))
        right.addWidget(ug, 1)
        hg = QGroupBox(self.tr("Hardware interfaces"))
        hl = QVBoxLayout(hg)
        self.hw = make_table([self.tr("Interface"), self.tr("Stage"), self.tr("Status")])
        hl.addWidget(self.hw)
        right.addWidget(hg, 1)
        body.addLayout(right, 1)
        self.root.addLayout(body, 1)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, self.tr("Workspace folder"), self.ws.text())
        if d:
            self.ws.setText(d)

    def save(self):
        s = self.ctx.settings
        moved = s.workspace != self.ws.text()
        s.workspace, s.device = self.ws.text(), self.device.currentText()
        s.image_size, s.default_epochs = int(self.size.currentText()), self.epochs.value()
        s.log_retention_days, s.language = self.ret.value(), self.lang.currentData()
        s.save()
        saved = self.tr("Saved. Restart the app to switch the workspace.") if moved else self.tr("Saved.")
        QMessageBox.information(self, self.tr("Settings"), saved)

    def add_user(self):
        name, ok = QInputDialog.getText(self, self.tr("User"), self.tr("User name"))
        if ok and name:
            names = [role_text(r) for r in ROLES]
            role, ok = QInputDialog.getItem(self, self.tr("Role"), self.tr("Role"), names, 0, False)
            if ok:
                self.ctx.add_user(name, ROLES[names.index(role)])
                self.on_show()

    def on_show(self):
        fill_table(self.users, [[u["name"], role_text(u["role"])] for u in self.ctx.users()])
        fill_table(self.hw, [[self.tr(cell) for cell in row] for row in HARDWARE])
