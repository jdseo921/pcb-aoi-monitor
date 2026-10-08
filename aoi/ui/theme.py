"""Industrial HMI look (spec 7): blue/gray background, 14pt sans-serif,
buttons >= 120x40, green/red/yellow status colours."""

OK_COLOR = "#43a047"
NG_COLOR = "#e53935"
WARN_COLOR = "#fdd835"
INFO_COLOR = "#90a4ae"
VERDICT_COLORS = {"OK": OK_COLOR, "NG": NG_COLOR, "WARN": WARN_COLOR, "INFO": INFO_COLOR}

QSS = """
* { font-family: "Segoe UI", "Malgun Gothic", "Noto Sans", sans-serif; font-size: 14pt; }
QMainWindow, QWidget#page, QDialog { background: #1f2a36; color: #e6edf3; }
QWidget { color: #e6edf3; }
QLabel#h1 { font-size: 20pt; font-weight: 600; }
QLabel#muted { color: #9fb0c0; font-size: 12pt; }
QFrame#header { background: #15202b; border-bottom: 1px solid #2f3e4e; }
QListWidget#nav { background: #15202b; border: none; padding-top: 8px; }
QListWidget#nav::item { padding: 14px 18px; margin: 2px 8px; border-radius: 6px; }
QListWidget#nav::item:selected { background: #1e88e5; color: white; }
QListWidget#nav::item:hover:!selected { background: #24394f; }
QListWidget#nav::item:disabled { color: #4c5c6c; }
QPushButton { background: #2d4257; border: 1px solid #3f5a75; border-radius: 6px;
              min-width: 120px; min-height: 40px; padding: 0 14px; }
QPushButton:hover { background: #36506a; }
QPushButton:disabled { color: #6c7c8c; background: #26323f; }
QPushButton#primary { background: #1e88e5; border-color: #1e88e5; font-weight: 600; }
QPushButton#start { background: #2e7d32; border-color: #2e7d32; font-weight: 600; }
QPushButton#stop { background: #c62828; border-color: #c62828; font-weight: 600; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit {
    background: #15202b; border: 1px solid #3f5a75; border-radius: 4px; min-height: 34px; padding: 0 6px; }
QTableWidget, QListWidget, QPlainTextEdit, QTextEdit {
    background: #15202b; alternate-background-color: #1a2633; gridline-color: #2f3e4e;
    border: 1px solid #2f3e4e; font-size: 12pt; }
QHeaderView::section { background: #26323f; padding: 6px; border: none; font-size: 12pt; font-weight: 600; }
QGroupBox { border: 1px solid #2f3e4e; border-radius: 6px; margin-top: 18px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9fb0c0; }
QProgressBar { border: 1px solid #3f5a75; border-radius: 4px; text-align: center; min-height: 24px; }
QProgressBar::chunk { background: #1e88e5; }
QTabWidget::pane { background: #1f2a36; border: 1px solid #2f3e4e; }
QTabWidget > QWidget, QStackedWidget > QWidget#qt_tabwidget_stackedwidget { background: #1f2a36; }
QHeaderView { background: #26323f; }
QTableCornerButton::section { background: #26323f; border: none; }
QTabBar::tab { background: #26323f; padding: 8px 18px; min-width: 120px; }
QTabBar::tab:selected { background: #1e88e5; }
QStatusBar { background: #15202b; color: #9fb0c0; }
QWidget#busy { background: rgba(15, 22, 29, 200); }
QLabel#busyText { font-size: 16pt; font-weight: 600; color: #e6edf3; }
"""


def verdict_style(verdict: str, big: bool = True) -> str:
    c = VERDICT_COLORS.get(verdict, INFO_COLOR)
    fg = "#1f2a36" if verdict == "WARN" else "white"
    size = "40pt" if big else "14pt"
    return (
        f"background:{c}; color:{fg}; font-size:{size}; font-weight:700; "
        f"border-radius:8px; padding:6px; qproperty-alignment: AlignCenter;"
    )
