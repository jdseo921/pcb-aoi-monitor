"""Application shell: header (board model + user), sidebar navigation, page stack."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_NAME, APP_VERSION
from ..core.services import AppContext
from ..errors import AoiError
from . import theme
from .errors import show_error
from .pages.base import Page, button
from .pages.compare import ComparePage
from .pages.inspection import InspectionPage
from .pages.logs import LogsPage
from .pages.model_test import ModelTestPage
from .pages.profile3d import Profile3DPage
from .pages.recipe_editor import RecipeEditorPage
from .pages.settings import SettingsPage
from .pages.training import TrainingPage
from .widgets.empty_state import EmptyState


class HomePage(Page):
    """Workflow hub: the Stage 1 path as numbered steps with live status."""

    title = "Home"
    subtitle = "Stage 1 workflow: upload → train → validate → inspect"

    STEPS = [
        ("1", "Upload samples", "Add good (OK) and defective (NG) photos of this board model.", "Training"),
        ("2", "Self-train", "The app learns the golden template and an anomaly model from your OK boards.", "Training"),
        ("3", "Tune recipe", "Draw ROIs and adjust thresholds on the golden board.", "Recipe Editor"),
        ("4", "Validate", "Run a labelled test folder; check accuracy, recall and false calls.", "AI Model Test"),
        ("5", "Inspect", "Run boards; open Compare to see why any board was called NG.", "Inspection"),
        ("6", "Export", "CSV, overlay images and PDF reports for customer validation.", "Logs & Export"),
    ]

    def __init__(self, ctx, shell):
        super().__init__(ctx, shell)
        self.cards = QWidget()
        grid = QGridLayout(self.cards)
        grid.setSpacing(theme.SPACE)
        self.status_labels = {}
        for i, (n, name, desc, target) in enumerate(self.STEPS):
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            h = QLabel(
                f"<span style='font-size:{theme.FONT_STEP_PT}pt;font-weight:700;color:{theme.ACCENT}'>{n}</span>"
                f"&nbsp;&nbsp;<span style='font-size:{theme.FONT_LARGE_PT}pt;font-weight:600'>{name}</span>"
            )
            d = QLabel(desc)
            d.setWordWrap(True)
            d.setObjectName("muted")
            st = QLabel("")
            st.setWordWrap(True)
            self.status_labels[name] = st
            cl.addWidget(h)
            cl.addWidget(d)
            cl.addStretch(1)
            cl.addWidget(st)
            kind = "primary" if target == "Inspection" else ""  # the page's one blue primary: the Inspect card
            cl.addWidget(button(f"Open {target} ›", kind, lambda _=False, t=target: shell.navigate(t)))
            grid.addWidget(card, i // 3, i % 3)
        self.root.addWidget(self.cards)
        self.empty = EmptyState()  # no board model yet: one block in place of the cards (REQ-SET-019)
        self.root.addWidget(self.empty)
        self.root.addStretch(1)

    def on_show(self):
        bm = self.board_model
        self.cards.setVisible(bool(bm))
        if not bm:
            if self.ctx.role == "Operator":
                self.empty.show_state("No board model yet", "Ask an Engineer to create one.")
            else:
                self.empty.show_state(
                    "No board model yet", "Create one to begin.", "+ New board model", self.shell.new_board_model
                )
            return
        self.empty.hide()
        st = self.ctx.board_status(bm)
        tm = st.last_test
        self.status_labels["Upload samples"].setText(
            f"{st.ok_samples} OK · {st.ng_samples} NG uploaded"
            if st.ok_samples or st.ng_samples
            else "No samples yet. Add at least 20 OK boards."
        )
        self.status_labels["Self-train"].setText(
            f"Active model {st.model_version}"
            if st.model_version
            else "No AI model yet. Train one from your OK boards."
        )
        self.status_labels["Tune recipe"].setText(
            f"Recipe revision {st.recipe_revision}"
            if st.recipe_revision
            else "Recipe uses defaults. Draw ROIs on the Golden board."
        )
        self.status_labels["Validate"].setText(
            f"Last test: accuracy {tm['accuracy']:.0%}, recall {tm['recall']:.0%}, "
            f"false calls {tm['false_call_rate']:.0%}"
            if tm
            else "Not validated yet. Run a labelled test folder."
        )
        self.status_labels["Inspect"].setText(
            f"{st.inspected} boards inspected · {st.ng} NG"
            if st.inspected
            else "No boards inspected yet. Load images on Inspection."
        )
        self.status_labels["Export"].setText(
            "Ready" if st.inspected else "Nothing to export yet. Inspect a board first."
        )


# Sidebar: (section, page class). Order = navigation order.
NAV = [
    ("", HomePage),
    ("PRODUCTION", InspectionPage),
    ("", ComparePage),
    ("ENGINEERING", TrainingPage),
    ("", ModelTestPage),
    ("", RecipeEditorPage),
    ("", Profile3DPage),
    ("DATA", LogsPage),
    ("SYSTEM", SettingsPage),
]


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.board_model: str | None = None
        self.last_inspected = None  # (path, InspectionResult) shared by Inspection -> Compare
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1920, 1080)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._header())
        body = QHBoxLayout()
        body.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(theme.NAV_W)
        self.stack = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self.pages: dict[str, Page] = {}
        self._items: dict[str, QListWidgetItem] = {}
        for section, cls in NAV:
            if section:
                sec = QListWidgetItem(section)
                sec.setFlags(Qt.NoItemFlags)
                sec.setForeground(QColor(theme.TEXT_MUTED))
                self.nav.addItem(sec)
            page = cls(ctx, self)
            self.pages[cls.title] = page
            self.stack.addWidget(page)
            it = QListWidgetItem(cls.title)
            it.setData(Qt.UserRole, cls.title)
            self.nav.addItem(it)
            self._items[cls.title] = it
        self.nav.currentItemChanged.connect(self._on_nav)

        self._reload_board_models()
        first_run = not ctx.board_models()  # no board model yet: start as Admin to set the station up
        self.set_role("Admin" if first_run else "Operator", "admin" if first_run else "operator")
        if not self.navigate(ctx.settings.last_page):  # reopen where the last session was (REQ-LOG-005)
            self.navigate("Home")

    # --- header -------------------------------------------------------------------
    def _header(self) -> QWidget:
        h = QFrame()
        h.setObjectName("header")
        h.setFixedHeight(theme.HEADER_H)
        layout = QHBoxLayout(h)
        layout.setContentsMargins(18, 0, 18, 0)
        logo = QLabel(f"<b>{APP_NAME}</b>")
        logo.setObjectName("logo")
        layout.addWidget(logo)
        layout.addSpacing(30)
        layout.addWidget(QLabel("Board model:"))
        self.bm_combo = QComboBox()
        self.bm_combo.setMinimumWidth(theme.FIELD_W)
        self.bm_combo.currentTextChanged.connect(self._on_board_model)
        layout.addWidget(self.bm_combo)
        layout.addWidget(button("+ New", slot=self.new_board_model))
        layout.addStretch(1)
        self.user_label = QLabel("")
        layout.addWidget(self.user_label)
        layout.addWidget(button("Switch User", slot=self.switch_user))
        return h

    def _reload_board_models(self, select: str | None = None):
        self.bm_combo.blockSignals(True)
        self.bm_combo.clear()
        self.bm_combo.addItems(self.ctx.board_models())
        self.bm_combo.blockSignals(False)
        if select:
            self.bm_combo.setCurrentText(select)
        self._on_board_model(self.bm_combo.currentText())

    def new_board_model(self):
        name, ok = QInputDialog.getText(self, "New board model", "Board model name (e.g. TBOX-A1 Rev2)")
        if ok and name.strip():
            try:
                self.ctx.ensure_board_model(name.strip())
            except AoiError as e:  # the service layer refuses an Operator; the dialog names the role it needs
                return show_error(self, self.ctx.report_error(e, "Board model"))
            self._reload_board_models(name.strip())

    def _on_board_model(self, name: str):
        self.board_model = name or None
        for p in self.pages.values():
            p.on_board_model_changed(self.board_model)
        cur = self.stack.currentWidget()
        if isinstance(cur, Page):
            cur.on_show()

    # --- users / roles (spec 8) -------------------------------------------------------
    def switch_user(self):
        users = self.ctx.users()
        names = [f"{u['name']} ({u['role']})" for u in users]
        sel, ok = QInputDialog.getItem(self, "Switch user", "User", names, 0, False)
        if ok:
            u = users[names.index(sel)]
            self.set_role(u["role"], u["name"])

    def set_role(self, role: str, user: str):
        self.ctx.set_user(user, role)
        self.user_label.setText(f"{user}  ·  {role}")
        for title, it in self._items.items():
            allowed = role in self.pages[title].roles
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable if allowed else Qt.NoItemFlags)
            it.setToolTip("" if allowed else f"Requires: {', '.join(self.pages[title].roles)}")
        cur = self.stack.currentWidget()
        if isinstance(cur, Page) and role not in cur.roles:
            self.navigate("Home")

    # --- navigation -----------------------------------------------------------------
    def navigate(self, title: str) -> bool:
        it = self._items.get(title)
        if it and it.flags() & Qt.ItemIsEnabled:
            self.nav.setCurrentItem(it)
            return True
        if title in self.pages:
            self.status(f"{title} requires role: {', '.join(self.pages[title].roles)}")
        return False

    def _on_nav(self, cur: QListWidgetItem, _prev):
        if cur is None or not cur.data(Qt.UserRole):
            return
        page = self.pages[cur.data(Qt.UserRole)]
        self.stack.setCurrentWidget(page)
        page.on_show()
        if self.ctx.settings.last_page != page.title:
            self.ctx.settings.last_page = page.title
            try:
                self.ctx.settings.save()
            except OSError:
                self.ctx.log.warning("settings.save_failed", exc_info=True)

    def open_compare(self, path: str):
        self.navigate("Compare")
        self.pages["Compare"].set_test(path)

    def status(self, msg: str):
        self.statusBar().showMessage(msg, 8000)
