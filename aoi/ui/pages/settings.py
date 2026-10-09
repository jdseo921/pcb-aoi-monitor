"""System settings, users, dataset stores and hardware status (Admin)."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
from ...core.services import AppContext
from ...errors import AoiError
from .base import QT_TRANSLATE_NOOP, ROLES, Page, button, fill_table, make_table, role_text
from .settings_stores import StoresPanel

if TYPE_CHECKING:
    from ..main_window import MainWindow

_S1 = QT_TRANSLATE_NOOP("SettingsPage", "Stage 1")  # a literal each: pyside6-lupdate extracts no other text (#199)
_S2 = QT_TRANSLATE_NOOP("SettingsPage", "Stage 2")
_S3 = QT_TRANSLATE_NOOP("SettingsPage", "Stage 3")
_S4 = QT_TRANSLATE_NOOP("SettingsPage", "Stage 4")
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

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
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
        self.input_size = QComboBox()
        self.input_size.addItems(["128", "256", "384", "512"])
        self.input_size.setCurrentText(str(s.image_size))
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
        f.addRow(self.tr("Default input size"), self.input_size)
        f.addRow(self.tr("Default epochs"), self.epochs)
        f.addRow(self.tr("Log retention (days)"), self.ret)
        f.addRow(self.tr("Language"), self.lang)
        f.addRow(button(self.tr("Save Settings"), "primary", self.save))
        left = QVBoxLayout()
        left.addWidget(g)
        self.stores = StoresPanel(self)  # the customers' encrypted dataset stores (REQ-TRN-017), under System
        left.addWidget(self.stores, 1)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        ug = QGroupBox(self.tr("Users & roles").replace("&", "&&"))  # a lone & would be a mnemonic, not shown
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

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.tr("Workspace folder"), self.ws.text())
        if d:
            self.ws.setText(d)

    def save(self) -> None:
        """Write the page's own settings over settings.json as it is now, so a hand edit of another key stays (#170),
        through `AppContext.save_settings`: an Admin's write, role-checked and audited (#197). Each value is checked
        first (AOI-SET-008: an empty or relative workspace), and nothing is written on a refusal. The running app
        follows the device, defaults and retention at once (#201) and the workspace from the restart (REQ-SET-001); the
        language is stored only until the 2H 2027 localisation."""
        values = {
            "workspace": self.ws.text(),
            "device": self.device.currentText(),
            "image_size": int(self.input_size.currentText()),
            "default_epochs": self.epochs.value(),
            "log_retention_days": self.ret.value(),
            "language": self.lang.currentData(),
        }
        try:
            self.ctx.save_settings(values)
        except (AoiError, OSError) as e:  # AOI-USR-001 below the Admin role, AOI-SET-008, AOI-SET-010, a disk error
            self.error(e)
            return
        moved = self.ctx.settings.workspace != values["workspace"]
        saved = self.tr("Saved. Restart the app to switch the workspace.") if moved else self.tr("Saved.")
        QMessageBox.information(self, self.tr("Settings"), saved)

    def add_user(self) -> None:
        name, ok = QInputDialog.getText(self, self.tr("User"), self.tr("User name"))
        if ok and name:
            names = [role_text(r) for r in ROLES]
            current = next((u["role"] for u in self.ctx.users() if u["name"] == name), None)
            at = ROLES.index(current) if current in ROLES else 0  # an existing user's own role: OK changes nothing
            role, ok = QInputDialog.getItem(self, self.tr("Role"), self.tr("Role"), names, at, False)
            if ok:
                chosen = ROLES[names.index(role)]
                try:
                    self.ctx.add_user(name, chosen)  # the last Admin keeps the role (AOI-USR-002)
                except AoiError as e:
                    self.error(e)
                    return
                self.on_show()
                if name == self.ctx.user and chosen != current:  # the signed-in user's own role changed
                    self.shell.set_user(name)  # the header and the pages follow the role add_user stored

    def on_user_changed(self) -> None:
        self.stores.close_sheet()  # the recovery sheet, or a key half typed, never stays for the next user

    def on_show(self) -> None:
        fill_table(self.users, [[u["name"], role_text(u["role"])] for u in self.ctx.users()])
        self.stores.refresh()
        fill_table(self.hw, [[self.tr(cell) for cell in row] for row in HARDWARE])
