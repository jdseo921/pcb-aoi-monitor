"""The UI language (REQ-SET-006, REQ-SET-028): the translator of the language settings.json names, loaded once at
start-up from the .qm file shipped beside the translation source, before any window or dialog is built. English is
the sources' own language and needs none. A language whose file is missing or will not load leaves the UI in English
and says so in the return value; nothing else depends on it, as the engine stores its names in English."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTranslator

FOLDER = Path(__file__).resolve().parents[1] / "i18n"  # in a build too: aoi/i18n beside the app's own files
SOURCE_LANGUAGE = "en"


def qm_file(language: str) -> Path:
    """The compiled translation of `language` (tools/update_translations.py --release writes it from the .ts)."""
    return FOLDER / f"aoi_{language}.qm"


_installed: list[QTranslator] = []  # the translator in use, kept alive here; at most one


def install(app: object, language: str) -> bool:
    """Load `language` into the running app; True when the UI now shows in it. A second call replaces the first one's
    language. `app` is the QApplication main.py made, named so that the call reads in order there; the translator is
    Qt's application-wide one."""
    del app
    while _installed:
        QCoreApplication.removeTranslator(_installed.pop())
    if language == SOURCE_LANGUAGE:
        return True
    translator = QTranslator()
    if not translator.load(str(qm_file(language))) or not QCoreApplication.installTranslator(translator):
        return False
    _installed.append(translator)
    return True
