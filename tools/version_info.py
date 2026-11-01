"""The VERSIONINFO resource of the Windows .exe (REQ-SET-023): what Explorer's Details tab and support read.

installer/aoi.spec passes `resource()` to PyInstaller's EXE. The numbers and strings are worked out here without
PyInstaller, so tests check them on any platform; only `resource()` imports it, in the build.
"""

from __future__ import annotations

import re
from typing import Any

PRERELEASE = 0x2  # VS_FF_PRERELEASE: a .devN, aN, bN or rcN version
OS_NT_WINDOWS32 = 0x40004
APP_FILE = 0x1


def numbers(version: str, build: int | None) -> tuple[int, int, int, int]:
    """The four 16-bit numbers Windows shows as the file version: major, minor, patch and CI's build number."""
    found = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
    if not found:
        raise ValueError(f"{version!r} does not start with major.minor.patch")
    parts = (*(int(n) for n in found.groups()), build or 0)
    if any(n > 0xFFFF for n in parts):
        raise ValueError(f"{version} build {build}: each part must fit in 16 bits")
    return parts[0], parts[1], parts[2], parts[3]


def strings(app_name: str, label: str, version: str, build: int | None) -> dict[str, str]:
    """The string table: the product's version as the log carries it, the file version as four numbers."""
    exe = app_name.replace(" ", "-")
    return {
        "FileDescription": app_name,
        "FileVersion": ".".join(str(n) for n in numbers(version, build)),
        "InternalName": exe,
        "OriginalFilename": f"{exe}.exe",
        "ProductName": app_name,
        "ProductVersion": label,
    }


def flags(version: str) -> int:
    return PRERELEASE if re.search(r"(\.dev|a|b|rc)\d+$", version) else 0


def resource(app_name: str, label: str, version: str, build: int | None) -> Any:
    """PyInstaller's VSVersionInfo for EXE(version=...); US English, Unicode."""
    from PyInstaller.utils.win32 import versioninfo as vi  # noqa: PLC0415  (only the build has PyInstaller)

    fixed = numbers(version, build)
    table = [vi.StringStruct(key, value) for key, value in strings(app_name, label, version, build).items()]
    return vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(
            filevers=fixed, prodvers=fixed, mask=0x3F, flags=flags(version), OS=OS_NT_WINDOWS32, fileType=APP_FILE
        ),
        kids=[
            vi.StringFileInfo([vi.StringTable("040904B0", table)]),
            vi.VarFileInfo([vi.VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
