"""Every colour, point size and size class the screens use (REQ-SET-004; Engineering standard, "Look" and "Sizes").

Screens take tokens from here and never write a colour or a point size of their own, so a theme change (the light
presenter theme, REQ-SET-008) is one file, and `tests/test_screen_rules.py` fails the build on a colour literal
anywhere else under aoi/ui. The verdict and severity colours are the standard's, and a verdict is always shown as
its colour with a word and a shape (REQ-INSP-002), never as colour alone.

Contrast, by the WCAG 2.1 formula (tests/screens measures it on every rendered page): every text colour on its surface
reads at 4.5:1 or more. Text on the standard's OK green, NG red and accent blue is black, ON_FILL (6.4, 5.0 and 5.7:1;
Q53, #150): the verdict banner, coloured cells, the primary, Start, Stop and danger buttons. One exception is left: a
progress bar's bold percentage straddles the accent chunk and the dark trough, so it stays white (3.7:1 on the chunk,
the 3:1 WCAG AA asks of bold text), and so does the 22 pt bold number on a Home card, ACCENT on BG_RAISED (3.5:1, #240).
The selected sidebar entry, tab and row, and selected text, whose text is not bold, sit on BG_SELECTED (5.7:1). A
disabled control is exempt (WCAG 1.4.3), and every disabled button, coloured or not, greys out to BG_RAISED and
TEXT_DISABLED, so it never looks ready to press; a disabled field, its label and its group's title take TEXT_DISABLED
too, as Compare's thresholds do for an Operator (REQ-USR-001). The lists, calendars and menus that open as windows of
their own are themed here too, never left on the platform's light background, and the calendar's bar stays BG_SELECTED,
on which Qt's dark month arrows read at 3.4:1 (#239); the sidebar greys a page the role may not open on the item itself,
since a rule for disabled items would also grey its headings.

The light presenter theme (REQ-SET-008, frame sketch) is PRESENTER, a set of overrides of these tokens that `use()` puts
in place while it is on: a #FAFAFA background, text 18 pt or more and the verdict at 48 pt, with the same verdict
colours and shapes; where the app has under SMALL_H px of height or SMALL_W px of width, PRESENTER_SMALL's 16 pt text
and 44 pt verdict over those (ADR 0019, put to Jay as a departure from REQ-SET-008's 18 pt). There every text colour
reads at 4.5:1 or more on its surface, bold and large text included, with black on the green, red and blue fills
(Q53). The screens read the tokens when they draw, so `stylesheet()` and
anything drawn after the switch follow it; what a screen drew before is drawn again by MainWindow.apply_theme.
"""

from collections.abc import Callable
from functools import partial
from string import Template

# Verdicts and severities (Engineering standard, "Look"); the shapes pair with the words (REQ-INSP-002)
OK_COLOR = "#43a047"
NG_COLOR = "#e53935"
WARN_COLOR = "#fdd835"
INFO_COLOR = "#90a4ae"
MAJOR_COLOR = "#fb8c00"  # severity Major, between Critical (NG red) and Minor (WARN amber)
ACCENT = "#1e88e5"  # the one primary button on a page, progress
ACCENT_TEXT = ACCENT  # text in the accent colour: the number on a Home card
VERDICT_COLORS = {"OK": OK_COLOR, "NG": NG_COLOR, "WARN": WARN_COLOR, "INFO": INFO_COLOR}
VERDICT_SHAPES = {"OK": "✓", "NG": "✗", "WARN": "▲", "INFO": "·"}
SEVERITY_COLORS = {"Critical": NG_COLOR, "Major": MAJOR_COLOR, "Minor": WARN_COLOR}
SEVERITY_SHAPES = {"Critical": "◆", "Major": "■", "Minor": "●"}  # on a defect box's label (Q57, #152)
NG_TINT = "#5d2a2a"  # an NG row in a long list, readable with normal text (9.7:1)
ROI_SELECTED, ROI_COLOR, ROI_DISABLED = WARN_COLOR, OK_COLOR, "#6c7c8c"  # Recipe Editor: edited, saved, disabled

