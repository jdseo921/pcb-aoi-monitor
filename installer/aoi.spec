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
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))

from aoi.config import APP_NAME, APP_VERSION
from tools import third_party_notices as tpn

NAME = APP_NAME.replace(" ", "-")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "aoi" / "data" / "migrations" / "*.sql"), "aoi/data/migrations")],  # applied at start-up
    # Never used by the app: Tk has no window here, and setuptools comes only through torch.utils.cpp_extension,
    # which builds C++ extensions; left in, they would pull in build tools that are not in the shipped set.
    excludes=["tkinter", "setuptools", "pkg_resources", "distutils"],
)

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
