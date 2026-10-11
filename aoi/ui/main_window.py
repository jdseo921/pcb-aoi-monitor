"""Application shell: header (board model + user), sidebar navigation, page stack."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPersistentModelIndex, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QColor, QKeySequence, QMouseEvent, QPainter
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
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_NAME, APP_VERSION, use_workspace
from ..core import datasets, demo, drift
from ..core.run_progress import RunProgress
from ..core.services import REQUIRED_ROLE, ROLES_FROM, AppContext
from ..errors import AoiError
from . import theme
from .demo_workspace import boards
from .errors import install_excepthook, open_workspace, phrase_text, show_error
from .pages.base import (
    QT_TRANSLATE_NOOP,
    Page,
    RoleGates,
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
        # (step, name, what it does, page, the AppContext call whose role the step needs, None for every role); the name
        # is also the key of its status label. Words from the Charter list.
        (
            "1",
            QT_TRANSLATE_NOOP("HomePage", "Upload samples"),
            QT_TRANSLATE_NOOP("HomePage", "Add good (OK) and defective (NG) photos of this board model."),
            "Training",
            "import_samples",
        ),
        (
            "2",
            QT_TRANSLATE_NOOP("HomePage", "Train AI model"),
            QT_TRANSLATE_NOOP("HomePage", "The app learns the Golden board and an AI model from your OK boards."),
            "Training",
            "start_training",
        ),
        (
            "3",
            QT_TRANSLATE_NOOP("HomePage", "Tune recipe"),
            QT_TRANSLATE_NOOP("HomePage", "Draw ROIs and adjust thresholds on the Golden board."),
            "Recipe Editor",
            "save_recipe",
        ),
        (
            "4",
            QT_TRANSLATE_NOOP("HomePage", "Validate"),
            QT_TRANSLATE_NOOP("HomePage", "Test the AI model on the locked validation set."),
            "AI Model Test",
            "test_dataset",
        ),
        (
            "5",
            QT_TRANSLATE_NOOP("HomePage", "Inspect"),
            QT_TRANSLATE_NOOP("HomePage", "Run boards; open Compare to see why any board was called NG."),
            "Inspection",
            None,
        ),
        (
            "6",
            QT_TRANSLATE_NOOP("HomePage", "Export"),
            QT_TRANSLATE_NOOP(
                "HomePage",
                "CSV files and overlay images on Logs & Export; the PDF reports on AI Model Test (Export Report, "
                "Validation Report…).",
            ),
            "Logs & Export",
            "export_csv_files",
        ),
    ]

    # each drift measure out of its control limits, as the Inspect card names it (REQ-INSP-019)
    DRIFT_NAMES = {
        drift.NG_RATE: QT_TRANSLATE_NOOP("HomePage", "NG rate up"),
        drift.WARN_RATE: QT_TRANSLATE_NOOP("HomePage", "WARN rate up"),
        drift.OK_SCORE: QT_TRANSLATE_NOOP("HomePage", "OK boards' AI score up"),
        drift.ALIGNMENT: QT_TRANSLATE_NOOP("HomePage", "alignment to the Golden board down"),
        drift.FALSE_CALLS: QT_TRANSLATE_NOOP("HomePage", "false calls up"),
    }

    def __init__(self, ctx: AppContext, shell: MainWindow) -> None:
        super().__init__(ctx, shell)
        self.cards = QWidget()
        grid = QGridLayout(self.cards)
        grid.setSpacing(theme.SPACE)
        self.status_labels: dict[str, QLabel] = {}
        self.training_line = QLabel()  # on Train AI model's card while a training run goes on (REQ-TRN-008)
        self._training = False  # whether the last show_training saw a run going on
        self.training_line.setWordWrap(True)
        self.training_line.hide()
        self.headings: list[tuple[QLabel, str, str]] = []  # each card's heading, its number and its name
        self.links: list[tuple[QPushButton, str]] = []  # each card's button and the page it opens
        self.who: dict[str, QLabel] = {}  # each card's line naming the role its step needs (REQ-USR-001)
        for i, (n, name, desc, target, call) in enumerate(self.STEPS):
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            h = QLabel(self._heading(n, name))
            self.headings.append((h, n, name))
            d = QLabel(self.tr(desc))
            d.setWordWrap(True)
            d.setObjectName("muted")
            who = QLabel(self._who(call))
            who.setWordWrap(True)
            self.who[name] = who
            st = QLabel("")
            st.setWordWrap(True)
            self.status_labels[name] = st
            cl.addWidget(h)
            cl.addWidget(d)
            cl.addWidget(who)
            cl.addStretch(1)
            cl.addWidget(st)
            if name == "Train AI model":
                cl.addWidget(self.training_line)
            kind = "primary" if target == "Inspection" else ""  # the page's one blue primary: the Inspect card
            go = button("", kind, lambda _=False, t=target: shell.navigate(t))
            self.links.append((go, target))
            cl.addWidget(go)
            grid.addWidget(card, i // 3, i % 3)
        self.root.addWidget(self.cards)
        self.empty = EmptyState()  # no board model yet: one block in place of the cards (REQ-SET-019)
        self.root.addWidget(self.empty)
        self.root.addStretch(1)

    def _who(self, call: str | None) -> str:
        """The role a step needs, as its card says it to every role: the role AppContext's `call` requires and those
        above it (REQUIRED_ROLE), or every role for a step with no call that checks one."""
        if call is None:
            return self.tr("Open to every role.")
        return self.tr("Needs the {roles} role.").format(roles=phrase_text(ROLES_FROM[REQUIRED_ROLE[call]]))

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
        """Train AI model's line while a training run goes on, with its latest report; hidden once it ends, when the
        cards shown say what the run left: its version active, or trained and not active (ADR 0018)."""
        if running:
            percent, left = (progress.percent, progress.left_s) if progress else (0, None)
            line = self.tr("Training running {percent} % · {left}")
            self.training_line.setText(line.format(percent=percent, left=time_left_text(left)))
        self.training_line.setVisible(running)
        ended, self._training = self._training and not running, running
        if ended and self.isVisible():
            self.on_show()

    def _sync_links(self) -> None:
        """Each card's button opens its page, or, for a page the role may not open, is greyed and reads "For Engineer /
        Admin", its tooltip naming the page too: an Operator's Home holds no button that leads nowhere (Engineering
        standard, "No dead ends")."""
        for go, target in self.links:
            allowed = self.ctx.role in self.shell.pages[target].roles
            go.setEnabled(allowed)
            roles = " / ".join(role_text(r) for r in self.shell.pages[target].roles)
            text = self.tr("Open {page} ›").format(page=page_text(target)) if allowed else self.tr("For {roles}")
            go.setText(text.format(roles=roles).replace("&", "&&"))  # "Logs & Export" as written, not a mnemonic
            go.setToolTip("" if allowed else self.shell.needs_role(target))  # the page and the roles that open it

    def on_show(self) -> None:
        self._sync_links()
        bm = self.board_model
        self.cards.setVisible(bool(bm))
        if not bm:
            self.show_empty(self.empty, *self.no_board_model())
            return
        self.empty.hide()
        st = self.ctx.board_status(bm)
        tm = st.last_test
        self.status_labels["Upload samples"].setText(
            self.tr("{ok} OK · {ng} NG uploaded").format(ok=st.ok_samples, ng=st.ng_samples)
            if st.ok_samples or st.ng_samples
            else self.tr("No samples yet. Add at least {count} OK boards.").format(count=FIRST_OK)
        )
        waiting = None if st.model_version else self.ctx.inactive_model(bm)  # trained, not active: named (D3)
        self.status_labels["Train AI model"].setText(
            self.tr("Active AI model {version}").format(version=st.model_version)
            if st.model_version
            else self.tr("AI model {version} trained, not active. Activate it on Training.").format(
                version=waiting["version"]
            )
            if waiting
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
        inspected = self.tr("{count} boards inspected · {ng} NG").format(count=st.inspected, ng=st.ng)
        if st.reviewed:  # the calls reviewed on the line, and how many were false (REQ-INSP-013)
            reviewed = self.tr("False calls {false_calls} of {reviewed} reviewed")
            inspected += "\n" + reviewed.format(false_calls=st.false_calls, reviewed=st.reviewed)
        if st.drifted:  # measures out of their control limits now: look at the line (REQ-INSP-019)
            names = ", ".join(self.tr(self.DRIFT_NAMES[m]) for m in st.drifted)
            inspected += "\n" + self.tr("Drift: {measures}. See the alarm log on Inspection.").format(measures=names)
        self.status_labels["Inspect"].setText(
            inspected if st.inspected else self.tr("No boards inspected yet. Load images on Inspection.")
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


HEADING = Qt.ItemDataRole.UserRole + 1  # a sidebar row that is a section's heading, not a page


class _NavDelegate(QStyledItemDelegate):
    """The sidebar's rows: a page's entry as the theme draws it, an operator target (TARGET_H); a section's heading,
    which no one clicks, a line of muted text only as tall as it needs, so that every entry, badge and all, fits a
    768 px tall screen without a scroll bar narrowing the sidebar under its badges."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:  # noqa: N802
        hint = super().sizeHint(option, index)
        if not index.data(HEADING):
            return hint
        return QSize(hint.width(), option.fontMetrics.height() + 2 * theme.SPACE_S)

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        if not index.data(HEADING):
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setFont(option.font)
        painter.setPen(QColor(theme.TEXT_MUTED))  # a heading, not a disabled control: 7.4:1 (#239)
        style = option.widget.style() if option.widget is not None else QApplication.style()
        inset = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, option, option.widget) + 1  # as Qt's text
        text = option.rect.adjusted(theme.SPACE_S + theme.NAV_TEXT_X + inset, 0, -theme.SPACE_S, 0)
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
        painter.drawText(text.adjusted(0, 0, 0, -theme.SPACE_S // 2), align, str(index.data()))
        painter.restore()


class _GreyedEntryPress(QObject):
    """A press on a greyed sidebar entry says on the status bar which role opens its page, as its tooltip does: a
    touch screen shows no tooltip, and a greyed entry takes no click (REQ-USR-001)."""

    def __init__(self, win: MainWindow) -> None:
        super().__init__(win)
        self.win = win

    def eventFilter(self, watched: QObject, e: QEvent) -> bool:  # noqa: N802 (Qt's name)
        if e.type() == QEvent.Type.MouseButtonPress and isinstance(e, QMouseEvent):
            it = self.win.nav.itemAt(e.position().toPoint())
            title = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
            if it is not None and title in self.win.pages and not it.flags() & Qt.ItemFlag.ItemIsEnabled:
                self.win.navigate(title)  # refused, and says why on the status bar
        return False


class _PageStack(QStackedWidget):
    """The pages in the scroll area round them (#104): as wide as the widest page needs, as a QStackedWidget is, so
    every page keeps the width it was laid out for, but only as tall as the page shown needs. A QStackedWidget asks
    for the tallest page's height, so every page would scroll as far down as the tallest one (Settings) needs, and
    Compare's Try panel would sit below the fold of a 1600 x 900 window."""

    def __init__(self) -> None:
        super().__init__()
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        page, hint = self.currentWidget(), super().minimumSizeHint()
        if page is None:
            return hint
        return QSize(hint.width(), max(page.minimumSizeHint().height(), page.minimumHeight()))

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        page, hint = self.currentWidget(), super().sizeHint()
        return hint if page is None else QSize(hint.width(), page.sizeHint().height())

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt's name)
        """None: the scroll area then gives the page the viewport's height, or its minimum where that is more, as the
        window gave it before (a wrapped label's preferred height would make every page scroll)."""
        return -1


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, carried: str | None = None) -> None:
        """The window on `ctx`'s workspace. `carried`: the role of the user signed in in the window before, when a
        workspace switch builds this one (`switch_workspace`)."""
        super().__init__()
        self.ctx = ctx
        self.board_model: str | None = None
        self.last_inspected: tuple[str, InspectionResult, int | None] | None = None  # path, result, record id
        self.in_demo = demo.is_demo(ctx.settings.root)  # the demo workspace is open (REQ-SET-007)
        self.switched = False  # closed by switch_workspace, which stopped the work and closed the context already
        self.gates = RoleGates(self, ctx, self.status)  # the header's controls a role may not use (REQ-USR-001)
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
        self.nav.setItemDelegate(_NavDelegate(self.nav))
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
                sec.setData(HEADING, True)
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
        self.nav.viewport().installEventFilter(_GreyedEntryPress(self))
        # Ctrl+1 to Ctrl+9 open the sidebar's pages in its order, from any page, and F1 lists the keys of the page
        # shown (Engineering standard, "Short paths": one key to any page; "Input": every action by keyboard)
        self.page_keys: dict[str, str] = {}
        for n, title in enumerate(self.pages, 1):
            if n <= 9:
                key = QKeySequence(f"Ctrl+{n}")
                self.page_keys[title] = key.toString(QKeySequence.SequenceFormat.NativeText)
                go = QAction(self)
                go.setShortcut(key)
                go.triggered.connect(lambda _=False, t=title: self.navigate(t))
                self.addAction(go)
        keys = QAction(self)
        keys.setShortcut(QKeySequence(Qt.Key.Key_F1))
        keys.triggered.connect(self.show_keys)
        self.addAction(keys)

        self._training_timer = QTimer(self)  # the header and Home follow a training run on every page (REQ-TRN-008)
        self._training_timer.timeout.connect(self.show_training)
        self._training_timer.start(1000)
        self._reload_board_models()
        # the demo, and a station with no board model yet to set up, start with an Admin; any other start with the user
        # who signed in last on the station; a workspace switch with the first user of the role carried, if the folder
        # holds one; the role is the stored one either way (#197). Audited as user.start, which no later start reads,
        # so a role carried, the demo's Admin say, is never the station's next start user (REQ-USR-003)
        start = ctx.start_user(setting_up=not ctx.board_models())
        if carried is not None:
            start = next((str(u["name"]) for u in ctx.users() if u["role"] == carried), start)
        ctx.sign_in(start, start=True)
        self.set_user(start)
        if self.in_demo:  # its boards wait on Inspection as a scripted run at the demo's pace (REQ-SET-009)
            cast(InspectionPage, self.pages["Inspection"]).play(
                boards(ctx.settings.root), ctx.settings.demo_pace_s, False
            )
        # where the last session was (REQ-LOG-005); the demo after a normal close at Home, where its scripts begin
        if not self.navigate(ctx.settings.last_page):
            self.navigate("Home")
        resumed = carried is None and not self.in_demo and bool(ctx.board_models()) and start == ctx.last_signed_in()
        if resumed:  # someone else may be at the station now
            said = self.tr(
                "Signed in as {user} ({role}), who signed in last on this station. Not you? Press Switch User."
            )
            self.status(said.format(user=start, role=role_text(ctx.role)), ms=0)

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
        self.btn_new = button(self.tr("+ New"), slot=self.new_board_model)  # greyed for an Operator (_sync_nav)
        layout.addWidget(self.btn_new)
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
        for control in (self.bm_combo, self.btn_new, self.training_link, self.exit_presenter, switch):
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
            name = str(users[names.index(sel)]["name"])
            try:
                self.ctx.sign_in(name)  # audited, and the station's next start signs them in again
            except AoiError as e:
                show_error(self, self.ctx.report_error(e, "Switch user"))
                return
            self.set_user(name)

    def set_user(self, user: str) -> None:
        """Sign `user` in with the role the users table holds for them (#197); the header and the pages follow it."""
        self.ctx.set_user(user)
        role = self.ctx.role
        self.user_label.setText(self.tr("{user}  ·  {role}").format(user=user, role=role_text(role)))
        self._sync_nav()
        for page in self.pages.values():  # shown or not: what a page keeps for the role before goes now
            page.on_user_changed()
            page.limits_changed()  # an empty state names what the new role may not do
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
            tip = " · ".join(t for t in (page_text(self.pages[title].badge_tip), self.page_keys.get(title, "")) if t)
            it.setToolTip(tip if allowed else self.needs_role(title))
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
        self.gates.gate(self.btn_new, "ensure_board_model")  # never hidden: greyed, saying who may (REQ-USR-001)

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

    def needs_role(self, title: str) -> str:
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
            self.status(self.needs_role(title))
        return False

    def keys_text(self) -> str:
        """The keys of the page shown, then the keys that open each page the role may open, one per line (F1)."""
        cur = self.stack.currentWidget()
        lines: list[str] = []
        if isinstance(cur, Page):
            lines.append(self.tr("On {page}:").format(page=page_text(cur.title)))
            for a in cur.actions():
                key = a.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
                if key and a.text():
                    name = a.text().replace("▶", "").replace("■", "").strip()
                    lines.append(self.tr("{key}   {action}").format(key=key, action=name))
            lines.append("")
        lines.append(self.tr("Open a page:"))
        for title, key in self.page_keys.items():
            if self.ctx.role in self.pages[title].roles and not self.hidden(title):
                lines.append(self.tr("{key}   {action}").format(key=key, action=page_text(title)))
        lines += ["", self.tr("F1   This list of keys")]
        return "\n".join(lines)

    def show_keys(self) -> None:
        """F1: the keys of the page shown and of every page, so a new user learns them where they work."""
        QMessageBox.information(self, self.tr("Keys"), self.keys_text())

    def _on_nav(self, cur: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        if cur is None or not cur.data(Qt.ItemDataRole.UserRole):
            return
        page = self.pages[cur.data(Qt.ItemDataRole.UserRole)]
        self.stack.setCurrentWidget(page)
        page.on_show()
        self._save_page(page.title)

    def _save_page(self, title: str) -> None:
        """`title` as the page the next start opens (REQ-LOG-005), unaudited, as no user asks for it."""
        if self.ctx.settings.last_page != title:
            self.ctx.settings.last_page = title
            try:  # that key alone, over the file as it is now: a hand edit made while the app runs stays (#170)
                self.ctx.settings.save_keys({"last_page": title})
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
        if self.in_demo and not self.switched:  # closed, the demo opens at Home next, where its scripts begin; after a
            self._save_page("Home")  # crash, on the page it showed, so the presenter carries on (REQ-LOG-005)
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
        if self.in_demo:  # the demo, left, opens at Home next as after a close; saved before another settings.json
            self._save_page("Home")
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
            win = build_window(ctx, role) if ctx is not None else None  # signed in as the role carried
        finally:
            QApplication.restoreOverrideCursor()
        if win is None:  # nothing opens: the app closes, as at a start that opens nothing
            if ctx is not None:
                ctx.close()
            self.close()
            return None
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

    def _page_title(self) -> str:
        cur = self.stack.currentWidget()
        return cur.title if isinstance(cur, Page) else "Home"


def build_window(ctx: AppContext, carried: str | None = None) -> MainWindow | None:
    """The main window at start-up, or at a workspace switch with the role `carried` from the window before, with the
    unhandled-error hook in place (REQ-LOG-005, REQ-SET-019), or None when it could not be built. The hook goes in
    before the window exists, so a slot that raises while the pages are built is logged and shown too, and again with
    the window as the dialog's parent once it is built. An error raised out of building it (a page that cannot read the
    database, #205; a start's sign-in whose audit entry cannot be written, so no one is signed in unaudited) is shown
    as one coded dialog with its trace in the log; the caller closes the workspace and ends the app."""
    install_excepthook(ctx, None)
    try:
        win = MainWindow(ctx, carried)
    except Exception as e:
        show_error(None, ctx.report_error(e, QT_TRANSLATE_NOOP("Errors", "start-up")))
        return None
    install_excepthook(ctx, win)
    return win
