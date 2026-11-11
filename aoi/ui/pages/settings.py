"""System settings, users, dataset stores and hardware status (Admin)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...config import APP_VERSION
from ...core import retention
from ...core.services import AppContext
from ...errors import AoiError
from ...times import to_local
from .. import theme
from .base import QT_TRANSLATE_NOOP, ROLES, Page, button, fill_table, make_table, role_text, size_class
from .settings_demo import DemoPanel
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
        f = self.form = QFormLayout(g)
        s = ctx.settings
        self.ws = QLineEdit(s.workspace)
        ws_row = QWidget()
        wl = QHBoxLayout(ws_row)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self.ws)
        wl.addWidget(button(self.tr("Browse…"), slot=self._browse))
        self.input_folder, input_row = self._folder_row(s.input_folder, self.tr("Input folder"))  # REQ-INSP-020
        self.output_folder, output_row = self._folder_row(s.output_folder, self.tr("Output folder"))  # REQ-INSP-021
        self.device = QComboBox()
        self.device.addItems(["auto", "cpu", "cuda"])
        self.device.setCurrentText(s.device)
        self.input_size = QComboBox()
        self.input_size.addItems(["128", "256", "384", "512", "640"])  # ADR 0012: 256 by default, 640 for small defects
        self.input_size.setCurrentText(str(s.image_size))
        self.epochs = QSpinBox()
        self.epochs.setRange(5, 1000)
        self.epochs.setValue(s.default_epochs)
        self.ret = QSpinBox()
        self.ret.setRange(1, 3650)
        self.ret.setValue(s.log_retention_days)
        self.map_ret = QSpinBox()  # the map retention and the two image limits, kept in Settings.check's bounds (Q56)
        self.map_ret.setRange(0, 3650)
        self.map_ret.setValue(s.map_retention_days_ok)
        self.ok_evidence = QComboBox()  # the evidence policy for OK boards (D1, REQ-INSP-012)
        self.ok_evidence.addItem(self.tr("JPEG and preview"), "jpeg")
        self.ok_evidence.addItem(self.tr("Full PNG, as NG"), "full")
        self.ok_evidence.setCurrentIndex(max(0, self.ok_evidence.findData(s.ok_evidence)))
        self.max_mp = QSpinBox()
        self.max_mp.setRange(1, 1000)
        self.max_mp.setValue(s.max_image_megapixels)
        self.max_mb = QSpinBox()
        self.max_mb.setRange(1, 10000)
        self.max_mb.setValue(s.max_image_megabytes)
        self.shift_hours = QSpinBox()  # REQ-INSP-017: 0 asks for no shift check, as Settings.check bounds it
        self.shift_hours.setRange(0, 24)
        self.shift_hours.setValue(s.shift_check_hours)
        self.lang = QComboBox()
        for code, name in LANGUAGES:
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(s.language)))
        f.addRow(self.tr("Workspace (images, AI models, database)"), ws_row)
        f.addRow(self.tr("Input folder (empty: none)"), input_row)
        f.addRow(self.tr("Output folder (empty: none)"), output_row)
        f.addRow(self.tr("AI device"), self.device)
        f.addRow(self.tr("Default input size"), self.input_size)
        f.addRow(self.tr("Default epochs"), self.epochs)
        f.addRow(self.tr("Log retention (days)"), self.ret)
        f.addRow(self.tr("Keep OK results' maps (days)"), self.map_ret)
        f.addRow(self.tr("OK boards keep"), self.ok_evidence)
        f.addRow(self.tr("Largest image (megapixels)"), self.max_mp)
        f.addRow(self.tr("Largest image file (MB)"), self.max_mb)
        f.addRow(self.tr("Shift check counts for (hours, 0 off)"), self.shift_hours)
        f.addRow(self.tr("Language"), self.lang)
        f.addRow(button(self.tr("Save Settings"), "primary", self.save))
        self.sweep = QLabel()  # the last retention sweep and the policy it deletes under (REQ-LOG-010, D20)
        self.sweep.setObjectName("muted")
        self.sweep.setWordWrap(True)
        left = QVBoxLayout()
        left.addWidget(g)
        left.addWidget(self.sweep)  # under the group: a wrapped label in a form row is cut to one row's height
        tools = QHBoxLayout()
        tools.addWidget(button(self.tr("Confirm Retention Policy"), slot=self.confirm_retention))
        self.bundle = button(self.tr("Support Bundle…"), slot=self.support_bundle)  # REQ-LOG-007, an Admin's
        tools.addWidget(self.bundle)
        tools.addStretch(1)
        left.addLayout(tools)
        self.with_images = size_class(QCheckBox(self.tr("Support bundle with board images")), "T")
        left.addWidget(self.with_images)
        self.stores = StoresPanel(self)  # the customers' encrypted dataset stores (REQ-TRN-017), under System
        left.addWidget(self.stores, 1)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        self.demo = DemoPanel(self)  # load, play, reset and leave the demo workspace (REQ-SET-007, REQ-SET-009)
        right.addWidget(self.demo)
        pg = QGroupBox(self.tr("Presenter theme"))  # the settings-demo sketch's group (REQ-SET-008)
        pl = QVBoxLayout(pg)
        self.presenter = size_class(QCheckBox(self.tr("Presenter theme")), "T")
        self.presenter.clicked.connect(self._switch_presenter)
        about = QLabel(
            self.tr(
                "Full screen and light, text 18 pt or more, verdict 48 pt; where the app has under 900 px of height or"
                " 1400 px of width, as on a 1366 × 768 projector, text 16 pt and verdict 44 pt. 3D Profile and the"
                " hardware table are hidden; Settings is hidden too, except for an Admin, who keeps it for Reset Demo."
                " An Admin leaves the theme with Exit presenter theme in the header."
            )
        )
        about.setObjectName("muted")
        about.setWordWrap(True)
        pl.addWidget(self.presenter)
        pl.addWidget(about)
        right.addWidget(pg)
        ug = QGroupBox(self.tr("Users & roles").replace("&", "&&"))  # a lone & would be a mnemonic, not shown
        ul = QVBoxLayout(ug)
        self.users = make_table([self.tr("Name"), self.tr("Role"), self.tr("Status")])
        ul.addWidget(self.users)
        row = QHBoxLayout()
        row.addWidget(button(self.tr("Add / Change User"), slot=self.add_user))
        self.btn_unlock = button(self.tr("Unlock User"), slot=self.unlock_user)
        row.addWidget(self.btn_unlock)
        ul.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button(self.tr("Disable / Enable"), slot=self.toggle_user))
        row.addWidget(button(self.tr("Reset Password"), slot=self.reset_secret))
        ul.addLayout(row)
        right.addWidget(ug, 1)
        self.hardware = QGroupBox(self.tr("Hardware interfaces"))
        hl = QVBoxLayout(self.hardware)
        self.hw = make_table([self.tr("Interface"), self.tr("Stage"), self.tr("Status")])
        hl.addWidget(self.hw)
        right.addWidget(self.hardware, 1)
        body.addLayout(right, 1)
        self.root.addLayout(body, 1)
        self.restyle()

    def restyle(self) -> None:
        """The presenter theme leaves out the hardware table, whose Stage 2 to 4 rows read "Not connected": a demo shows
        only what is finished (Customers & Launch, "Demos"; A4 of the 2026-10 business-readiness brief). Its 16 and
        18 pt labels leave a field beside them a few letters, so there each field goes under its label. The tick shows
        the theme now in use, also after Exit presenter theme in the header."""
        self.presenter.setChecked(self.ctx.settings.presenter_theme)
        self.hardware.setVisible(not theme.presenter())
        wrap = QFormLayout.RowWrapPolicy
        self.form.setRowWrapPolicy(wrap.WrapAllRows if theme.presenter() else wrap.DontWrapRows)

    def _folder_row(self, value: str, title: str) -> tuple[QLineEdit, QWidget]:
        """A folder's box with its Browse…: the line's input or output folder, a full path or empty for none."""
        box, row = QLineEdit(value), QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(box)

        def browse() -> None:
            if d := QFileDialog.getExistingDirectory(self, title, box.text()):
                box.setText(d)

        rl.addWidget(button(self.tr("Browse…"), slot=browse))
        return box, row

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.tr("Workspace folder"), self.ws.text())
        if d:
            self.ws.setText(d)

    def save(self) -> None:
        """Write the page's own settings over settings.json as it is now, so a hand edit of another key stays (#170),
        through `AppContext.save_settings`: an Admin's write, role-checked and audited (#197). Each value is checked
        first (AOI-SET-008: an empty or relative workspace), and nothing is written on a refusal. The running app
        follows the device, defaults and retention at once (#201) and the workspace and the language from the restart
        (REQ-SET-001, REQ-SET-006: `aoi/ui/language.py` loads the language before the first window)."""
        values = {
            "workspace": self.ws.text(),
            "device": self.device.currentText(),
            "image_size": int(self.input_size.currentText()),
            "default_epochs": self.epochs.value(),
            "log_retention_days": self.ret.value(),
            "language": self.lang.currentData(),
            "ok_evidence": self.ok_evidence.currentData(),
            "input_folder": self.input_folder.text().strip(),  # empty: no line; a relative one is AOI-SET-008
            "output_folder": self.output_folder.text().strip(),
        }
        s = self.ctx.settings
        limits = {"map_retention_days_ok": self.map_ret, "max_image_megapixels": self.max_mp}
        limits["max_image_megabytes"] = self.max_mb
        limits["shift_check_hours"] = self.shift_hours
        # only a limit changed here is written, so a hand edit of settings.json made while the app runs stays (#170)
        values |= {name: box.value() for name, box in limits.items() if box.value() != getattr(s, name)}
        language_before = self.ctx.settings.language
        try:
            self.ctx.save_settings(values)
        except (AoiError, OSError) as e:  # AOI-USR-001 below the Admin role, AOI-SET-008, AOI-SET-010, a disk error
            self.error(e)
            return
        moved = self.ctx.settings.workspace != values["workspace"]
        saved = self.tr("Saved. Restart the app to switch the workspace.") if moved else self.tr("Saved.")
        if values["language"] != language_before:  # every screen reads its texts as it is built (REQ-SET-006)
            saved = self.tr("Saved. Restart the app to change the language.")
        QMessageBox.information(self, self.tr("Settings"), saved)

    def show_sweep(self) -> None:
        """The last retention sweep, and whether an Admin confirmed the policy its deleting steps act under (D20)."""
        last, confirmed = self.ctx.last_sweep, self.ctx.retention_confirmed()
        if last is None:
            swept = self.tr("No retention sweep yet.")
        else:
            n = sum(v for k, v in last.items() if k not in ("time", "skipped"))
            swept = self.tr("Last retention sweep: {time}, {n} items.").format(time=to_local(last["time"]), n=n)
        if confirmed is None:
            policy = self.tr("Policy not confirmed: only OK maps are deleted; logs are gzipped and archived.")
        else:
            policy = self.tr(
                "Policy confirmed {time}: logs go after {days} days, backups but the last {kept}, test-run overlays and"
                " OK files no record names."
            ).format(time=to_local(confirmed["at_utc"]), days=retention.LOG_DELETE_DAYS, kept=retention.BACKUPS_KEPT)
        self.sweep.setText(" ".join((swept, policy)))

    def confirm_retention(self) -> None:
        """An Admin confirms the retention policy, audited (`AppContext.confirm_retention`), after a question."""
        ask = self.tr(
            "From now on the hourly sweep deletes log files after {logs} days, migration backups but the newest {kept},"
            " validation runs' overlays after {days} days and OK boards' files no record names. Confirm?"
        ).format(logs=retention.LOG_DELETE_DAYS, kept=retention.BACKUPS_KEPT, days=self.ctx.settings.test_run_days)
        yes = QMessageBox.StandardButton.Yes
        if QMessageBox.question(self, self.tr("Confirm Retention Policy"), ask) != yes:
            return
        try:
            self.ctx.confirm_retention()
        except AoiError as e:  # AOI-USR-001 below the Admin role
            self.error(e)
            return
        self.show_sweep()

    def support_bundle(self) -> None:
        """The support bundle written where the Admin chooses, on a pool thread (`AppContext.support_bundle`)."""
        name = f"support-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.zip"
        start = self.ctx.usb_drive() or self.ctx.settings.exports_dir
        f, _ = QFileDialog.getSaveFileName(self, self.tr("Support Bundle"), str(start / name), self.tr("Zip (*.zip)"))
        if f:
            done = self.tr("Support bundle written: {file}").format(file=f)
            self.run_in_background(
                self.ctx.support_bundle, f, self.with_images.isChecked(), on_result=lambda _: self.shell.status(done)
            )

    def _switch_presenter(self, on: bool) -> None:
        """The tick saves and applies the presenter theme at once (MainWindow.save_presenter_theme); on a refusal it
        goes back to what is in effect."""
        if not self.shell.save_presenter_theme(on):
            self.presenter.setChecked(self.ctx.settings.presenter_theme)

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

    def unlock_user(self) -> None:
        """An Admin ends a lock before its time (REQ-USR-004): pick one of the locked users."""
        locked = [str(u["name"]) for u in self.ctx.users() if u["locked_minutes"]]
        name, ok = QInputDialog.getItem(self, self.tr("Unlock User"), self.tr("User"), locked, 0, False)
        if ok and name:
            try:
                self.ctx.unlock_user(name)
            except AoiError as e:
                self.error(e)
            self.on_show()

    def _pick_user(self, title: str, ask: str) -> dict[str, Any] | None:
        """Pick a user, each shown with their status, then a question with No as its default; the row picked."""
        users = self.ctx.users()
        shown = [self.tr("{user} ({status})").format(user=u["name"], status=self.status_text(u)) for u in users]
        picked, ok = QInputDialog.getItem(self, title, self.tr("User"), shown, 0, False)
        if not ok or picked not in shown:
            return None
        user = users[shown.index(picked)]
        no = QMessageBox.StandardButton.No
        asked = QMessageBox.question(
            self, title, ask.format(user=user["name"]), QMessageBox.StandardButton.Yes | no, no
        )
        return user if asked == QMessageBox.StandardButton.Yes else None

    def toggle_user(self) -> None:
        """Disable a user, or enable a disabled one again (REQ-USR-006); audited, the last Admin kept."""
        ask = self.tr("Disable {user}, or enable them again if they are disabled?")
        if (user := self._pick_user(self.tr("Disable / Enable User"), ask)) is None:
            return
        try:
            self.ctx.set_user_enabled(str(user["name"]), user["status"] == "disabled")
        except AoiError as e:
            self.error(e)
        self.on_show()

    def reset_secret(self) -> None:
        """Drop a user's password or PIN: they choose a new one at their next sign-in, with an Admin signed in."""
        ask = self.tr("Drop {user}'s password or PIN? They choose a new one at their next sign-in.")
        if (user := self._pick_user(self.tr("Reset Password or PIN"), ask)) is None:
            return
        name = str(user["name"])
        try:
            self.ctx.reset_secret(name)
        except AoiError as e:
            self.error(e)
            return
        self.on_show()
        self.shell.status(self.tr("{user} chooses a new password or PIN at their next sign-in.").format(user=name))

    def status_text(self, user: dict[str, Any]) -> str:
        if minutes := user["locked_minutes"]:
            if minutes > 60 * 24 * 365:  # passwords.FOR_GOOD: until an Admin unlocks it
                return self.tr("Locked until unlocked")
            return self.tr("Locked, {minutes} min").format(minutes=minutes)
        statuses = {"setup": self.tr("No password yet"), "disabled": self.tr("Disabled")}
        return statuses.get(str(user["status"]), self.tr("Active"))

    def idle(self) -> bool:
        """No move or shred of a dataset store runs: the panel's steps wait for it."""
        return self._bg is None

    def update_actions(self) -> None:
        self.stores.sync()
        self.role_gate(self.bundle, "support_bundle", self._bg is None)

    def on_user_changed(self) -> None:
        self.stores.close_sheet()  # a key half typed never stays for the next user
        self.stores.advanced.setChecked(False)  # nor the advanced steps shown for the last

    def on_show(self) -> None:
        self.presenter.setChecked(self.ctx.settings.presenter_theme)
        users = self.ctx.users()
        fill_table(self.users, [[u["name"], role_text(u["role"]), self.status_text(u)] for u in users])
        self.btn_unlock.setEnabled(any(u["locked_minutes"] for u in users))
        self.stores.refresh()
        self.show_sweep()
        fill_table(self.hw, [[self.tr(cell) for cell in row] for row in HARDWARE])
