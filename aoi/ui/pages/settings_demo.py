"""Settings › Demo (REQ-SET-007, REQ-SET-009; S53; sketch settings-demo.md): load the demo workspace in one click, play
its scripted run at a pace of 1 to 10 s per board, put it back as the bundle holds it, and leave it. Admin only, as the
page is."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QMessageBox, QSlider, QVBoxLayout

from ...core import demo
from ...errors import AoiError
from .base import button, size_class

if TYPE_CHECKING:
    from .settings import SettingsPage

PACE_MIN, PACE_MAX = 1, 10  # seconds per board (REQ-SET-009); settings.json holds the same range (config._MOST)


class DemoPanel(QGroupBox):
    """Outside the demo: what Load Demo Workspace opens, and the button. In it: the pace, Play Scripted Run ›, Leave
    Demo Workspace and the red Reset Demo, last. Each switch opens the other workspace in a new window
    (`MainWindow.switch_workspace`)."""

    def __init__(self, page: SettingsPage) -> None:
        super().__init__()
        self.setTitle(self.tr("Demo"))
        self.page, self.ctx = page, page.ctx
        root = self.ctx.settings.root
        self.in_demo = demo.is_demo(root)
        lay = QVBoxLayout(self)
        self.state = QLabel()
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        row = QHBoxLayout()
        if not self.in_demo:
            folder = demo.demo_folder(root)
            loaded = demo.is_demo(folder)
            self.state.setText(
                self.tr("Demo workspace: loaded, not open.") if loaded else self.tr("Demo workspace: not loaded.")
            )
            what = QLabel(
                self.tr(
                    "Load Demo Workspace opens the demo board model with its AI model, recipe and 10 boards, one of"
                    " them NG, in a folder of its own beside this workspace, {folder}; production data is not"
                    " touched. The boards are drawn, not photographed: the demo shows how the app works, never how"
                    " well it finds defects."
                ).format(folder=folder.name)
            )
            what.setObjectName("muted")
            what.setWordWrap(True)
            lay.addWidget(what)
            self.btn_load = button(self.tr("Load Demo Workspace"), slot=self._load)
            row.addWidget(self.btn_load)
            row.addStretch(1)
        else:
            self.state.setText(self.tr("Demo workspace: open, in the folder {folder}.").format(folder=root.name))
            pace = QHBoxLayout()
            pace.addWidget(QLabel(self.tr("Scripted run pace")))
            pace.addWidget(QLabel(self.tr("{seconds} s").format(seconds=PACE_MIN)))
            self.pace = size_class(QSlider(Qt.Orientation.Horizontal), "T")
            self.pace.setRange(PACE_MIN, PACE_MAX)
            self.pace.setValue(self.ctx.settings.demo_pace_s)
            self.pace.setTracking(False)  # stored once the knob is let go, or at each arrow key
            self.pace.sliderMoved.connect(self._show_pace)
            self.pace.valueChanged.connect(self._save_pace)
            pace.addWidget(self.pace, 1)
            pace.addWidget(QLabel(self.tr("{seconds} s").format(seconds=PACE_MAX)))
            self.pace_label = QLabel()
            pace.addWidget(self.pace_label)
            self._show_pace(self.pace.value())
            lay.addLayout(pace)
            self.btn_play = button(self.tr("Play Scripted Run ›"), slot=self.page.shell.play_demo)
            self.btn_leave = button(self.tr("Leave Demo Workspace"), slot=self._leave)
            self.btn_reset = button(self.tr("Reset Demo"), "danger", self._reset)  # red, last, never the default
            row.addWidget(self.btn_play)
            row.addWidget(self.btn_leave)
            row.addStretch(1)
            row.addWidget(self.btn_reset)
        lay.addLayout(row)

    def _load(self) -> None:
        """Load the demo beside this workspace, or keep it as it is when it is there, and open it."""
        try:
            folder = demo.load_beside(self.ctx.settings, self.ctx.credentials)
        except AoiError as e:  # AOI-SET-015 for a missing or damaged bundle, AOI-SET-016 for a folder not the demo's
            self.page.error(e)
            return
        self.page.shell.switch_workspace(folder)

    def _leave(self) -> None:
        self.page.shell.switch_workspace(None)

    def _reset(self) -> None:
        """Ask first, naming what goes, then put the demo back as the bundle holds it and open it again."""
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        question = self.tr(
            "Reset the demo workspace? Every result, record, alarm and log of the demo, and every change made in it to"
            " its board model, AI model, recipe and samples, is deleted, and the demo is copied back from the"
            " installed bundle. The production workspace is not touched."
        )
        if QMessageBox.question(self, self.tr("Reset Demo"), question, yes | no, no) == yes:
            self.page.shell.switch_workspace(self.ctx.settings.root, reset=True)

    def _show_pace(self, seconds: int) -> None:
        self.pace_label.setText(self.tr("= {seconds} s per board").format(seconds=seconds))

    def _save_pace(self, seconds: int) -> None:
        """Store the pace in the demo workspace's settings.json, audited as an Admin's change of settings."""
        self._show_pace(seconds)
        try:
            self.ctx.save_settings({"demo_pace_s": seconds})
        except (AoiError, OSError) as e:
            self.page.error(e)
