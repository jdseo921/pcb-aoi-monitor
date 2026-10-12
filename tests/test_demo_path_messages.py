"""F8 of the 2026-10 business-readiness brief, item A5: every message the 5-, 15- and 45-minute demo scripts can raise
says what happened and what to do in plain words. None names a Python exception class, quotes the system's own text (an
errno, a WinError, SQLite's words), points at a tool's file or says "Do what the reason says"; the technical words go
behind the dialog's Show Details… and into the log.

The brief's section 5 holds the banned words; it could not be read when this was written, so the four kinds Jay's
message names stand for it here, with "unhandled" and a traceback, which say nothing a user can act on."""

from __future__ import annotations

import ast
import builtins
import errno
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from aoi import errors as catalogue
from aoi.config import Settings
from aoi.core import demo
from aoi.core.anomaly import AnomalyModel, ModelFileError
from aoi.core.maps import read_map
from aoi.core.services import UNHANDLED, AppContext, ErrorReport, _not_written
from aoi.errors import CODES, AoiError, Phrase, system_detail, system_reason
from aoi.ui import demo_workspace
from aoi.ui import errors as ui_errors
from aoi.ui.errors import ErrorBox, dialog_text

ROOT = Path(__file__).resolve().parents[1]

# Every code the scripts can raise, with where they meet it (docs/demo/stage1-5min.md, -15min.md, -45min.md and
# README.md's "When something goes wrong"), as A5 walked them: each control a script presses, each message it can raise
DEMO_PATH = {
    **dict.fromkeys(
        ("AOI-SET-001", "AOI-SET-002", "AOI-SET-003", "AOI-SET-004", "AOI-SET-005", "AOI-SET-006", "AOI-SET-009"),
        "starting the demo: the workspace's database opened and upgraded",
    ),
    **dict.fromkeys(("AOI-SET-008", "AOI-SET-010"), "starting the demo, and the Presenter theme tick: settings.json"),
    **dict.fromkeys(("AOI-SET-011", "AOI-SET-012"), "starting the demo: the workspace folder and its lock"),
    "AOI-SET-007": "any action, an error without a code of its own",
    "AOI-SET-013": "any action that writes while another app holds the database",
    "AOI-SET-014": "Inspection without a board model",
    **dict.fromkeys(("AOI-SET-015", "AOI-SET-016"), "starting the demo, Load Demo Workspace and Reset Demo"),
    "AOI-SET-017": "Reset Demo",
    "AOI-USR-001": "a control the role signed in may not use",
    "AOI-USR-003": "Switch User",
    **dict.fromkeys(
        (
            "AOI-INSP-001",
            "AOI-INSP-004",
            "AOI-INSP-005",
            "AOI-INSP-006",
            "AOI-INSP-007",
            "AOI-INSP-008",
            "AOI-INSP-009",
            "AOI-INSP-010",
            "AOI-INSP-011",
            "AOI-INSP-014",
            "AOI-INSP-016",
            "AOI-TRN-001",
            "AOI-RCP-012",
        ),
        "Inspection's Start, the scripted run",
    ),  # fmt: skip
    **dict.fromkeys(("AOI-INSP-003", "AOI-INSP-012", "AOI-INSP-013"), "Inspection's alarm list"),
    **dict.fromkeys(
        ("AOI-CMP-001", "AOI-CMP-002", "AOI-CMP-003", "AOI-CMP-004", "AOI-CMP-005", "AOI-CMP-006"),
        "Compare, its heatmap and Re-evaluate",
    ),
    **dict.fromkeys(("AOI-RCP-004", "AOI-RCP-010"), "Compare's Save to Recipe"),
    **dict.fromkeys(("AOI-LOG-001", "AOI-LOG-002"), "Logs & Export's Export CSV and Export Image Overlays"),
    **dict.fromkeys(("AOI-TST-001", "AOI-TST-003"), "AI Model Test's Run Test and its preview"),
    "AOI-TRN-025": "AI Model Test and Training on a dataset store's images",
    "AOI-TRN-045": "Training's Start Training and AI Model Test's Run Test",
    **dict.fromkeys(
        ("AOI-TRN-002", "AOI-TRN-004", "AOI-TRN-005", "AOI-TRN-019", "AOI-TRN-043", "AOI-TRN-046", "AOI-TRN-047"),
        "Training's Start Training",
    ),
    **dict.fromkeys(("AOI-TRN-012", "AOI-TRN-048", "AOI-TRN-049"), "the AI Model Card, Activate Selected, Roll Back"),
    **dict.fromkeys(
        ("AOI-RCP-005", "AOI-RCP-007", "AOI-RCP-009", "AOI-RCP-013"),
        "the Recipe Editor and Learn From Labelled Boards…",
    ),
}

