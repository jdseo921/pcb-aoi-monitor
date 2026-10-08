"""Regenerate aoi/i18n/aoi_ko.ts from the sources with pyside6-lupdate (REQ-SET-005).

    python tools/update_translations.py            # rewrite aoi/i18n/aoi_ko.ts
    python tools/update_translations.py out.ts     # write elsewhere (the test compares that with the committed file)

The .ts file is generated: change the strings in the sources, run this, and commit both; a test fails when the
committed file is stale. Translators fill the <translation> elements in Qt Linguist (pyside6-linguist), and
pyside6-lrelease turns the file into the .qm the app loads.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "aoi"
TS_FILE = ROOT / "aoi" / "i18n" / "aoi_ko.ts"


def qt_tool(name: str) -> str:
    """A PySide6 tool (pyside6-lupdate, pyside6-lrelease) from the interpreter's own scripts folder, or from PATH."""
    exe = Path(sys.executable).with_name(name + (".exe" if os.name == "nt" else ""))
    found = str(exe) if exe.exists() else shutil.which(name)
    if not found:
        raise FileNotFoundError(f"{name} not found: pip install -r requirements.txt")
    return found


def update(out: Path = TS_FILE) -> Path:
    """Scan every .py file under aoi/ for tr(), translate() and QT_TRANSLATE_NOOP() strings and write `out`."""
    out.parent.mkdir(parents=True, exist_ok=True)
    options = ["-extensions", "py", "-source-language", "en_US", "-target-language", "ko_KR"]
    options += ["-locations", "relative", "-no-obsolete", "-silent"]
    subprocess.run([qt_tool("pyside6-lupdate"), *options, str(SOURCES), "-ts", str(out)], check=True)
    return out


if __name__ == "__main__":
    print(update(Path(sys.argv[1]) if len(sys.argv) > 1 else TS_FILE))
