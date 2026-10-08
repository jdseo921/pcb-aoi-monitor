"""Every colour, point size and size class the screens use (REQ-SET-004; Engineering standard, "Look" and "Sizes").

Screens take tokens from here and never write a colour or a point size of their own, so a theme change (the light
presenter theme, REQ-SET-008) is one file, and `tests/test_screen_rules.py` fails the build on a colour literal
anywhere else under aoi/ui. The verdict and severity colours are the standard's, and a verdict is always shown as
its colour with a word and a shape (REQ-INSP-002), never as colour alone.

Contrast, by the WCAG 2.1 formula (tests/screens measures it on every rendered page): every text colour on its
surface reads at 4.5:1 or more, except white on the standard's OK green (3.3:1), NG red (4.2:1) and accent blue
(3.7:1). Those three fills carry only bold or 40 pt text (the verdict banner, coloured cells, the primary, Start and
Stop buttons, a progress bar's percentage), for which WCAG AA asks 3:1; whether the standard's "4.5:1" allows that
reading is open with Jay. The 22 pt bold number on a Home card, ACCENT on BG_RAISED (3.5:1), takes the same reading
(#240). The selected sidebar entry, tab and row, and selected text, whose text is not bold, sit on BG_SELECTED instead
(5.7:1). A disabled control is exempt (WCAG 1.4.3), and every disabled button, coloured or not, greys out to BG_RAISED
and TEXT_DISABLED, so it never looks ready to press. The lists, calendars and menus that open as windows of their own
are themed here too, never left on the platform's light background, and the calendar's bar stays BG_SELECTED, on which
Qt's dark month arrows read at 3.4:1 (#239); the sidebar greys a page the role may not open on the item itself, since a
rule for disabled items would also grey its headings.
"""

from string import Template

# Verdicts and severities (Engineering standard, "Look"); the shapes pair with the words (REQ-INSP-002)
OK_COLOR = "#43a047"
NG_COLOR = "#e53935"
WARN_COLOR = "#fdd835"
INFO_COLOR = "#90a4ae"
MAJOR_COLOR = "#fb8c00"  # severity Major, between Critical (NG red) and Minor (WARN amber)
ACCENT = "#1e88e5"  # the one primary button on a page, progress
VERDICT_COLORS = {"OK": OK_COLOR, "NG": NG_COLOR, "WARN": WARN_COLOR, "INFO": INFO_COLOR}
VERDICT_SHAPES = {"OK": "✓", "NG": "✗", "WARN": "▲", "INFO": "·"}
SEVERITY_COLORS = {"Critical": NG_COLOR, "Major": MAJOR_COLOR, "Minor": WARN_COLOR}
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
BG_BUSY = "rgba(15, 22, 29, 200)"
LINE, LINE_STRONG = "#2f3e4e", "#3f5a75"
TEXT, TEXT_MUTED, TEXT_DISABLED = "#e6edf3", "#9fb0c0", "#6c7c8c"
ON_LIGHT = BG  # text on amber
ON_DARK = "#ffffff"  # text on green, red and blue fills
PRINT_TEXT = "#000000"  # text in a PDF report, on paper

# Point sizes, never below FONT_PT, and pixel sizes (Engineering standard, "Sizes"; the sketches' size classes)
FONT_FAMILY = '"Segoe UI", "Malgun Gothic", "Noto Sans", sans-serif'  # the screenshot tests pin one font instead
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
WHY_MIN_H = 60  # Compare's "why" box gives way to two lines before a row of Try other thresholds is squeezed
NAV_W, HEADER_H, FIELD_W, CARD_W = 250, 64, 240, 720
IMAGE_MIN_W, IMAGE_MIN_H, PROGRESS_W = 320, 240, 360
SPACE, SPACE_S = 14, 8  # between blocks; inside a block
RADIUS, RADIUS_L = 6, 10

TOKENS = {k: v for k, v in dict(globals()).items() if k.isupper()}

