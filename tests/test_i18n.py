"""Every visible string goes through tr() and the translation file is current (REQ-SET-005; S19, S20).

S19 covers the Page base, Home, the frame (header, sidebar, dialogs), Inspection, Compare and Logs & Export; S20
Training, AI Model Test, Settings, 3D Profile, the Recipe Editor and the scan for untranslated literals. Korean
translations themselves are a later stage: the file lists the strings.
"""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTranslator
from PySide6.QtWidgets import QPushButton

from aoi.core.inspector import Inspector
from aoi.core.recipe import Recipe
from aoi.hal import VIEWS
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import VIEW_NAMES
from aoi.ui.pages.compare import CHECK_NAMES, MODE_AI, MODES, RULES, SOURCES
from tools.update_translations import TS_FILE, qt_tool, update

PLACEHOLDER = re.compile(r"\{(\w+)(?::[^}]*)?\}")
S19_CONTEXTS = {"Page", "Role", "View", "HomePage", "MainWindow", "InspectionPage", "ComparePage", "LogsPage"}
S20_CONTEXTS = {"TrainingPage", "NgDialog", "ModelTestPage", "SettingsPage", "Profile3DPage"}


def _messages(ts: Path) -> dict[tuple[str, str], str]:
    """{(context, source): translation} of a .ts file."""
    root = ET.parse(ts).getroot()
    return {
        (c.findtext("name") or "", m.findtext("source") or ""): m.findtext("translation") or ""
        for c in root.findall("context")
        for m in c.findall("message")
    }


def test_req_set_005_translation_file_is_generated_from_the_sources(tmp_path: Path) -> None:
    """aoi/i18n/aoi_ko.ts holds exactly the strings pyside6-lupdate finds today, so a changed string without a rerun
    of tools/update_translations.py fails the build; every placeholder is a named {field}, never an f-string."""
    fresh = _messages(update(tmp_path / "fresh.ts"))
    committed = _messages(TS_FILE)
    assert set(fresh) == set(committed), "the file is stale: python tools/update_translations.py"
    assert S19_CONTEXTS | S20_CONTEXTS <= {context for context, _ in committed}
    for context, source in committed:
        assert "{self." not in source and "{len(" not in source, (context, source)
        assert all(name.isidentifier() for name in PLACEHOLDER.findall(source)), (context, source)
    assert ("Page", "Home") in committed and ("LogsPage", "Filter") in committed and ("Role", "Admin") in committed
    assert ("SettingsPage", "Version {version}") in committed and ("NgDialog", "Label NG images") in committed


def test_req_set_005_engine_names_and_camera_views_have_display_strings(tiny_model) -> None:  # type: ignore[no-untyped-def]
    """The engine names checks, their sources, rules and camera views in English and stores them; the pages show
    each through a marked display string in the translation file, so a translation never changes a stored name."""
    assert set(VIEW_NAMES) == set(VIEWS)
    recipe = Recipe(board_model=tiny_model.board_model)  # Golden board comparison and the AI check, no ROI
    res = Inspector(recipe, tiny_model.model, tiny_model.reference).inspect(tiny_model.reference)
    assert {c.name for c in res.checks} == set(CHECK_NAMES)
    assert {c.source for c in res.checks} <= set(SOURCES) and {c.rule for c in res.checks} <= set(RULES)
    listed = {source for context, source in _messages(TS_FILE) if context == "ComparePage"}
    assert set(CHECK_NAMES.values()) | set(SOURCES.values()) | set(RULES.values()) | set(MODES) <= listed


def test_req_set_005_a_translation_changes_titles_sections_roles_and_page_strings(qtbot, ctx, tmp_path: Path) -> None:
    """A .qm built from the generated file translates a page title (context Page), a sidebar section (MainWindow),
    a role name (Role), a page's own string (LogsPage), a Compare mode and a camera view; the English titles stay the
    navigation keys, the mode is still chosen by index and the view combo keeps the English key as its data."""
    wanted = {
        ("Page", "Home"): "홈",
        ("MainWindow", "DATA"): "데이터",
        ("Role", "Admin"): "관리자",
        ("LogsPage", "Filter"): "필터",
        ("ComparePage", "AI score heatmap"): "AI 점수 히트맵",
        ("View", "Top"): "상면",
    }
    tree = ET.parse(TS_FILE)
    for context in tree.getroot().findall("context"):
        for message in context.findall("message"):
            text = wanted.get((context.findtext("name"), message.findtext("source")))
            if text:
                translation = message.find("translation")
                translation.text = text
                translation.attrib.pop("type", None)  # no longer "unfinished"
    tree.write(tmp_path / "test.ts", encoding="utf-8", xml_declaration=True)
    qm = tmp_path / "test.qm"
    subprocess.run([qt_tool("pyside6-lrelease"), "-silent", str(tmp_path / "test.ts"), "-qm", str(qm)], check=True)
    translator = QTranslator()
    assert translator.load(str(qm))
    assert QCoreApplication.installTranslator(translator)
    try:
        win = MainWindow(ctx)  # an empty workspace opens as Admin
        qtbot.addWidget(win)
        texts = [win.nav.item(i).text() for i in range(win.nav.count())]
        assert "홈" in texts and "데이터" in texts and "Home" not in texts and "DATA" not in texts
        assert win.user_label.text() == "admin  ·  관리자"
        assert win.pages["Logs & Export"].findChild(QPushButton, "primary").text() == "필터"
        assert win.navigate("Logs & Export") and win.stack.currentWidget() is win.pages["Logs & Export"]
        mode = win.pages["Compare"].mode
        assert mode.itemText(MODE_AI) == "AI 점수 히트맵" and mode.count() == len(MODES)
        views = win.pages["Inspection"].view_combo
        assert views.itemText(0) == "상면" and views.itemData(0) == "Top" == VIEWS[0]
    finally:
        QCoreApplication.removeTranslator(translator)