# Surfaces, lines and text of the dark production theme
BG = "#1f2a36"
BG_DEEP = "#15202b"  # header, sidebar, fields, tables
BG_ALT = "#1a2633"  # alternate table rows
BG_RAISED = "#26323f"  # cards, tiles, table headers, disabled buttons
BG_IMAGE = "#0f161d"  # behind board images
BG_BUTTON, BG_BUTTON_HOVER, BG_NAV_HOVER = "#2d4257", "#36506a", "#24394f"
BG_SELECTED = "#1565c0"  # the selected sidebar entry, tab, row and text: 14 pt white reads at 5.7:1, 3.7:1 on ACCENT
BG_ON = BG_SELECTED  # a toggle button while it is on, such as Draw Box in Draw mode, with white text and border
BG_BUSY = "rgba(15, 22, 29, 200)"
LINE, LINE_STRONG = "#2f3e4e", "#3f5a75"
TEXT, TEXT_MUTED, TEXT_DISABLED = "#e6edf3", "#9fb0c0", "#6c7c8c"
ON_LIGHT = BG  # text on amber
ON_DARK = "#ffffff"  # text on the selection blue and on dark surfaces
ON_FILL = "#000000"  # text on the green, red and blue fills: 6.4, 5.0 and 5.7:1 (Q53, #150)
PRINT_TEXT = "#000000"  # text in a PDF report, on paper

# Point sizes, never below FONT_PT, and pixel sizes (Engineering standard, "Sizes"; the sketches' size classes)
FONT_FAMILY = '"Segoe UI", "Malgun Gothic", "Noto Sans", sans-serif'  # the screenshot tests pin one font instead
FONT_MONO = '"Consolas", "DejaVu Sans Mono", monospace'  # a recovery sheet's key, each letter as wide
FONT_PT = 14  # body, tables, headers, muted labels
FONT_LARGE_PT = 16  # card titles, the logo, busy text
FONT_H1_PT = 20
FONT_STEP_PT = 22  # the number on a Home card
FONT_TILE_PT = 26  # the value on a metric tile
FONT_VERDICT_PT = 40  # the verdict banner, size class V
BUTTON_W, BUTTON_H = 120, 40  # B
TARGET_H = 48  # T: an operator target, such as a defect row or a sidebar entry
RUN_CONTROL_H = 56  # T+: Start, Stop, Next Board, Save Image…
FIELD_H = 40  # F
BANNER_H = 90  # the verdict banner and a metric tile
WHY_MIN_H = 60  # Compare's "why" box gives way to two lines before the decision table's rows are squeezed
DECISION_ROWS = 7  # and before the decision table shows fewer rows than this, the sketch's seven; more scroll
TRY_ROWS = 5  # the rows the Recipe Editor's Try checks table shows before it scrolls (recipe-editor sketch)
NAV_W, HEADER_H, FIELD_W, CARD_W = 250, 64, 240, 720
CELL_PAD = 6  # px of space each side of a table cell's and its heading's text, so no two cells' text runs together
NAV_TEXT_X = 18  # a sidebar entry's text from its left edge, as QListWidget#nav::item's padding sets it
IMAGE_MIN_W, IMAGE_MIN_H, PROGRESS_W = 320, 240, 360
SIDE_W = 520  # Inspection's verdict panel beside the board; the board gives way in a narrower window (#104)
# Compare's decision table with every column whole, as the demo's NG board fills it (893 px at 14 pt): the pair goes
# beside it only where both fit, a width the window decides, not the record shown (#104, review of A7)
DECISION_W = 900
FILTER_MIN_W = 80  # a name filter's drop-down gives way to this in a narrow window ("All" stays whole; S51)
MARK_D = 12  # a point picked on an image (Calibrate Scale…): a ring this many px across at every zoom
WHY_H = 150  # Compare's "why" box at most, AOI-RCP-007's line in it included (S29)
HANDLE_PX = 16  # a corner handle of the selected defect box on Training's label editor (labels sketch)
SPACE, SPACE_S = 14, 8  # between blocks; inside a block
ROW_GAP = 6  # between a row's controls: Qt's own spacing in a box layout, kept by the rows that wrap (#104)
RADIUS, RADIUS_L = 6, 10
MARK_W = 6  # the verdict-colour bar beside a verdict said next to a control, such as Compare's "Would be"
SHARE_BAR_W = 320  # the longest bar of Logs & Export's Defect types tab, the type with the most defects (REQ-LOG-008)