EXCEPTIONS = {n for n, v in vars(builtins).items() if isinstance(v, type) and issubclass(v, BaseException)}
CLASS_NAME = re.compile(r"\b[A-Z]\w*(?:Error|Exception)\b|\bBadZipFile\b")
SYSTEM_TEXT = [  # what the system says in its own words: an errno, a WinError, the C library's and SQLite's messages
    "errno", "winerror", "strerror", "permission denied", "no such file", "no space left", "access is denied",
    "being used by another process", "database is locked", "disk i/o error", "not a database", "unable to open",
    "readonly database", "traceback", "unhandled",
]  # fmt: skip
TOOL = re.compile(r"\btools[/\\]|\bpython\b|\.py\b|\bpip\b", re.IGNORECASE)
DO_WHAT = "do what the reason says"


def banned(text: str) -> list[str]:
    """What in `text` a demo's message never holds: an exception's class, the system's own text, a tool's file and
    "Do what the reason says"; [] for none."""
    found = [w for w in re.findall(r"\b\w+\b", text) if w in EXCEPTIONS]
    found += CLASS_NAME.findall(text) + TOOL.findall(text)
    found += [w for w in [*SYSTEM_TEXT, DO_WHAT] if w in text.lower()]
    return sorted(set(found))


def test_req_set_019_the_gate_sees_each_kind_of_banned_word() -> None:
    """The scan finds each kind it is for and passes plain words: a gate that finds nothing proves nothing."""
    assert banned("An unexpected error (PermissionError) stopped it") == ["PermissionError"]
    assert banned("it failed (KeyError)") == ["KeyError"]
    assert banned("the zip is a BadZipFile") == ["BadZipFile"]
    assert banned("[Errno 28] No space left on device") == ["errno", "no space left"]
    held = "[WinError 32] The process cannot access the file because it is being used by another process"
    assert banned(held) == ["WinError", "being used by another process", "winerror"]
    assert banned("database is locked") == ["database is locked"]
    assert banned("run python tools/make_demo_bundle.py") == [".py", "python", "tools/"]
    assert banned("Do what the reason says, then try again.") == [DO_WHAT]
    assert banned("stopped the last action (unhandled).") == ["unhandled"]
    plain = "The export E:/report.csv could not be written: the drive is full. Close any app that has the file open."
    assert banned(plain) == []


def test_req_set_019_the_demo_path_codes_are_in_the_catalogue() -> None:
    """Each code listed is one the catalogue holds: a code renamed or removed fails here, not silently."""
    assert set(DEMO_PATH) <= set(CODES), sorted(set(DEMO_PATH) - set(CODES))


@pytest.mark.parametrize("code", sorted(DEMO_PATH))
def test_req_set_019_a_demo_path_message_names_no_class_system_text_or_tool(code: str) -> None:
    """A demo-path code's title, what happened and what to do, as the catalogue and docs/error-codes.md hold them."""
    entry = CODES[code]
    for text in (entry.title, entry.what, entry.action):
        assert banned(text) == [], (code, DEMO_PATH[code], text)
    assert "error_type" not in entry.what, code  # a {placeholder} for the class of an exception


def test_req_set_019_no_message_says_do_what_the_reason_says() -> None:
    """No code at all, on the demo path or not, leaves the user to work out the step from the reason."""
    assert [c.code for c in CODES.values() if DO_WHAT in f"{c.what} {c.action}".lower()] == []


