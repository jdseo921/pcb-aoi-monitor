"""Application shell: header (board model + user), sidebar navigation, page stack."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QCloseEvent, QColor
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
    QMessageBox,
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
from .pages.base import QT_TRANSLATE_NOOP, Page, button, page_text, role_text, size_class
from .pages.compare import ComparePage
from .pages.inspection import InspectionPage
from .pages.logs import LogsPage
from .pages.model_test import ModelTestPage
from .pages.profile3d import Profile3DPage
from .pages.recipe_editor import RecipeEditorPage
from .pages.settings import SettingsPage
from .pages.training import TrainingPage
from .widgets.empty_state import EmptyState

if TYPE_CHECKING:
    from ..core.inspector import InspectionResult


class HomePage(Page):
    """Workflow hub: the Stage 1 path as numbered steps with live status."""

    title = QT_TRANSLATE_NOOP("Page", "Home")
    subtitle = QT_TRANSLATE_NOOP("Page", "Stage 1 workflow: upload → train → validate → inspect")

    STEPS = [
        # (step, name, what it does, page); the name is also the key of its status label. Words from the Charter list.
        (
            "1",
            QT_TRANSLATE_NOOP("HomePage", "Upload samples"),
            QT_TRANSLATE_NOOP("HomePage", "Add good (OK) and defective (NG) photos of this board model."),
            "Training",
        ),
        (
            "2",
            QT_TRANSLATE_NOOP("HomePage", "Self-train"),
            QT_TRANSLATE_NOOP("HomePage", "The app learns the Golden board and an AI model from your OK boards."),
            "Training",
        ),
        (
            "3",
            QT_TRANSLATE_NOOP("HomePage", "Tune recipe"),
            QT_TRANSLATE_NOOP("HomePage", "Draw ROIs and adjust thresholds on the Golden board."),
            "Recipe Editor",
        ),
        (
            "4",
            QT_TRANSLATE_NOOP("HomePage", "Validate"),
            QT_TRANSLATE_NOOP(
                "HomePage", "Validate the AI model on a labelled folder; check accuracy, recall and false calls."
            ),
            "AI Model Test",
        ),
        (
            "5",
            QT_TRANSLATE_NOOP("HomePage", "Inspect"),
            QT_TRANSLATE_NOOP("HomePage", "Run boards; open Compare to see why any board was called NG."),
            "Inspection",
        ),
        (
            "6",
            QT_TRANSLATE_NOOP("HomePage", "Export"),
            QT_TRANSLATE_NOOP("HomePage", "CSV, overlay images and PDF reports for the customer."),
            "Logs & Export",
        ),
    ]

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        self.cards = QWidget()
        grid = QGridLayout(self.cards)
        grid.setSpacing(theme.SPACE)
        self.status_labels: dict[str, QLabel] = {}
        for i, (n, name, desc, target) in enumerate(self.STEPS):
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            h = QLabel(
                f"<span style='font-size:{theme.FONT_STEP_PT}pt;font-weight:700;color:{theme.ACCENT}'>{n}</span>"
                f"&nbsp;&nbsp;<span style='font-size:{theme.FONT_LARGE_PT}pt;font-weight:600'>{self.tr(name)}</span>"
            )
            d = QLabel(self.tr(desc))
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
            link = self.tr("Open {page} ›").format(page=page_text(target))
            cl.addWidget(button(link, kind, lambda _=False, t=target: shell.navigate(t)))
            grid.addWidget(card, i // 3, i % 3)
        self.root.addWidget(self.cards)
        self.empty = EmptyState()  # no board model yet: one block in place of the cards (REQ-SET-019)
        self.root.addWidget(self.empty)
        self.root.addStretch(1)

    def on_show(self) -> None:
        bm = self.board_model
        self.cards.setVisible(bool(bm))
        if not bm:
            if self.ctx.role == "Operator":
                self.empty.show_state(self.tr("No board model yet"), self.tr("Ask an Engineer to create one."))
            else:
                self.empty.show_state(
                    self.tr("No board model yet"),
                    self.tr("Create one to begin."),
                    self.tr("+ New board model"),
                    self.shell.new_board_model,
                )
            return
        self.empty.hide()
        st = self.ctx.board_status(bm)
        tm = st.last_test
        self.status_labels["Upload samples"].setText(
            self.tr("{ok} OK · {ng} NG uploaded").format(ok=st.ok_samples, ng=st.ng_samples)
            if st.ok_samples or st.ng_samples
            else self.tr("No samples yet. Add at least 20 OK boards.")
        )
        self.status_labels["Self-train"].setText(
            self.tr("Active AI model {version}").format(version=st.model_version)
            if st.model_version
            else self.tr("No AI model yet. Train one from your OK boards.")
        )
        self.status_labels["Tune recipe"].setText(
            self.tr("Recipe revision {revision}").format(revision=st.recipe_revision)
            if st.recipe_revision and not st.recipe_is_default
            else self.tr("Recipe uses defaults. Draw ROIs on the Golden board.")
        )
        self.status_labels["Validate"].setText(
            self.tr(
                "Last validation: accuracy {accuracy:.0%}, recall {recall:.0%}, false calls {false_calls:.0%}"
            ).format(accuracy=tm["accuracy"], recall=tm["recall"], false_calls=tm["false_call_rate"])
            if tm
            else self.tr("Not validated yet. Run a labelled folder on AI Model Test.")
        )
        self.status_labels["Inspect"].setText(
            self.tr("{count} boards inspected · {ng} NG").format(count=st.inspected, ng=st.ng)
            if st.inspected
            else self.tr("No boards inspected yet. Load images on Inspection.")
        )
        self.status_labels["Export"].setText(
            self.tr("Ready") if st.inspected else self.tr("Nothing to export yet. Inspect a board first.")
        )


# Sidebar: (section, page class). Order = navigation order.
NAV = [
    ("", HomePage),
    (QT_TRANSLATE_NOOP("MainWindow", "PRODUCTION"), InspectionPage),
    ("", ComparePage),
    (QT_TRANSLATE_NOOP("MainWindow", "ENGINEERING"), TrainingPage),
    ("", ModelTestPage),
    ("", RecipeEditorPage),
    ("", Profile3DPage),
    (QT_TRANSLATE_NOOP("MainWindow", "DATA"), LogsPage),
    (QT_TRANSLATE_NOOP("MainWindow", "SYSTEM"), SettingsPage),
]


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.board_model: str | None = None
        self.last_inspected: tuple[str, InspectionResult, int | None] | None = None  # path, result, record id
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
                sec = QListWidgetItem(self.tr(section))
                sec.setFlags(Qt.ItemFlag.NoItemFlags)
                sec.setForeground(QColor(theme.TEXT_MUTED))
                self.nav.addItem(sec)
            page = cls(ctx, self)
            self.pages[cls.title] = page
            self.stack.addWidget(page)
            it = QListWidgetItem(page_text(cls.title))
            it.setData(Qt.ItemDataRole.UserRole, cls.title)
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
        layout.addWidget(QLabel(self.tr("Board model:")))
        self.bm_combo = QComboBox()
        self.bm_combo.setMinimumWidth(theme.FIELD_W)
        self.bm_combo.currentTextChanged.connect(self._on_board_model)
        layout.addWidget(self.bm_combo)
        new = button(self.tr("+ New"), slot=self.new_board_model)
        layout.addWidget(new)
        layout.addStretch(1)
        self.user_label = QLabel("")
        layout.addWidget(self.user_label)
        switch = button(self.tr("Switch User"), slot=self.switch_user)
        layout.addWidget(switch)
        for control in (self.bm_combo, new, switch):
            size_class(control, "T")  # header controls are operator targets (frame sketch, size class T)
        return h

    def _reload_board_models(self, select: str | None = None) -> None:
        self.bm_combo.blockSignals(True)
        self.bm_combo.clear()
        self.bm_combo.addItems(self.ctx.board_models())
        self.bm_combo.blockSignals(False)
        if select:
            self.bm_combo.setCurrentText(select)
        self._on_board_model(self.bm_combo.currentText())

    def new_board_model(self) -> None:
        name, ok = QInputDialog.getText(
            self, self.tr("New board model"), self.tr("Board model name (e.g. TBOX-A1 Rev2)")
        )
        if ok and name.strip():
            try:
                self.ctx.ensure_board_model(name.strip())
            except AoiError as e:  # the service layer refuses an Operator; the dialog names the role it needs
                show_error(self, self.ctx.report_error(e, "Board model"))
                return
            self._reload_board_models(name.strip())

    def _on_board_model(self, name: str) -> None:
        self.board_model = name or None
        for p in self.pages.values():
            p.on_board_model_changed(self.board_model)
        cur = self.stack.currentWidget()
        if isinstance(cur, Page):
            cur.on_show()

    # --- users / roles (spec 8) -------------------------------------------------------
    def switch_user(self) -> None:
        users = self.ctx.users()
        names = [self.tr("{user} ({role})").format(user=u["name"], role=role_text(u["role"])) for u in users]
        sel, ok = QInputDialog.getItem(self, self.tr("Switch user"), self.tr("User"), names, 0, False)
        if ok:
            u = users[names.index(sel)]
            self.set_role(u["role"], u["name"])

    def set_role(self, role: str, user: str) -> None:
        self.ctx.set_user(user, role)
        self.user_label.setText(self.tr("{user}  ·  {role}").format(user=user, role=role_text(role)))
        for title, it in self._items.items():
            allowed = role in self.pages[title].roles
            it.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if allowed else Qt.ItemFlag.NoItemFlags
            )
            it.setToolTip("" if allowed else self._needs_role(title))
        cur = self.stack.currentWidget()
        if isinstance(cur, Page) and role not in cur.roles:
            self.navigate("Home")

    def _needs_role(self, title: str) -> str:
        """One sentence naming the page and the roles that may open it, for the tooltip and the status bar."""
        roles = " / ".join(role_text(r) for r in self.pages[title].roles)
        return self.tr("{page} needs the {roles} role").format(page=page_text(title), roles=roles)

    # --- navigation -----------------------------------------------------------------
    def navigate(self, title: str) -> bool:
        it = self._items.get(title)
        if it and it.flags() & Qt.ItemFlag.ItemIsEnabled:
            self.nav.setCurrentItem(it)
            return True
        if title in self.pages:
            self.status(self._needs_role(title))
        return False

    def _on_nav(self, cur: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if cur is None or not cur.data(Qt.ItemDataRole.UserRole):
            return
        page = self.pages[cur.data(Qt.ItemDataRole.UserRole)]
        self.stack.setCurrentWidget(page)
        page.on_show()
        if self.ctx.settings.last_page != page.title:
            self.ctx.settings.last_page = page.title
            try:  # that key alone, over the file as it is now: a hand edit made while the app runs stays (#170)
                self.ctx.settings.save_keys({"last_page": page.title})
            except (OSError, AoiError):  # a file that cannot be written, or read (AOI-SET-010): left as it is
                self.ctx.log.warning("settings.save_failed", exc_info=True)

    def open_compare(self, path: str) -> None:
        self.navigate("Compare")
        cast(ComparePage, self.pages["Compare"]).set_test(path)

    def open_stored(self, inspection_id: int) -> None:
        """Compare on a stored result in one click, as it was decided (REQ-INSP-009)."""
        self.navigate("Compare")
        cast(ComparePage, self.pages["Compare"]).show_stored(inspection_id)

    def status(self, msg: str, ms: int = 8000) -> None:
        """A message in the status bar, for 8 s by default; `ms=0` keeps it until the next message replaces it."""
        self.statusBar().showMessage(msg, ms)

    # --- closing (#171) -------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        """Closing the window stops the background work and closes the context; while work runs it asks first, and No
        keeps the window open. A stopped training run saves nothing (REQ-TRN-008)."""
        if not self.ctx.jobs.idle():
            yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
            question = self.tr(
                "Work is still running: training, an AI model test or an inspection. Stop it and close the app? "
                "Training stops without saving an AI model, so the active one stays; an AI model test finishes its "
                "folder first."
            )
            if QMessageBox.question(self, self.tr("Stop the running work?"), question, yes | no, no) != yes:
                event.ignore()
                return
            self.status(self.tr("Stopping the running work…"), ms=0)
            self.statusBar().repaint()  # the wait below holds the UI thread until each job has stopped
        self.ctx.close()  # every job asked to stop and waited for, then the database and the log file closed
        # Slots the jobs queued before they stopped would meet the closed context: drop them (None: every receiver).
        QCoreApplication.removePostedEvents(None, QEvent.Type.MetaCall)  # type: ignore[arg-type]
        event.accept()