TOKENS = {k: v for k, v in dict(globals()).items() if k.isupper()}

# The light presenter theme (REQ-SET-008): what differs from the tokens above; ON_LIGHT, the text on amber, stays
PRESENTER = {
    "BG": "#fafafa", "BG_DEEP": "#ffffff", "BG_ALT": "#f1f4f7", "BG_RAISED": "#eceff1", "BG_IMAGE": "#e3e8ec",
    "BG_BUTTON": "#e3e8ec", "BG_BUTTON_HOVER": "#d3dce3", "BG_NAV_HOVER": "#e3eef9", "BG_SELECTED": "#bbdefb",
    "BG_ON": "#bbdefb", "BG_BUSY": "rgba(250, 250, 250, 220)", "LINE": "#cfd8dc", "LINE_STRONG": "#78909c",
    "TEXT": "#1b1f24", "TEXT_MUTED": "#455a64", "TEXT_DISABLED": "#9aa6b0", "NG_TINT": "#ffcdd2",
    "ON_DARK": "#000000",  # black on the green, red and blue fills: 6.4, 5.0 and 5.7:1 (Q53)
    "ACCENT_TEXT": "#1565c0",  # 4.9:1 on BG_RAISED, where ACCENT reads at 3.1:1
    "FONT_PT": 18, "FONT_LARGE_PT": 20, "FONT_H1_PT": 24, "FONT_STEP_PT": 26, "FONT_TILE_PT": 30,
    "FONT_VERDICT_PT": 48,  # Q2
    # Inspection's verdict panel: its defect list's six columns whole with a type as long as "Missing Component" at
    # 18 pt, where 520 px scrolled the list sideways and cut off X and Y; at 16 pt its summary takes four lines, not
    # five, so its list, review and Compare fit over Start in a 768 px window
    "SIDE_W": 640,
    "DECISION_W": 1100,  # 1099 px at 18 pt
}  # fmt: skip
# The presenter theme in a window shorter than SMALL_H px or narrower than SMALL_W, as on a 1366 x 768 projector (#104,
# ADR 0019): its text as large on the wall as the presenter theme's on a 1920 x 1080 one, or larger (16 pt is 2.8 % of
# 768 lines, 18 pt 2.2 % of 1080, and 2.1 % of a 1280 x 1024 screen's 1024), and Compare's pair, verdict and decision
# table, and Inspection's verdict panel, whole in the window. 1920 x 1080 gives a window of about 1000 px; at 18 pt
# Compare's decision table needs a window 1389 px wide (docs/tests/2026-10-screen-sizes.md).
SMALL_H, SMALL_W = 900, 1400
PRESENTER_SMALL = {
    "FONT_PT": 16, "FONT_LARGE_PT": 18, "FONT_H1_PT": 22, "FONT_STEP_PT": 24, "FONT_TILE_PT": 26,
    "FONT_VERDICT_PT": 44,  # REQ-SET-004's verdict is 40 pt at least
    "DECISION_W": 980,  # 975 px at 16 pt
    # Compare's "why" box beside the pair, four lines: asking for 150 px it made the pair taller than its boards need,
    # and with Windows' Segoe UI, whose lines are 4 px taller than DejaVu Sans's, pushed the decision table's last row
    # 14 px below a 1366 x 768 window; it takes the height its column has, and its reasons scroll within it
    "WHY_H": 110,
}  # fmt: skip