_QSS = Template("""
* { font-family: ${FONT_FAMILY}; font-size: ${FONT_PT}pt; selection-background-color: $BG_SELECTED;
    selection-color: $ON_DARK; }
QMainWindow, QWidget#page, QDialog { background: $BG; color: $TEXT; }
QWidget { color: $TEXT; }
QLabel#h1 { font-size: ${FONT_H1_PT}pt; font-weight: 600; }
QLabel#muted { color: $TEXT_MUTED; }
QLabel#logo, QLabel#busyText { font-size: ${FONT_LARGE_PT}pt; font-weight: 600; }
QLabel#tile { background: $BG_RAISED; border-radius: ${RADIUS_L}px; padding: ${SPACE_S}px; }
QFrame#header { background: $BG_DEEP; border-bottom: 1px solid $LINE; }
QFrame#card { background: $BG_RAISED; border-radius: ${RADIUS_L}px; }
QWidget#empty { background: $BG_DEEP; border: 1px dashed $LINE_STRONG; border-radius: ${RADIUS_L}px; }
QLabel#emptyHeading { font-size: ${FONT_LARGE_PT}pt; font-weight: 600; }
QListWidget#nav { background: $BG_DEEP; border: none; padding-top: ${SPACE_S}px; }
QListWidget#nav::item { padding: ${SPACE}px 18px; margin: 2px ${SPACE_S}px; border-radius: ${RADIUS}px; }
QListWidget#nav::item:selected { background: $BG_SELECTED; color: $ON_DARK; }
QListWidget#nav::item:hover:!selected { background: $BG_NAV_HOVER; }
QPushButton { background: $BG_BUTTON; border: 1px solid $LINE_STRONG; border-radius: ${RADIUS}px;
              min-width: ${BUTTON_W}px; min-height: ${BUTTON_H}px; padding: 0 ${SPACE}px; }
QPushButton:hover { background: $BG_BUTTON_HOVER; }
QPushButton[sizeClass="T"], QComboBox[sizeClass="T"] { min-height: ${TARGET_H}px; }
QPushButton[sizeClass="T+"] { min-height: ${RUN_CONTROL_H}px; }
QCheckBox[sizeClass="F"] { min-height: ${FIELD_H}px; }
QPushButton:disabled { color: $TEXT_DISABLED; background: $BG_RAISED; }
QPushButton#primary, QPushButton#start, QPushButton#stop, QPushButton#danger { color: $ON_DARK; font-weight: 700; }
QPushButton#primary { background: $ACCENT; border-color: $ACCENT; }
QPushButton#start { background: $OK_COLOR; border-color: $OK_COLOR; }
QPushButton#stop, QPushButton#danger { background: $NG_COLOR; border-color: $NG_COLOR; }
QPushButton#primary:disabled, QPushButton#start:disabled, QPushButton#stop:disabled, QPushButton#danger:disabled {
    color: $TEXT_DISABLED; background: $BG_RAISED; border-color: $LINE_STRONG; font-weight: normal; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit {
    background: $BG_DEEP; border: 1px solid $LINE_STRONG; border-radius: 4px; min-height: ${FIELD_H}px;
    padding: 0 6px; }
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
QHeaderView::section { background: $BG_RAISED; padding: 6px; border: none; font-weight: 600; }
QGroupBox { border: 1px solid $LINE; border-radius: ${RADIUS}px; margin-top: 18px; padding-top: ${SPACE_S}px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: $TEXT_MUTED; }
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
""")


def stylesheet(**overrides: object) -> str:
    """The application stylesheet built from the tokens; `overrides` serve another theme (REQ-SET-008)."""
    return _QSS.substitute({**TOKENS, **overrides})


QSS = stylesheet()


def verdict_label(verdict: str) -> str:
    """The verdict as a shape and a word, "✗ NG", so colour is never the only cue (REQ-INSP-002)."""
    return f"{VERDICT_SHAPES.get(verdict, VERDICT_SHAPES['INFO'])} {verdict}"


def on_color(fill: str) -> str:
    """The text colour that reads on `fill`: dark on amber, grey and orange (5.6:1 or more), white on green, red and
    blue (where white measures 3.3:1 to 4.2:1, so the text there is bold or 40 pt; see the module docstring)."""
    return ON_LIGHT if fill in (WARN_COLOR, INFO_COLOR, MAJOR_COLOR) else ON_DARK


def verdict_style(verdict: str, big: bool = True) -> str:
    """Stylesheet of a verdict banner (`big`, size class V at 40 pt) or of a one-line verdict label."""
    c = VERDICT_COLORS.get(verdict, INFO_COLOR)
    size = FONT_VERDICT_PT if big else FONT_PT
    return (
        f"background:{c}; color:{on_color(c)}; font-size:{size}pt; font-weight:700; "
        f"border-radius:{RADIUS}px; padding:6px; qproperty-alignment: AlignCenter;"
    )
