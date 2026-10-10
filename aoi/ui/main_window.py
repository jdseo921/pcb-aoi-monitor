"""Application shell: header (board model + user), sidebar navigation, page stack."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWidgets import (
    QApplication,
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
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_NAME, APP_VERSION, use_workspace
from ..core import datasets, demo
from ..core.run_progress import RunProgress
from ..core.services import AppContext
from ..errors import AoiError
from . import theme
from .demo_workspace import boards
from .errors import install_excepthook, open_workspace, show_error
from .pages.base import (
    QT_TRANSLATE_NOOP,
    Page,
    button,
    page_text,
    restyle_table,
    role_text,
    scrolled,
    size_class,
    time_left_text,
)
from .pages.compare import ComparePage
from .pages.inspection import InspectionPage
from .pages.logs import LogsPage
from .pages.model_test import ModelTestPage
from .pages.profile3d import Profile3DPage
from .pages.recipe_editor import RecipeEditorPage
from .pages.settings import SettingsPage
from .pages.training import TrainingPage
from .widgets.empty_state import EmptyState
from .widgets.image_view import ImageView
from .workers import drop_queued

# The OK boards a board model needs before it trains: a locked validation set's and a training set's (REQ-TRN-007).
FIRST_OK = datasets.VALIDATION_OK + datasets.TRAIN_OK

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
            QT_TRANSLATE_NOOP("HomePage", "Train AI model"),
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
            QT_TRANSLATE_NOOP("HomePage", "Test the AI model on the locked validation set."),
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
        self.training_line = QLabel()  # on Train AI model's card while a training run goes on (REQ-TRN-008)
        self.training_line.setWordWrap(True)
        self.training_line.hide()
        self.headings: list[tuple[QLabel, str, str]] = []  # each card's heading, its number and its name
        for i, (n, name, desc, target) in enumerate(self.STEPS):
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            h = QLabel(self._heading(n, name))
            self.headings.append((h, n, name))
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
            if name == "Train AI model":
                cl.addWidget(self.training_line)
            kind = "primary" if target == "Inspection" else ""  # the page's one blue primary: the Inspect card
            link = self.tr("Open {page} ›").format(page=page_text(target))
            cl.addWidget(button(link, kind, lambda _=False, t=target: shell.navigate(t)))
            grid.addWidget(card, i // 3, i % 3)
        self.root.addWidget(self.cards)
        self.empty = EmptyState()  # no board model yet: one block in place of the cards (REQ-SET-019)
        self.root.addWidget(self.empty)
        self.root.addStretch(1)

    def _heading(self, n: str, name: str) -> str:
        """A card's heading: its step number, large in the accent colour, then its name."""
        return (
            f"<span style='font-size:{theme.FONT_STEP_PT}pt;font-weight:700;color:{theme.ACCENT_TEXT}'>{n}</span>"
            f"&nbsp;&nbsp;<span style='font-size:{theme.FONT_LARGE_PT}pt;font-weight:600'>{self.tr(name)}</span>"
        )

    def restyle(self) -> None:
        for h, n, name in self.headings:
            h.setText(self._heading(n, name))

    def show_training(self, progress: RunProgress | None, running: bool) -> None:
        """Train AI model's line while a training run goes on, with its latest report; hidden once it ends."""
        if running:
            percent, left = (progress.percent, progress.left_s) if progress else (0, None)
            line = self.tr("Training running {percent} % · {left}")
            self.training_line.setText(line.format(percent=percent, left=time_left_text(left)))
        self.training_line.setVisible(running)

    def on_show(self) -> None:
        bm = self.board_model
        self.cards.setVisible(bool(bm))
        if not bm:
            self.empty.show_state(*self.no_board_model())
            return
        self.empty.hide()
        st = self.ctx.board_status(bm)
        tm = st.last_test
        self.status_labels["Upload samples"].setText(
            self.tr("{ok} OK · {ng} NG uploaded").format(ok=st.ok_samples, ng=st.ng_samples)
            if st.ok_samples or st.ng_samples
            else self.tr("No samples yet. Add at least {count} OK boards.").format(count=FIRST_OK)
        )
        self.status_labels["Train AI model"].setText(
            self.tr("Active AI model {version}").format(version=st.model_version)
            if st.model_version
            else self.tr("No AI model yet. Train one from your OK boards.")
        )
        self.status_labels["Tune recipe"].setText(
            self.tr("Recipe revision {revision}").format(revision=st.recipe_revision)
            if st.recipe_revision and not st.recipe_is_default
            else self.tr("Recipe uses defaults. Draw ROIs on the Golden board.")
        )
        self.status_labels["Validate"].setText(  # counts, never a bare percent (Customers & Launch, Validation)
            self.tr("Missed defects {missed} of {ng} · False calls {false_calls} of {ok}").format(
                missed=tm["FN"], ng=tm["TP"] + tm["FN"], false_calls=tm["FP"], ok=tm["FP"] + tm["TN"]
            )
            if tm
            else self.tr("Not validated yet. Run the locked validation set.")
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


class _PageStack(QStackedWidget):
    """The pages, sized for the one shown (#104): a QStackedWidget asks for the largest minimum of all its pages, so in
    the scroll area round it every page would scroll as far as the tallest or widest one (Settings, say) needs. Here
    the stack asks for the page shown, and asks again when another is shown."""

    def __init__(self) -> None:
        super().__init__()
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        page = self.currentWidget()
        return page.minimumSizeHint().expandedTo(page.minimumSize()) if page is not None else super().minimumSizeHint()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.board_model: str | None = None
        self.last_inspected: tuple[str, InspectionResult, int | None] | None = None  # path, result, record id
        self.in_demo = demo.is_demo(ctx.settings.root)  # the demo workspace is open (REQ-SET-007)
        self.switched = False  # closed by switch_workspace, which stopped the work and closed the context already
        title = f"{APP_NAME} {APP_VERSION}"
        self.setWindowTitle(self.tr("{title} · Demo").format(title=title) if self.in_demo else title)
        self.resize(1920, 1080)
        if ctx.settings.presenter_theme != theme.presenter():  # start in the theme saved, before anything is drawn
            self._set_theme(ctx.settings.presenter_theme)

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
        self.stack = _PageStack()
        body.addWidget(self.nav)
        # the pages scroll where the screen is smaller than the widest page, so a 1366 x 768 station shows every
        # control (REQ-SET-004, #104): a QStackedWidget takes the largest minimum of its pages, which held the
        # window at about 1886 x 821 px; at 1920 x 1080 every page fits and nothing scrolls
        self.stack.setObjectName("stack")
        pages = scrolled(self.stack)
        pages.setObjectName("pages")  # on the window's background, BG, as the stack was before (theme.py)
        pages.setMinimumSize(0, 0)
        body.addWidget(pages, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self.pages: dict[str, Page] = {}
        self._items: dict[str, QListWidgetItem] = {}
        self._badges: dict[str, QLabel] = {}
        self._sections: list[tuple[QListWidgetItem, list[str]]] = []  # each heading and the pages under it
        for section, cls in NAV:
            if section:
                sec = QListWidgetItem(self.tr(section))
                sec.setFlags(Qt.ItemFlag.NoItemFlags)
                self.nav.addItem(sec)
                self._sections.append((sec, []))
            if self._sections:
                self._sections[-1][1].append(cls.title)
            page = cls(ctx, self)
            self.pages[cls.title] = page
            self.stack.addWidget(page)
            it = QListWidgetItem(page_text(cls.title))
            it.setData(Qt.ItemDataRole.UserRole, cls.title)
            self.nav.addItem(it)
            self._items[cls.title] = it
            if cls.badge:
                self._badges[cls.title] = self._badge(it, cls.badge, cls.badge_tip)
        self.nav.currentItemChanged.connect(self._on_nav)

        self._training_timer = QTimer(self)  # the header and Home follow a training run on every page (REQ-TRN-008)
        self._training_timer.timeout.connect(self.show_training)
        self._training_timer.start(1000)
        self._reload_board_models()
        # no board model yet: start with an Admin to set the station up; the role is the stored one either way (#197)
        self.set_user(ctx.start_user(setting_up=not ctx.board_models()))
        if self.in_demo:  # its boards wait on Inspection as a scripted run at the demo's pace (REQ-SET-009)
            cast(InspectionPage, self.pages["Inspection"]).play(
                boards(ctx.settings.root), ctx.settings.demo_pace_s, False
            )
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
        self.demo_badge = QLabel(self.tr("Demo"))  # on every page while the demo workspace is open (settings sketch)
        self.demo_badge.setObjectName("badge")
        self.demo_badge.setVisible(self.in_demo)
        layout.addWidget(self.demo_badge)
        layout.addSpacing(30)
        layout.addWidget(QLabel(self.tr("Board model:")))
        self.bm_combo = QComboBox()
        self.bm_combo.setMinimumWidth(theme.FIELD_W)
        self.bm_combo.currentTextChanged.connect(self._on_board_model)
        layout.addWidget(self.bm_combo)
        new = button(self.tr("+ New"), slot=self.new_board_model)
        layout.addWidget(new)
        layout.addStretch(1)
        self.training_link = button("", slot=lambda: self.navigate("Training"))  # while a training run goes on
        self.training_link.hide()
        layout.addWidget(self.training_link)
        self.exit_presenter = button(self.tr("Exit presenter theme"), slot=lambda: self.save_presenter_theme(False))
        self.exit_presenter.hide()  # shown in the presenter theme, to an Admin (_sync_nav)
        layout.addWidget(self.exit_presenter)
        self.user_label = QLabel("")
        layout.addWidget(self.user_label)
        switch = button(self.tr("Switch User"), slot=self.switch_user)
        layout.addWidget(switch)
        for control in (self.bm_combo, new, self.training_link, self.exit_presenter, switch):
            size_class(control, "T")  # header controls are operator targets (frame sketch, size class T)
        return h

    def show_training(self) -> None:
        """The header's training indicator and Home's line, read each second from the context's run, whichever page
        started it: shown while it goes on, with its percent and time left; a click opens Training (REQ-TRN-008)."""
        job, progress = self.ctx.training, self.ctx.training_progress
        running = job is not None and not job.done
        if running:
            percent, left = (progress.percent, progress.left_s) if progress else (0, None)
            text = self.tr("Training {percent} % · {left}").format(percent=percent, left=time_left_text(left))
            self.training_link.setText(text)
        self.training_link.setVisible(running)
        cast(HomePage, self.pages["Home"]).show_training(progress, running)

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
            if name.strip() == self.board_model:  # nothing changes: no page drops what it shows or judges again (#247)
                self.status(self.tr("Board model {name} is already selected.").format(name=name.strip()))
                return
            self._reload_board_models(name.strip())

    def _on_board_model(self, name: str) -> None:
        if (name or None) != self.board_model:  # the board inspected last was another board model's: Use Last
            self.last_inspected = None  # Inspected never opens it as one of this board model (#172)
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
            self.set_user(users[names.index(sel)]["name"])

    def set_user(self, user: str) -> None:
        """Sign `user` in with the role the users table holds for them (#197); the header and the pages follow it."""
        self.ctx.set_user(user)
        role = self.ctx.role
        self.user_label.setText(self.tr("{user}  ·  {role}").format(user=user, role=role_text(role)))
        self._sync_nav()
        for page in self.pages.values():  # shown or not: what a page keeps for the role before goes now
            page.on_user_changed()
        cur = self.stack.currentWidget()
        if isinstance(cur, Page) and role not in cur.roles:
            self.navigate("Home")
        elif isinstance(cur, Page) and self.nav.currentItem() is not None:  # none yet while the window is built
            cur.on_show()  # the page stays: its role-gated buttons and links follow the new role (#174)

    def _sync_nav(self) -> None:
        """The sidebar and the header for the role and the theme. An entry the role may not open is greyed, its tooltip
        naming the roles that may, and its badge hidden. In the presenter theme the Admin pages and 3D Profile leave the
        sidebar, with a heading left over none, and Exit presenter theme shows to an Admin only (REQ-SET-008, Q49)."""
        role = self.ctx.role
        for title, it in self._items.items():
            allowed = role in self.pages[title].roles
            it.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if allowed else Qt.ItemFlag.NoItemFlags
            )
            it.setToolTip(page_text(self.pages[title].badge_tip) if allowed else self._needs_role(title))
            # greyed as a disabled control here, not by a stylesheet rule for disabled items: that rule would grey
            # the section headings too, which have no flags either (#239)
            it.setData(Qt.ItemDataRole.ForegroundRole, None if allowed else QColor(theme.TEXT_DISABLED))
            if title in self._badges:  # a greyed entry says only which role it needs; the badge, not its row: Qt
                self._badges[title].setVisible(allowed)  # shows a row again on every layout of the list
            it.setHidden(self.hidden(title))
        for heading, titles in self._sections:
            heading.setForeground(QColor(theme.TEXT_MUTED))  # a heading, not a disabled control: 7.4:1 (#239)
            heading.setHidden(all(self.hidden(t) for t in titles))
        self.exit_presenter.setVisible(theme.presenter() and role in SettingsPage.roles)  # where it was switched on

    def hidden(self, title: str) -> bool:
        """Whether page `title` is out of the sidebar, and cannot be opened: in the presenter theme, a page for the
        Admin alone (Settings) and a page marked not `in_presenter_theme` (3D Profile) (REQ-SET-008)."""
        page = self.pages[title]
        return theme.presenter() and (page.roles == ("Admin",) or not page.in_presenter_theme)

    def _set_theme(self, presenter: bool) -> None:
        theme.use(presenter)
        cast(QApplication, QApplication.instance()).setStyleSheet(theme.stylesheet())

    def apply_theme(self) -> None:
        """The theme settings.json holds, at once (REQ-SET-008): the stylesheet, then what the pages drew with the
        tokens, each in the new theme (verdict labels, coloured table rows, the text on images, each page's own
        `restyle`), the sidebar and the header. The page shown goes to Home when the theme hides it."""
        if self.ctx.settings.presenter_theme != theme.presenter():
            styled = theme.verdict_styles()  # read with the tokens they were drawn with
            self._set_theme(self.ctx.settings.presenter_theme)
            for label in self.findChildren(QLabel):
                if (style := styled.get(label.styleSheet())) is not None:
                    label.setStyleSheet(style())
            for table in self.findChildren(QTableWidget):
                restyle_table(table)
            for view in self.findChildren(ImageView):
                view.restyle()
            for page in self.pages.values():
                page.restyle()
        self._sync_nav()
        cur = self.stack.currentWidget()
        if isinstance(cur, Page) and self.hidden(cur.title):
            self.navigate("Home")

    def save_presenter_theme(self, on: bool) -> bool:
        """Switch the presenter theme on or off, as an Admin does on Settings or with the header's Exit presenter
        theme: saved through the service layer (Admin only, audited as settings.change, Q49), then applied at once. A
        refusal is shown with its code and changes nothing. Returns whether it was saved."""
        try:
            self.ctx.save_settings({"presenter_theme": on})
        except (AoiError, OSError) as e:  # AOI-USR-001 below the Admin role, AOI-SET-010, a disk error
            show_error(self, self.ctx.report_error(e, "Settings"))
            return False
        self.apply_theme()
        if on:
            self.status(self.tr("Presenter theme on. An Admin turns it off with Exit presenter theme."))
        else:
            self.status(self.tr("Presenter theme off."))
        return True

    def _badge(self, it: QListWidgetItem, text: str, tip: str) -> QLabel:
        """A badge after a sidebar entry's name, such as 3D Profile's "Stage 2" (sketch profile3d-card.md), 14 pt in
        amber at the entry's right end; returns the badge. The row holding it lets the pointer through, so a click on
        the entry selects it as on any other, and the entry shows the badge's tooltip."""
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)  # Qt gives it the entry's text line, inside its margin and padding
        layout.addStretch(1)
        badge = QLabel(page_text(text))
        badge.setObjectName("badge")
        badge.setToolTip(page_text(tip))
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.nav.setItemWidget(it, row)
        return badge

    def _needs_role(self, title: str) -> str:
        """One sentence naming the page and the roles that may open it, for the tooltip and the status bar."""
        roles = " / ".join(role_text(r) for r in self.pages[title].roles)
        return self.tr("{page} needs the {roles} role").format(page=page_text(title), roles=roles)

    # --- navigation -----------------------------------------------------------------
    def navigate(self, title: str) -> bool:
        it = self._items.get(title)
        if it and self.hidden(title):
            self.status(self.tr("{page} is hidden in the presenter theme").format(page=page_text(title)))
            return False
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
        compare = cast(ComparePage, self.pages["Compare"])
        compare.judge_on_show = False  # set_test judges `path` next: on_show starts no run of the board before (#247)
        compare.show_golden_pane()  # "Compare with Golden board ›": shown beside the board (#248)
        self.navigate("Compare")
        compare.set_test(path)

    def open_stored(self, inspection_id: int) -> None:
        """Compare on a stored result in one click, as it was decided (REQ-INSP-009)."""
        compare = cast(ComparePage, self.pages["Compare"])
        compare.judge_on_show = False  # the record shows next: on_show starts no run of the board before (#247)
        compare.show_golden_pane()  # lined up with the Golden board it was judged against (#248)
        self.navigate("Compare")
        compare.show_stored(inspection_id)

    def status(self, msg: str, ms: int = 8000) -> None:
        """A message in the status bar, for 8 s by default; `ms=0` keeps it until the next message replaces it."""
        self.statusBar().showMessage(msg, ms)

    # --- closing (#171) -------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        """Closing the window stops the background work and closes the context; while work runs it asks first, and No
        keeps the window open. A stopped training run saves nothing (REQ-TRN-008)."""
        if not self.switched and not self._may_stop_work(self.tr("close the app")):
            event.ignore()
            return
        self.ctx.close()  # every job asked to stop and waited for, then the database and the log file closed
        drop_queued(self.ctx.jobs)  # slots the jobs queued before they stopped would meet the closed context
        event.accept()

    def _may_stop_work(self, then: str) -> bool:
        """True when no work runs, or the user agrees to stop it before `then`; the status bar says it is stopping."""
        if self.ctx.jobs.idle():
            return True
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        question = self.tr(
            "Work is still running: training, an AI model test, an inspection, an export or an image import. Stop "
            "it and {then}? Training stops without saving an AI model, so the active one stays; an AI model "
            "test finishes its folder first; an export or import keeps the files copied so far."
        ).format(then=then)
        if QMessageBox.question(self, self.tr("Stop the running work?"), question, yes | no, no) != yes:
            return False
        self.status(self.tr("Stopping the running work…"), ms=0)
        self.statusBar().repaint()  # the wait that follows holds the UI thread until each job has stopped
        return True

    # --- demo workspace (REQ-SET-007, REQ-SET-009) ----------------------------------
    def switch_workspace(self, folder: Path | None, reset: bool = False, play: bool = False) -> MainWindow | None:
        """Close this workspace and open `folder`, the demo workspace (None: the station's own), in a new window on
        the same page, signed in as a user of the same role; the demo is put back as the bundle holds it first when
        `reset`, and its scripted run started when `play`. Running work is stopped first, if the user agrees; a folder
        that does not open opens the one before again. Returns the new window, or None when nothing was switched."""
        if not self._may_stop_work(self.tr("switch the workspace")):
            return None
        role, page, keys = self.ctx.role, self._page_title(), self.ctx.credentials
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)  # the busy indicator while the folders are copied
        try:
            self.switched = True
            self.ctx.close()
            drop_queued(self.ctx.jobs)
            before = use_workspace(folder)
            failed, took = None, None
            if reset and folder is not None:
                try:
                    took = demo.reset(demo.bundle_dir(), folder, keys)
                except AoiError as e:  # shown once the demo is open again, as it is
                    failed = e
            ctx = open_workspace()  # a refusal is shown, with a folder picker where another folder cures it
            if ctx is None:
                use_workspace(before)
                ctx = open_workspace()
            win = build_window(ctx) if ctx is not None else None
        finally:
            QApplication.restoreOverrideCursor()
        if win is None:  # nothing opens: the app closes, as at a start that opens nothing
            if ctx is not None:
                ctx.close()
            self.close()
            return None
        win._sign_in_as(role)
        win.navigate(page)
        if failed is not None:
            show_error(win, win.ctx.report_error(failed, QT_TRANSLATE_NOOP("Errors", "demo reset")))
        elif took is not None:
            win.ctx.audit("demo.reset", "workspace", None, None, {"folder": str(folder), "seconds": round(took, 2)})
            win.status(self.tr("Demo reset in {seconds:.1f} s.").format(seconds=took))
        if play and win.in_demo:
            win.play_demo()
        win.showMaximized()
        self.close()
        self.deleteLater()
        return win

    def play_demo(self) -> None:
        """Inspection with the demo's boards queued as a scripted run at its pace, and Start pressed (REQ-SET-009)."""
        page = cast(InspectionPage, self.pages["Inspection"])
        if self.navigate("Inspection"):
            page.play(boards(self.ctx.settings.root), self.ctx.settings.demo_pace_s)

    def _sign_in_as(self, role: str) -> None:
        """Sign in the first user the workspace holds with `role`, if it holds one; else the start's user stays."""
        if (name := next((u["name"] for u in self.ctx.users() if u["role"] == role), None)) is not None:
            self.set_user(str(name))

    def _page_title(self) -> str:
        cur = self.stack.currentWidget()
        return cur.title if isinstance(cur, Page) else "Home"


def build_window(ctx: AppContext) -> MainWindow | None:
    """The main window at start-up, with the unhandled-error hook in place (REQ-LOG-005, REQ-SET-019), or None when
    it could not be built. The hook goes in before the window exists, so a slot that raises while the pages are built
    is logged and shown too, and again with the window as the dialog's parent once it is built. An error raised out of
    building it (a page that cannot read the database, #205) is shown as one coded dialog with its trace in the log;
    the caller closes the workspace and ends the app."""
    install_excepthook(ctx, None)
    try:
        win = MainWindow(ctx)
    except Exception as e:
        show_error(None, ctx.report_error(e, QT_TRANSLATE_NOOP("Errors", "start-up")))
        return None
    install_excepthook(ctx, win)
    return win