_QSS = Template("""
* { font-family: ${FONT_FAMILY}; font-size: ${FONT_PT}pt; selection-background-color: $BG_SELECTED;
    selection-color: $ON_DARK; }
QMainWindow, QWidget#page, QDialog { background: $BG; color: $TEXT; }
QScrollArea#pages, QScrollArea#pages > QWidget#qt_scrollarea_viewport, QStackedWidget#stack { background: $BG; }
QWidget { color: $TEXT; }
QLabel#h1 { font-size: ${FONT_H1_PT}pt; font-weight: 600; }
QLabel#muted { color: $TEXT_MUTED; }
QLabel#logo, QLabel#busyText { font-size: ${FONT_LARGE_PT}pt; font-weight: 600; }
QLabel#recoveryKey { font-family: ${FONT_MONO}; font-size: ${FONT_H1_PT}pt; }
QLabel#badge { background: $WARN_COLOR; color: $ON_LIGHT; border-radius: ${RADIUS}px; padding: 4px ${SPACE_S}px; }
QListWidget#nav QLabel#badge { padding: 0 4px; }  /* on the entry's line of text, clear of its name */
QLabel#tile { background: $BG_RAISED; border-radius: ${RADIUS_L}px; padding: ${SPACE_S}px; }
QFrame#header { background: $BG_DEEP; border-bottom: 1px solid $LINE; }
QFrame#card { background: $BG_RAISED; border-radius: ${RADIUS_L}px; }
QWidget#empty { background: $BG_DEEP; border: 1px dashed $LINE_STRONG; border-radius: ${RADIUS_L}px; }
QLabel#emptyHeading { font-size: ${FONT_LARGE_PT}pt; font-weight: 600; }
QListWidget#nav { background: $BG_DEEP; border: none; padding-top: ${SPACE_S}px; }
QListWidget#nav::item { padding: ${SPACE}px ${NAV_TEXT_X}px; margin: 2px ${SPACE_S}px; border-radius: ${RADIUS}px; }
QListWidget#nav::item:selected { background: $BG_SELECTED; color: $ON_DARK; }
QListWidget#nav::item:hover:!selected { background: $BG_NAV_HOVER; }
QPushButton { background: $BG_BUTTON; border: 1px solid $LINE_STRONG; border-radius: ${RADIUS}px;
              min-width: ${BUTTON_W}px; min-height: ${BUTTON_H}px; padding: 0 ${SPACE}px; }
QPushButton:hover { background: $BG_BUTTON_HOVER; }
QPushButton:checked, QPushButton:checked:hover { background: $BG_ON; border-color: $ON_DARK; color: $ON_DARK; }
QPushButton[sizeClass="T"], QComboBox[sizeClass="T"], QRadioButton[sizeClass="T"] { min-height: ${TARGET_H}px; }
QRadioButton[sizeClass="T"] { background: $BG_BUTTON; border: 1px solid $LINE_STRONG; border-radius: ${RADIUS}px;
                              padding: 0 ${SPACE}px; }
QRadioButton[sizeClass="T"]::indicator { width: 0; height: 0; }
QRadioButton[sizeClass="T"]:checked { background: $BG_SELECTED; border-color: $BG_SELECTED; color: $ON_DARK; }
QRadioButton[sizeClass="T"]:focus { border-color: $TEXT; }
QRadioButton[sizeClass="T"]:disabled { color: $TEXT_DISABLED; background: $BG_RAISED; }
QPushButton[sizeClass="T+"] { min-height: ${RUN_CONTROL_H}px; }
QCheckBox[sizeClass="F"] { min-height: ${FIELD_H}px; }
QCheckBox[sizeClass="T"] { min-height: ${TARGET_H}px; }
QPushButton:disabled { color: $TEXT_DISABLED; background: $BG_RAISED; }
QPushButton#primary, QPushButton#start, QPushButton#stop, QPushButton#danger { color: $ON_FILL; font-weight: 700; }
QPushButton#primary { background: $ACCENT; border-color: $ACCENT; }
QPushButton#start { background: $OK_COLOR; border-color: $OK_COLOR; }
QPushButton#stop, QPushButton#danger { background: $NG_COLOR; border-color: $NG_COLOR; }
QPushButton#primary:disabled, QPushButton#start:disabled, QPushButton#stop:disabled, QPushButton#danger:disabled {
    color: $TEXT_DISABLED; background: $BG_RAISED; border-color: $LINE_STRONG; font-weight: normal; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit {
    background: $BG_DEEP; border: 1px solid $LINE_STRONG; border-radius: 4px; min-height: ${FIELD_H}px;
    padding: 0 6px; }
QLabel:disabled, QCheckBox:disabled, QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QDateEdit:disabled { color: $TEXT_DISABLED; }  /* a field or its label a role may not use looks it (REQ-USR-001) */
QDoubleSpinBox#calibrated:disabled { color: $TEXT_MUTED; }
QComboBox QAbstractItemView { background: $BG_DEEP; color: $TEXT; border: 1px solid $LINE_STRONG;
    selection-background-color: $BG_SELECTED; selection-color: $ON_DARK; }
QCalendarWidget QAbstractItemView { background: $BG_DEEP; color: $TEXT; alternate-background-color: $BG_RAISED;
    selection-background-color: $BG_SELECTED; selection-color: $ON_DARK; }
QCalendarWidget QAbstractItemView:disabled { color: $TEXT_MUTED; }
QCalendarWidget QWidget#qt_calendar_navigationbar { background: $BG_SELECTED; }
QCalendarWidget QToolButton { color: $ON_DARK; }
QCalendarWidget QToolButton#qt_calendar_monthbutton:hover, QCalendarWidget QToolButton#qt_calendar_monthbutton:pressed,
QCalendarWidget QToolButton#qt_calendar_yearbutton:hover, QCalendarWidget QToolButton#qt_calendar_yearbutton:pressed {
    background: $BG_BUTTON_HOVER; border: none; border-radius: 4px; }
QMenu { background: $BG_RAISED; color: $TEXT; border: 1px solid $LINE_STRONG; }
QMenu::item:selected { background: $BG_SELECTED; color: $ON_DARK; }
QMenu::item:disabled { color: $TEXT_DISABLED; }
QTableWidget, QListWidget, QPlainTextEdit, QTextEdit {
    background: $BG_DEEP; alternate-background-color: $BG_ALT; gridline-color: $LINE; border: 1px solid $LINE; }
QHeaderView::section { background: $BG_RAISED; padding: ${CELL_PAD}px; border: none; font-weight: 600; }
QTableWidget::item { padding: 0 ${CELL_PAD}px; }  /* a cell's text as clear of the next as its heading's */
QGroupBox { border: 1px solid $LINE; border-radius: ${RADIUS}px; margin-top: 18px; padding-top: ${SPACE_S}px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: $TEXT_MUTED; }
QGroupBox::title:disabled { color: $TEXT_DISABLED; }
QProgressBar { background: $BG_DEEP; border: 1px solid $LINE_STRONG; border-radius: 4px; text-align: center;
               min-height: 24px; color: $ON_DARK; font-weight: 700; }
QProgressBar::chunk { background: $ACCENT; }
QTabWidget::pane { background: $BG; border: 1px solid $LINE; }
QTabWidget > QWidget, QStackedWidget > QWidget#qt_tabwidget_stackedwidget { background: $BG; }
QHeaderView { background: $BG_RAISED; }
QTableCornerButton::section { background: $BG_RAISED; border: none; }
QTabBar::tab { background: $BG_RAISED; padding: ${SPACE_S}px 18px; min-width: ${BUTTON_W}px; }
QTabBar::tab:selected { background: $BG_SELECTED; color: $ON_DARK; }
QStatusBar { background: $BG_DEEP; color: $TEXT_MUTED; }
QWidget#busy { background: $BG_BUSY; }
QScrollBar:vertical { background: $BG_DEEP; width: 16px; margin: 0; }
QScrollBar:horizontal { background: $BG_DEEP; height: 16px; margin: 0; }
QScrollBar::handle { background: $BG_BUTTON; border-radius: ${RADIUS}px; }
QScrollBar::handle:vertical { min-height: ${BUTTON_H}px; }
QScrollBar::handle:horizontal { min-width: ${BUTTON_H}px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; border: none;
                                                                                        width: 0; height: 0; }
QSlider[sizeClass="T"] { min-height: ${TARGET_H}px; }
QSlider::groove:horizontal { background: $BG_DEEP; border: 1px solid $LINE_STRONG; height: 8px; border-radius: 4px; }
QSlider::handle:horizontal { background: $ACCENT; border: 1px solid $LINE_STRONG; width: ${TARGET_H}px;
                             margin: -20px 0; border-radius: ${RADIUS}px; }
QSlider::handle:horizontal:focus { border-color: $TEXT; }
""")


