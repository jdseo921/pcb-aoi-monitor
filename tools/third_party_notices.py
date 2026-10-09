"""What the Windows build may ship, and its THIRD_PARTY_NOTICES.txt (REQ-SET-012, ADR 0007).

installer/aoi.spec calls these while PyInstaller builds the app (Legal & Compliance standard, "Open-source and
third-party licenses"):

- `bundled_packages` names the installed package each bundled file comes from, and refuses a file from a package
  outside the shipped set (requirements.lock and requirements-torch-cpu.lock, whose licenses CI checks, plus
  PyInstaller's own loader and run-time hooks) or from a folder that is neither a package, the app, Python nor
  PyInstaller's work folder, such as a DLL found on the build machine's PATH. The build stops on any refusal.
- `notices` writes THIRD_PARTY_NOTICES.txt ("Notices shipped"): Qt's LGPL notice first, with where to get Qt's
  source, then for each bundled package its version, the license its metadata declares and the full text of every
  license file it installs, then Python's own license, which also covers the libraries Python bundles. The PySide6
  and Shiboken6 wheels carry no LGPL text, so the texts come from installer/licenses/.
"""

from __future__ import annotations

import importlib.metadata as md
import os
import platform
import re
import sys
import sysconfig
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from tools.check_licenses import requirements

ROOT = Path(__file__).resolve().parents[1]
GNU_TEXTS = [ROOT / "installer" / "licenses" / "LGPL-3.0.txt", ROOT / "installer" / "licenses" / "GPL-3.0.txt"]
EMBEDDED_TOOLS = {"pyinstaller", "pyinstaller-hooks-contrib"}  # their loader and run-time hooks go into the .exe
QT_PACKAGES = {"pyside6-essentials", "shiboken6"}
LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|notice|authors|copyright)", re.IGNORECASE)
# Microsoft's Visual C++ runtime (msvcp140.dll, msvcp140_atomic_wait.dll, vcruntime140_1.dll ...), which Python and
# the wheels are built against; redistributable, and covered by Python's license text on Windows. PyInstaller may
# take it from the Windows folder.
VC_RUNTIME = re.compile(r"^(msvcp|vcruntime|concrt|vcomp|vccorlib)140(_[0-9a-z]+)*\.dll$", re.IGNORECASE)
RULE = "=" * 100


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def shipped(locks: Iterable[Path]) -> set[str]:
    """The packages the lock files name for this platform: the shipped set, whose licenses CI checks."""
    return {name for lock in locks for name in requirements(lock)[0]}


def _key(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(path))


def bundled_packages(
    sources: Iterable[str],
    allowed: set[str],
    allowed_dirs: Iterable[Path],
    dists: Iterable[md.Distribution] | None = None,
) -> tuple[set[str], list[str]]:
    """The packages the bundled `sources` come from, and the files the build must not ship, each with the reason."""
    owner: dict[str, str] = {}
    sites: set[str] = {_key(sysconfig.get_path("purelib")), _key(sysconfig.get_path("platlib"))}
    for dist in md.distributions() if dists is None else dists:
        name = norm(dist.metadata["Name"])
        sites.add(_key(dist.locate_file("")))
        for f in dist.files or ():
            owner[_key(dist.locate_file(f))] = name
    dirs = [_key(d) for d in allowed_dirs]
    used: set[str] = set()
    refused: list[str] = []
    for src in sources:
        path = _key(src)
        pkg = owner.get(path)
        if pkg is not None:
            used.add(pkg)
            if pkg not in allowed:
                refused.append(f"{src}: from {pkg}, which is not in the shipped set")
        elif any(path.startswith(site + os.sep) for site in sites):
            refused.append(f"{src}: in site-packages, but no installed package lists it")
        elif not any(path.startswith(d + os.sep) for d in dirs) and not VC_RUNTIME.match(os.path.basename(path)):
            refused.append(f"{src}: from outside the app, Python and the checked packages")
    return used, refused


