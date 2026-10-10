"""The Windows build ships only checked packages, with their notices (REQ-SET-012, ADR 0007).

tools/third_party_notices.py is what installer/aoi.spec runs while PyInstaller builds the app; these tests give it
packages installed in a temporary folder.
"""

from __future__ import annotations

import importlib.metadata as md
from pathlib import Path

import pytest

from tools import third_party_notices as tpn


def install(site: Path, name: str, version: str, info: dict[str, str], declared: str = "MIT") -> None:
    """A package with one module, and the given files in its .dist-info folder, as pip leaves it."""
    dist_info = f"{name}-{version}.dist-info"
    files = {f"{name.lower()}/__init__.py": "", **{f"{dist_info}/{rel}": text for rel, text in info.items()}}
    files[f"{dist_info}/METADATA"] = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\nLicense: {declared}\n"
    files[f"{dist_info}/RECORD"] = "".join(f"{rel},,\n" for rel in [*files, f"{dist_info}/RECORD"])
    for rel, text in files.items():
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        (site / rel).write_text(text, encoding="utf-8")


def installed(site: Path) -> list[md.Distribution]:
    return list(md.distributions(path=[str(site)]))


@pytest.fixture
def site(tmp_path: Path) -> Path:
    site = tmp_path / "site-packages"
    install(site, "shipped", "1.0", {"licenses/LICENSE": "the shipped package's license"})
    install(site, "tool", "2.0", {"LICENSE.txt": "the tool's license"})
    (site / "stray.dll").write_bytes(b"")  # in site-packages, but no package lists it
    return site


def test_req_set_012_a_file_from_an_unchecked_package_or_elsewhere_stops_the_build(site: Path, tmp_path: Path) -> None:
    app, elsewhere = tmp_path / "app", tmp_path / "Program Files" / "Git" / "bin"
    runtime = [elsewhere / "VCRUNTIME140_1.dll", elsewhere / "MSVCP140_ATOMIC_WAIT.dll"]  # Microsoft's, from anywhere
    sources = [site / "shipped/__init__.py", app / "main.py", *runtime]
    refusals = [site / "tool/__init__.py", site / "stray.dll", elsewhere / "zlib1.dll"]
    used, refused = tpn.bundled_packages(map(str, sources + refusals), {"shipped"}, [app], installed(site))
    assert used == {"shipped", "tool"}
    assert refused == [
        f"{refusals[0]}: from tool, which is not in the shipped set",
        f"{refusals[1]}: in site-packages, but no installed package lists it",
        f"{refusals[2]}: from outside the app, Python and the checked packages",
    ]


def test_req_set_012_the_notices_hold_every_license_text_and_python_s(site: Path) -> None:
    text = tpn.notices({"shipped", "tool"}, "AOI PoC Inspector 0.2.0", installed(site))
    assert text.startswith("Third-party notices for AOI PoC Inspector 0.2.0")
    assert "shipped 1.0\nLicense: MIT\n" in text and "the shipped package's license" in text
    assert "----- LICENSE.txt -----\n\nthe tool's license" in text
    assert "\nPython 3." in text and "PYTHON SOFTWARE FOUNDATION LICENSE" in text  # the runtime's own, last
    assert "Qt and Qt for Python" not in text  # no Qt here, so no Qt notice
    install(site, "bare", "3.0", {}, declared="BSD")
    with pytest.raises(SystemExit, match="bare 3.0 installs no license file"):
        tpn.notices({"bare"}, "app", installed(site))


def test_req_set_012_qt_gets_the_lgpl_notice_and_the_texts_its_wheels_lack(site: Path) -> None:
    lgpl = "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"
    install(site, "PySide6_Essentials", "6.11.2", {"licenses/LicenseRef-Qt-Commercial.txt": "see qt.io"}, lgpl)
    text = tpn.notices({"pyside6-essentials"}, "app", installed(site))
    assert "Qt and Qt for Python (PySide6 and Shiboken6) 6.11.2 are used under the GNU Lesser General" in text
    assert "you may replace them with your own builds of the same version" in text
    assert "GNU LESSER GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007" in text
    assert "GNU GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007" in text


def test_req_set_012_the_notices_carry_inno_setup_s_license_for_the_installer(site: Path) -> None:
    """The installer's setup program and the uninstaller it leaves beside the .exe are Inno Setup's, under its own
    license, which asks that its copyright notice stays in every copy (ADR 0007, update of S57)."""
    text = tpn.notices({"shipped"}, "app", installed(site))
    assert f"\nInno Setup {tpn.INNO_SETUP_VERSION} (the installer's setup program and its uninstaller, unins000" in text
    assert "Permission is granted to anyone to use this software for any purpose, including commercial" in text
    assert "Copyright (C) 1997-2026 Jordan Russell. All rights reserved." in text
    assert text.index("\nInno Setup ") < text.index("\nPython 3.")  # Python's own license stays last