def stylesheet(**overrides: object) -> str:
    """The application stylesheet built from the tokens in use (the production theme's or the presenter theme's),
    with `overrides`, such as the font the screenshots pin."""
    return _QSS.substitute({**{k: globals()[k] for k in TOKENS}, **overrides})


QSS = stylesheet()


def use(presenter: bool, small: bool = False) -> None:
    """Put the presenter theme's tokens in place (REQ-SET-008), its sizes for a small window with `small` (#104), or
    the production theme's back. The caller applies `stylesheet()` and draws again what it drew with the tokens before
    (MainWindow.apply_theme)."""
    tokens = {**TOKENS, **(PRESENTER if presenter else {}), **(PRESENTER_SMALL if presenter and small else {})}
    globals().update({k: tokens[k] for k in PRESENTER.keys() | PRESENTER_SMALL.keys()})


def presenter() -> bool:
    """Whether the presenter theme's tokens are in use."""
    return BG == PRESENTER["BG"]


def small() -> bool:
    """Whether the presenter theme's sizes for a small window are in use."""
    return presenter() and FONT_PT == PRESENTER_SMALL["FONT_PT"]


def verdict_styles() -> dict[str, Callable[[], str]]:
    """Every verdict stylesheet a label can hold now, each with what makes it again from the tokens in use when it is
    called: what a shown verdict is styled with again once the theme is switched (MainWindow.apply_theme)."""
    styles: dict[str, Callable[[], str]] = {}
    for v in VERDICT_COLORS:
        styles[verdict_mark_style(v)] = partial(verdict_mark_style, v)
        for big in (True, False):
            styles[verdict_style(v, big)] = partial(verdict_style, v, big)
    return styles


