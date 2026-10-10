# PyInstaller spec of the Windows build: one folder, no console window (REQ-SET-012; ADR 0007). From the repository:
#
#   python -m pip install --require-hashes --no-deps -r requirements-torch-cpu.lock
#   python -m pip install --require-hashes -r requirements-build.lock
#   pyinstaller --noconfirm --clean installer/aoi.spec    ->  dist/AOI-PoC-Inspector/AOI-PoC-Inspector.exe
#
# One folder keeps the Qt libraries separate files a user can replace (Legal & Compliance, "Packaging"). The build
# stops before it ships a file from outside the app, Python and the packages whose licenses CI checks, and it writes
# THIRD_PARTY_NOTICES.txt beside the .exe for the packages it ships ("Notices shipped"). PyInstaller runs this file
# with SPECPATH, DISTPATH, workpath, Analysis, PYZ, EXE and COLLECT defined.
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))

from aoi.config import APP_NAME, APP_VERSION
from tools import third_party_notices as tpn

NAME = APP_NAME.replace(" ", "-")
UCRT = re.compile(r"^(api-ms-win-.+|ucrtbase)\.dll$", re.IGNORECASE)

# The boards `AOI-PoC-Inspector.exe --self-test` inspects (aoi/selftest.py), drawn for each build from the synthetic
# regression set's seed; in a process of its own, before PATH is narrowed below, so nothing it loads stays in this one.
SELFTEST = Path(workpath) / "selftest"
subprocess.run([sys.executable, str(ROOT / "tools" / "make_selftest_data.py"), str(SELFTEST)], check=True)

if sys.platform == "win32":
    # PyInstaller looks for a DLL that a bundled file needs beside that file and in the packages' folders, then along
    # PATH, which on a build machine also holds other programs' folders (on GitHub's runners MySQL's, Java's and
    # ImageMagick's), whose copies would ship. The build searches only Python's folder and Windows' own.
    WINDOWS = os.environ["SystemRoot"]
    os.environ["PATH"] = os.pathsep.join([sys.base_prefix, os.path.join(WINDOWS, "System32"), WINDOWS])

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "aoi" / "data" / "migrations" / "*.sql"), "aoi/data/migrations"),  # applied at start-up
        (str(SELFTEST / "*"), "selftest"),  # two synthetic boards and selftest.json, never a photograph
    ],
    # Never used by the app. Tk has no window here. setuptools comes only through torch.utils.cpp_extension, which
    # builds C++ extensions, and would pull in build tools outside the shipped set. The QtNetwork module comes only
    # through PySide6's own __init__ (for a source build's OpenSSL), and the app makes no network call (Engineering
    # standard, "Offline and least privilege"); without it PyInstaller does not look for an OpenSSL to ship.
    excludes=["tkinter", "setuptools", "pkg_resources", "distutils", "PySide6.QtNetwork"],
)
# Windows 10 and 11, the Windows the app runs on, include the Universal C Runtime and always use their own copy
# (Microsoft, "Universal CRT deployment"), so the copies PyInstaller collects are left out.
a.binaries = [entry for entry in a.binaries if not UCRT.match(Path(entry[0]).name)]

allowed = tpn.shipped([ROOT / "requirements.lock", ROOT / "requirements-torch-cpu.lock"]) | tpn.EMBEDDED_TOOLS
entries = a.pure + a.scripts + a.binaries + a.datas  # (name, source, kind); a namespace package has no file
sources = [src for _, src, kind in entries if kind != "SYMLINK" and src and Path(src).is_file()]
used, refused = tpn.bundled_packages(sources, allowed, [ROOT, Path(sys.base_prefix), Path(workpath)])
if refused:
    raise SystemExit("The build would ship files that no license check covers:\n  " + "\n  ".join(refused))
print(f"Bundled packages ({len(used)}): {', '.join(sorted(used))}")

pyz = PYZ(a.pure)
console = os.environ.get("AOI_BUILD_CONSOLE") == "1"  # only CI's rebuild after a failed start, to print the error
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=console, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)

notices = tpn.notices(used | {"pyinstaller"}, f"{APP_NAME} {APP_VERSION}")  # its bootloader is in every .exe
(Path(DISTPATH) / NAME / "THIRD_PARTY_NOTICES.txt").write_text(notices, encoding="utf-8", newline="\r\n")