def declared(dist: md.Distribution) -> str:
    """The license a package's metadata declares: its SPDX expression, else its License field, else its classifiers."""
    meta = dist.metadata
    if meta["License-Expression"]:
        return str(meta["License-Expression"])
    if meta["License"] and meta["License"].strip():
        return str(meta["License"]).strip().splitlines()[0][:200]
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return "; ".join(classifiers) or "not declared"


def license_files(dist: md.Distribution) -> list[tuple[str, str]]:
    """(name, text) of every license file a package installs: those in its .dist-info folder's licenses/ folder (PEP
    639) and those named like LICENSE, COPYING, NOTICE or AUTHORS in the .dist-info folder itself."""
    found: dict[str, Path] = {}
    for f in dist.files or ():
        if len(f.parts) < 2 or not f.parts[0].endswith(".dist-info"):
            continue
        inner = f.parts[1:]
        if inner[0] == "licenses" or (len(inner) == 1 and LICENSE_FILE.match(inner[0])):
            found[str(PurePosixPath(*inner))] = Path(dist.locate_file(f))
    return [(name, path.read_text(encoding="utf-8", errors="replace")) for name, path in sorted(found.items())]


def python_license() -> str:
    """Python's LICENSE.txt: beside python.exe on Windows, in the standard library's folder elsewhere."""
    for folder in (Path(sys.base_prefix), Path(sysconfig.get_path("stdlib"))):
        if (folder / "LICENSE.txt").is_file():
            return (folder / "LICENSE.txt").read_text(encoding="utf-8", errors="replace")
    raise SystemExit(f"Python's LICENSE.txt is in neither {sys.base_prefix} nor {sysconfig.get_path('stdlib')}")


def section(title: str, license_name: str, files: list[tuple[str, str]]) -> str:
    texts = "".join(f"\n----- {name} -----\n\n{text.rstrip()}\n" for name, text in files)
    return f"\n{RULE}\n{title}\nLicense: {license_name}\n{RULE}\n{texts}"


def notices(packages: Iterable[str], app: str, dists: Iterable[md.Distribution] | None = None) -> str:
    """THIRD_PARTY_NOTICES.txt for a build that bundles `packages`; stops when one installs no license file."""
    by_name = {norm(d.metadata["Name"]): d for d in (md.distributions() if dists is None else dists)}
    qt = by_name["pyside6-essentials"].version if "pyside6-essentials" in packages else None
    out = [f"Third-party notices for {app}\n\n{app} contains the third-party software below, under its own licenses."]
    if qt is not None:
        out.append(
            f"\n\nQt and Qt for Python (PySide6 and Shiboken6) {qt} are used under the GNU Lesser General Public\n"
            "License version 3 (LGPL-3.0); its text, and the GNU General Public License version 3 it adds to, are in\n"
            "the PySide6-Essentials section below. They are the separate library files in the _internal\\PySide6 and\n"
            "_internal\\shiboken6 folders, and you may replace them with your own builds of the same version. Their\n"
            f"source code is at https://download.qt.io/ (Qt {qt} under official_releases/qt/, Qt for Python {qt}\n"
            "under official_releases/QtForPython/; a version no longer listed there is under archive/).\n"
        )
    for name in sorted(packages):
        dist = by_name[name]
        files = license_files(dist)
        if name in QT_PACKAGES:
            files += [(p.name, p.read_text(encoding="utf-8")) for p in GNU_TEXTS]
        if not files:
            raise SystemExit(f"{dist.metadata['Name']} {dist.version} installs no license file, so no notice")
        title = f"{dist.metadata['Name']} {dist.version}"
        if name in EMBEDDED_TOOLS:
            title += " (its loader and run-time hooks, embedded in the .exe)"
        out.append(section(title, declared(dist), files))
    out.append(
        section(
            f"Python {platform.python_version()} (the runtime and standard library, with the libraries it bundles)",
            "PSF-2.0, and the licenses of the bundled libraries in the text below",
            [("LICENSE.txt", python_license())],
        )
    )
    return "".join(out)