def row_fill(colour: str) -> str:
    """The fill of a table row in the theme in use: an NG row's tint is the theme's own (NG_TINT), the verdict and
    severity colours are the same in both."""
    return NG_TINT if colour in (TOKENS["NG_TINT"], PRESENTER["NG_TINT"]) else colour


def verdict_label(verdict: str) -> str:
    """The verdict as a shape and a word, "✗ NG", so colour is never the only cue (REQ-INSP-002)."""
    return f"{VERDICT_SHAPES.get(verdict, VERDICT_SHAPES['INFO'])} {verdict}"


def severity_label(severity: str) -> str:
    """A severity as a shape and a word, "◆ Critical", for a defect box's label (Q57, #152)."""
    return f"{SEVERITY_SHAPES.get(severity, SEVERITY_SHAPES['Critical'])} {severity}"


def on_color(fill: str) -> str:
    """The text colour that reads on `fill`: dark on amber, grey and orange (5.6:1 or more), black on green, red and
    blue (5.0:1 or more, Q53), white on anything else."""
    if fill in (WARN_COLOR, INFO_COLOR, MAJOR_COLOR):
        return ON_LIGHT
    return ON_FILL if fill in (OK_COLOR, NG_COLOR, ACCENT) else ON_DARK


def verdict_mark_style(verdict: str) -> str:
    """Stylesheet of a verdict said next to a control, such as Compare's "Would be: ▲ WARN": bold text beside a bar in
    the verdict's colour, with no fill or rounded box, so that it never reads as a button. The text keeps the
    stylesheet's colour, so a theme passed to `stylesheet()` (the presenter theme, REQ-SET-008) colours it too."""
    c = VERDICT_COLORS.get(verdict, INFO_COLOR)
    return (
        f"background:transparent; font-size:{FONT_PT}pt; font-weight:700; "
        f"border:none; border-left:{MARK_W}px solid {c}; padding-left:{SPACE_S}px;"
    )


def verdict_style(verdict: str, big: bool = True) -> str:
    """Stylesheet of a verdict banner (`big`, size class V at 40 pt, 48 pt in the presenter theme) or of a one-line
    verdict label."""
    c = VERDICT_COLORS.get(verdict, INFO_COLOR)
    size = FONT_VERDICT_PT if big else FONT_PT
    return (
        f"background:{c}; color:{on_color(c)}; font-size:{size}pt; font-weight:700; "
        f"border-radius:{RADIUS}px; padding:6px; qproperty-alignment: AlignCenter;"
    )