def _error_phrases() -> Iterator[str]:
    """Every phrase marked under the "Errors" context in aoi/ (the reasons that fill a code's {placeholders}), as
    pyside6-lupdate finds it, by the call's name."""
    for path in sorted((ROOT / "aoi").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", "")) == "QT_TRANSLATE_NOOP"
                and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "Errors"
                and isinstance(node.args[1], ast.Constant)
            ):
                yield str(node.args[1].value)


def test_req_set_019_no_reason_names_a_class_system_text_or_tool() -> None:
    """Every reason a code is filled with, from the engine, the data layer and the screens."""
    phrases = [p for p in _error_phrases() if p != UNHANDLED]  # the log's context alone: ErrorReport.of drops it
    assert len(phrases) > 100  # the walk found them
    assert {p: banned(p) for p in phrases if banned(p)} == {}


ERROR_CLASSES = {"AoiError", "WorkspaceError", "MigrationError", "ModelFileError"}
RAW = {"str", "repr", "format"}  # calls that turn an exception into its own words
RAW_ATTRS = {"strerror", "msg", "__name__", "args"}


def _raw_value(node: ast.AST, caught: set[str], assigned: dict[str, list[ast.AST]], seen: set[str]) -> str | None:
    """How `node`, a value a code's {placeholder} is filled with, puts an exception's own words in the message, or None:
    str(e) or repr(e), e.strerror or e.msg, type(e).__name__, e in an f-string, system_detail(e); a name is followed to
    what is assigned to it in the same function."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in RAW_ATTRS:
            return ast.unparse(sub)
        if isinstance(sub, ast.Call) and getattr(sub.func, "id", "") == "system_detail":
            return ast.unparse(sub)
        if isinstance(sub, ast.Call) and getattr(sub.func, "id", "") in RAW:
            if any(isinstance(a, ast.Name) and a.id in caught for a in sub.args):  # str(e), not str(e.filename)
                return ast.unparse(sub)
        if isinstance(sub, ast.FormattedValue) and isinstance(sub.value, ast.Name) and sub.value.id in caught:
            return ast.unparse(sub)
        if isinstance(sub, ast.Name) and sub.id in caught and node is sub:
            return sub.id
        if isinstance(sub, ast.Name) and sub.id in assigned and sub.id not in seen:
            for value in assigned[sub.id]:
                found = _raw_value(value, caught, assigned, seen | {sub.id})
                if found:
                    return f"{sub.id} = {found}"
    return None


def _raw_fills(tree: ast.AST) -> Iterator[tuple[int, str, str, str]]:
    """(line, code, placeholder, how) for each coded error built in `tree` with a demo-path code whose placeholder is
    filled with an exception's own words; its detail, which the log and the dialog's Details hold, may be."""
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        caught = {h.name for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler) and h.name}
        assigned: dict[str, list[ast.AST]] = {}
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        assigned.setdefault(t.id, []).append(n.value)
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") in ERROR_CLASSES and call.args):
                continue
            code = call.args[0]
            if not (isinstance(code, ast.Constant) and code.value in DEMO_PATH):
                continue
            for kw in call.keywords:
                how = None if kw.arg in (None, "detail") else _raw_value(kw.value, caught, assigned, set())
                if how and kw.arg:
                    yield call.lineno, str(code.value), kw.arg, how


def test_req_set_019_no_demo_path_error_is_filled_with_the_exceptions_own_words() -> None:
    """Where the code raises a demo-path code, its {placeholders} hold plain words: `system_reason(e)` for what the
    system refused, never str(e), e.strerror or the exception's class, which go to its detail."""
    found = [
        (path.relative_to(ROOT).as_posix(), *hit)
        for path in sorted((ROOT / "aoi").rglob("*.py"))
        for hit in _raw_fills(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert found == []


def test_req_set_019_the_gate_finds_an_exceptions_words_in_a_placeholder() -> None:
    """The AST scan finds each way an exception's words reached a message before A5."""
    source = """
def f(path):
    try:
        pass
    except OSError as e:
        raise AoiError("AOI-LOG-002", path=path, reason=e.strerror or str(e))
    except ValueError as e:
        why = f"it broke: {e}"
        raise AoiError("AOI-SET-010", path=path, reason=why)
    except Exception as e:
        raise AoiError("AOI-SET-007", error_type=type(e).__name__)
    except KeyError as e:
        raise AoiError("AOI-SET-013", detail=str(e), path=path, error=repr(e))
"""
    hits = [(code, placeholder) for _line, code, placeholder, _how in _raw_fills(ast.parse(source))]
    assert hits == [
        ("AOI-LOG-002", "reason"),
        ("AOI-SET-010", "reason"),
        ("AOI-SET-007", "error_type"),
        ("AOI-SET-013", "error"),
    ], hits


def _os_error(number: int, words: str, winerror: int | None = None) -> OSError:
    e = OSError(number, words, "E:/report.csv")
    if winerror is not None:  # as Windows sets it; a test on Linux sets it by hand
        e.winerror = winerror  # type: ignore[attr-defined]
    return e


SYSTEM_REFUSALS = [  # (the system's refusal, the plain reason a message gives for it)
    (_os_error(errno.ENOSPC, "No space left on device"), catalogue.FULL),
    (_os_error(errno.EACCES, "Permission denied"), catalogue.DENIED),
    (_os_error(errno.ENOENT, "No such file or directory"), catalogue.MISSING),
    (_os_error(errno.EROFS, "Read-only file system"), catalogue.WRITE_PROTECTED),
    (_os_error(errno.EIO, "Input/output error"), catalogue.NOT_READ),
    (_os_error(errno.ENAMETOOLONG, "File name too long"), catalogue.TOO_LONG),
    (_os_error(errno.EEXIST, "File exists"), catalogue.TAKEN),
    (_os_error(errno.EISDIR, "Is a directory"), catalogue.A_FOLDER),
    (_os_error(errno.ENOTDIR, "Not a directory"), catalogue.NOT_A_FOLDER),
    (_os_error(errno.EACCES, "The process cannot access the file because it is being used by another process", 32),
     catalogue.IN_USE),
    (_os_error(errno.ENOENT, "The device is not ready", 21), catalogue.NOT_READY),
    (_os_error(errno.ENOSPC, "There is not enough space on the disk", 112), catalogue.FULL),
    (_os_error(errno.EACCES, "Access is denied", 5), catalogue.DENIED),
    (_os_error(errno.EROFS, "The media is write protected", 19), catalogue.WRITE_PROTECTED),
    (OSError("a refusal with no errno"), catalogue.REFUSED),
    (sqlite3.OperationalError("database is locked"), catalogue.DB_HELD),
    (sqlite3.DatabaseError("file is not a database"), catalogue.DB_DAMAGED),
    (sqlite3.DatabaseError("database disk image is malformed"), catalogue.DB_DAMAGED),
    (sqlite3.OperationalError("disk I/O error"), catalogue.NOT_READ),
    (sqlite3.OperationalError("database or disk is full"), catalogue.FULL),
    (sqlite3.OperationalError("unable to open database file"), catalogue.DB_NOT_OPENED),
    (sqlite3.OperationalError("attempt to write a readonly database"), catalogue.WRITE_PROTECTED),
    (sqlite3.OperationalError("no such table: inspections"), catalogue.DB_REFUSED),
    (RuntimeError("anything else"), catalogue.REFUSED),
]  # fmt: skip


@pytest.mark.parametrize(("refusal", "reason"), SYSTEM_REFUSALS, ids=lambda v: str(v)[:40])
def test_req_set_019_a_system_refusal_reads_as_plain_words(refusal: BaseException, reason: Phrase) -> None:
    """`system_reason` says what the refusal means for the user, in words the scan passes; `system_detail` keeps the
    class and the system's text for the log and the dialog's Details."""
    plain = system_reason(refusal)
    assert isinstance(plain, Phrase) and plain.context == "Errors" and plain == reason
    assert banned(plain) == [] and str(refusal) not in plain
    assert system_detail(refusal) == f"{type(refusal).__name__}: {refusal}"


def _shown(report: ErrorReport) -> tuple[str, str, str]:
    """(title, text, details) of the error dialog for `report`, as the user reads it."""
    box = ErrorBox(None, report)
    try:
        assert box.standardButtons() == QMessageBox.StandardButton.Ok
        return box.windowTitle(), box.text(), box.detailedText()
    finally:
        box.deleteLater()


def test_req_set_019_an_unexpected_error_shows_its_class_only_behind_details(qtbot: QtBot) -> None:
    """AOI-SET-007, from any action or no handler at all: the message says an unexpected error stopped it, and where
    when that is a page; the class and the exception's text are behind Show Details…, never "unhandled"."""
    for context, where in ((UNHANDLED, "."), ("Compare", " (Compare)."), ("", ".")):
        title, text, details = _shown(ErrorReport.of(RuntimeError("secret detail"), context))
        assert title == "AOI-SET-007 Unexpected error"
        assert text.startswith(f"An unexpected error stopped the last action{where}\n\n"), text
        assert banned(text) == [] and "secret detail" not in text
        assert details == "RuntimeError: secret detail"


def test_req_set_019_a_full_drive_reads_as_a_full_drive(qtbot: QtBot, tmp_path: Path) -> None:
    """AOI-LOG-002 on Export CSV to a full stick: "the drive is full", the system's words behind Show Details…"""
    target = tmp_path / "report.csv"
    error = _not_written(_os_error(errno.ENOSPC, "No space left on device"), target)
    _title, text, details = _shown(ErrorReport.of(error))
    assert f"The export {target} could not be written: the drive is full." in text and banned(text) == []
    assert details == "OSError: [Errno 28] No space left on device: 'E:/report.csv'"


def test_req_set_019_a_database_another_app_holds_says_so(qtbot: QtBot, ctx: AppContext) -> None:
    """AOI-SET-013 for a write the database refuses as locked: the message names the database and the other app,
    SQLite's words are behind Show Details… and in the log."""
    held = sqlite3.OperationalError("database is locked")
    held.sqlite_errorcode = sqlite3.SQLITE_BUSY  # type: ignore[attr-defined]  # as SQLite sets it
    report = ctx.report_error(held, "Settings")
    title, text, details = _shown(report)
    assert title == "AOI-SET-013 Workspace database busy" and banned(text) == []
    assert details == "OperationalError: database is locked"


def test_req_set_019_a_settings_file_that_is_not_json_says_where(tmp_path: Path) -> None:
    """AOI-SET-010 at the demo's start: the line and column, not the parser's words, which go to the detail."""
    Settings._file().parent.mkdir(parents=True, exist_ok=True)
    Settings._file().write_text('{"presenter_theme": tru}', encoding="utf-8")
    with pytest.raises(AoiError) as e:
        Settings.load()
    assert e.value.code == "AOI-SET-010" and "(line 1, column 21)" in e.value.what
    assert banned(e.value.what) == [] and "Expecting value" not in e.value.what
    assert e.value.detail is not None and e.value.detail.startswith("JSONDecodeError: Expecting value")


def test_req_set_019_an_ai_model_file_that_cannot_be_read_names_no_class(tmp_path: Path) -> None:
    """AOI-TRN-001 at Start for a model file cut short, a file that is no model at all, or a folder: plain words."""
    garbage, folder = tmp_path / "cut.pt", tmp_path / "folder.pt"
    garbage.write_bytes(b"PK\x03\x04 not a whole zip")
    folder.mkdir()
    for path in (garbage, folder, tmp_path / "gone.pt"):
        with pytest.raises(ModelFileError) as e:
            AnomalyModel.load(path, device="cpu")
        assert e.value.code == "AOI-TRN-001" and banned(e.value.what) == [], e.value.what
        assert e.value.detail and ":" in e.value.detail, path  # the class and the reader's words, for the log


def test_req_set_019_a_stored_map_that_cannot_be_read_says_why(tmp_path: Path) -> None:
    """AOI-CMP-003 on Compare for a map the system refuses (a folder of its name): what the refusal means, "it is a
    folder, not a file" on Linux, never "IsADirectoryError" or "Permission denied"."""
    folder = tmp_path / "board_diff.png"
    folder.mkdir()
    with pytest.raises(AoiError) as e:
        read_map(folder)
    assert e.value.code == "AOI-CMP-003" and banned(e.value.what) == [], e.value.what
    assert system_reason(e.value.__cause__) in e.value.what and e.value.detail == system_detail(e.value.__cause__)


def test_req_set_019_a_demo_bundle_file_that_cannot_be_read_is_set_015(
    demo_bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reset Demo and Load Demo Workspace with a file of the installed bundle the system refuses: AOI-SET-015, which
    says to reinstall the app, never an uncoded error or a tool to run."""

    def refuse(_folder: Path) -> dict[str, str]:
        raise PermissionError(errno.EACCES, "Permission denied", str(demo_bundle / "boards" / "board_01.png"))

    monkeypatch.setattr(demo, "file_hashes", refuse)
    with pytest.raises(AoiError) as e:
        demo.read_bundle(demo_bundle)
    assert e.value.code == "AOI-SET-015" and banned(f"{e.value.what} {e.value.action}") == []
    assert "Reinstall the app" in e.value.action and catalogue.DENIED in e.value.what
    assert e.value.detail is not None and e.value.detail.startswith("PermissionError: [Errno 13] Permission denied")


def test_req_set_019_an_uncoded_error_starting_the_demo_is_one_plain_dialog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`main.py --demo` when loading the demo raises an error without a code (a folder that cannot be written): one
    AOI-SET-007 dialog in plain words, the class behind Show Details… and the trace in the default workspace's log;
    never the traceback a frozen build shows for an error that leaves `main`."""
    shown: list[ErrorReport] = []
    logged: list[BaseException] = []
    monkeypatch.setattr(demo_workspace, "show_error", lambda _parent, report: shown.append(report))
    monkeypatch.setattr(demo_workspace, "log_start_failure", logged.append)

    def refuse(_settings: Settings) -> Path:
        raise PermissionError(errno.EACCES, "Permission denied", str(tmp_path / "AOI_Workspace-Demo"))

    monkeypatch.setattr(demo, "load_beside", refuse)
    assert demo_workspace.open_demo() is None
    assert [r.code for r in shown] == ["AOI-SET-007"] and len(logged) == 1
    _title, text = dialog_text(shown[0])
    assert banned(text) == [] and "(start-up)" in text
    assert shown[0].detail.startswith("PermissionError: [Errno 13] Permission denied")


def test_req_set_019_the_dialog_shows_a_coded_errors_detail(qtbot: QtBot) -> None:
    """A coded error's detail, or the system error that caused it, is behind Show Details…; none, no Details."""
    with_detail = AoiError("AOI-LOG-002", "OSError: [Errno 28] No space left", path="E:/a.csv", reason=catalogue.FULL)
    assert _shown(ErrorReport.of(with_detail))[2] == "OSError: [Errno 28] No space left"
    caused = AoiError("AOI-SET-014", page="Inspection")
    caused.__cause__ = sqlite3.OperationalError("disk I/O error")
    assert _shown(ErrorReport.of(caused))[2] == "OperationalError: disk I/O error"
    assert _shown(ErrorReport.of(AoiError("AOI-SET-014", page="Inspection")))[2] == ""


def test_req_set_019_show_error_is_the_error_box(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every page's error goes through `show_error`, and it builds the one dialog with Details."""
    built: list[ErrorBox] = []
    monkeypatch.setattr(ErrorBox, "exec", lambda self: built.append(self) or 0)
    ui_errors.show_error(None, ErrorReport.of(RuntimeError("x")))
    assert len(built) == 1 and built[0].detailedText() == "RuntimeError: x"
    built[0].deleteLater()


def test_req_set_019_error_codes_md_holds_the_plain_texts() -> None:
    """docs/error-codes.md, generated from the catalogue, holds no banned word for a demo-path code either."""
    doc = (ROOT / "docs" / "error-codes.md").read_text(encoding="utf-8")
    rows = {line.split(" | ")[0].strip("| "): line for line in doc.splitlines() if line.startswith("| AOI-")}
    assert {code: banned(rows[code]) for code in DEMO_PATH if banned(rows[code])} == {}
