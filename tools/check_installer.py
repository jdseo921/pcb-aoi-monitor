#!/usr/bin/env python
"""Install the built installer silently, self-test the installed app, uninstall it (REQ-SET-012, S57; build.yml).

    python tools/check_installer.py dist/installer/AOI-PoC-Inspector-0.2.0-setup-x64-unsigned.exe

On Windows, with admin rights, for CI's runner:

1. The installer runs with /VERYSILENT /SUPPRESSMSGBOXES /NORESTART into a new temporary folder (/DIR), with the
   optional desktop shortcut chosen (/TASKS=desktopicon). It passes when it exits 0 and the folder holds the .exe, a
   GUI program that opens no console window, with THIRD_PARTY_NOTICES.txt, sbom.cdx.json and the uninstaller beside
   it; when the Start menu holds the app's shortcut and the Demo shortcut, which starts the .exe with --demo, and the
   desktop the app's shortcut; and when Windows lists the app as installed.
2. The installed .exe runs `--self-test` on a new folder, as tools/smoke_test_build.py does with the build: exit 0
   with the verdict the synthetic regression set expects.
3. The uninstaller runs with /VERYSILENT /SUPPRESSMSGBOXES /NORESTART. It passes when it exits 0 and the program
   files, the shortcuts and the uninstall entry are gone, while the user's workspace and the demo workspace beside it
   (by default %USERPROFILE%\\AOI_Workspace, with settings.json, and AOI_Workspace-Demo) hold the same files as before
   the install. Where those folders do not exist, as on CI's runner, the check first makes them with a settings.json
   and a database file of its own, which the installer did not create, and removes them at the end; folders that
   exist are only read.

It refuses to run where the app is installed already, as a second install would take over that install's entry in
Installed apps. The setup and uninstall logs are printed after a failure. Exit 0 on a pass, 1 on a failure, 2 off
Windows, without an installer file or where the app is installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script: the repository root holds the ``aoi`` and ``tools`` packages
    sys.path.insert(0, str(ROOT))

from aoi.config import APP_NAME, default_workspace  # noqa: E402 (the app's own rule for the workspace folder)
from aoi.core.demo import demo_folder  # noqa: E402
from tools.smoke_test_build import GUI, log_lines, self_test, subsystem  # noqa: E402

ISS = ROOT / "installer" / "aoi.iss"
EXE = APP_NAME.replace(" ", "-") + ".exe"
QUIET = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
TIMEOUT = 900  # seconds an install or uninstall may take: about 660 MB of files, which antivirus reads on a runner
SHORTCUTS = {f"{APP_NAME}.lnk": "", f"{APP_NAME} (Demo).lnk": "--demo"}  # in the Start menu: the .exe's arguments


def app_id(iss: Path = ISS) -> str:
    """The installer's AppId, the name of its uninstall entry in the registry ("{GUID}_is1")."""
    found = re.search(r"^AppId=\{(\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\})$", iss.read_text("utf-8"), re.M)
    if found is None:
        raise SystemExit(f"No AppId in {iss}")
    return found[1]


def snapshot(folders: list[Path]) -> dict[str, str]:
    """The SHA-256 of every file in `folders`, by its path."""
    hashes = {}
    for folder in folders:
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            with path.open("rb") as f:
                hashes[str(path)] = hashlib.file_digest(f, "sha256").hexdigest()
    return hashes


def installed(guid: str) -> bool:
    """Whether Windows lists an install of this AppId in Installed apps (its 64-bit uninstall entry)."""
    import winreg  # Windows only

    key = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{guid}_is1"
    try:
        winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY).Close()
    except FileNotFoundError:
        return False
    return True


def shortcut(lnk: Path) -> tuple[str, str] | None:
    """The full path of the program a .lnk file starts and its arguments, read through Windows Script Host; None when
    there is no such file."""
    if not lnk.is_file():
        return None
    script = "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); $s.TargetPath; $s.Arguments"
    args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    out = subprocess.run(args, env={**os.environ, "LNK": str(lnk)}, capture_output=True, text=True, check=True)
    target, arguments = [*out.stdout.splitlines(), "", ""][:2]
    return os.path.normcase(os.path.realpath(target)), arguments


def places() -> list[Path]:
    """Where the installer puts shortcuts for every user: the Start menu's programs folder and the desktop."""
    start = Path(os.environ["ProgramData"], "Microsoft", "Windows", "Start Menu", "Programs")
    return [start / name for name in SHORTCUTS] + [Path(os.environ["PUBLIC"], "Desktop", f"{APP_NAME}.lnk")]


def after_install(app: Path, guid: str) -> list[str]:
    exe = app / EXE
    names = (EXE, "THIRD_PARTY_NOTICES.txt", "sbom.cdx.json", "unins000.exe")
    problems = [f"no {name} in {app}" for name in names if not (app / name).is_file()]
    if exe.is_file() and subsystem(exe) != GUI:
        problems.append(f"the installed .exe's subsystem is {subsystem(exe)}, not {GUI} (no console window)")
    target = os.path.normcase(str(exe))
    wanted = [(target, arguments) for arguments in SHORTCUTS.values()] + [(target, "")]  # the desktop's last
    for lnk, want in zip(places(), wanted, strict=True):
        if (got := shortcut(lnk)) != want:
            problems.append(f"the shortcut {lnk} starts {got}, not {want}")
    if not installed(guid):
        problems.append("Windows does not list the app as installed")
    return problems


def uninstall(app: Path, logs: Path) -> list[str]:
    """Run the uninstaller; it deletes itself just after it exits, so its folder is watched for up to a minute."""
    args = [str(app / "unins000.exe"), *QUIET, f"/LOG={logs / 'uninstall.log'}"]
    code = subprocess.run(args, timeout=TIMEOUT, check=False).returncode  # noqa: S603 (the build under test)
    deadline = time.monotonic() + 60
    while (app / "unins000.exe").exists() and time.monotonic() < deadline:
        time.sleep(1)
    problems = [] if code == 0 else [f"the uninstaller exited with code {code}"]
    left = sorted(str(p) for p in app.rglob("*") if p.is_file()) if app.exists() else []
    if left:
        problems.append(f"the uninstaller left {len(left)} program file(s), such as {left[0]}")
    return problems


def check(setup: Path, tmp: Path, guid: str, workspaces: list[Path]) -> list[str]:
    """Install, self-test and uninstall, each in `tmp`; what went wrong."""
    app, logs = tmp / "app", tmp / "logs"
    logs.mkdir()
    before = snapshot(workspaces)
    args = [str(setup), *QUIET, f"/DIR={app}", "/TASKS=desktopicon", f"/LOG={logs / 'install.log'}"]
    code = subprocess.run(args, timeout=TIMEOUT, check=False).returncode  # noqa: S603 (the installer under test)
    if code != 0:
        problems = [f"the installer exited with code {code}"]
    else:
        problems = after_install(app, guid)
        if (app / EXE).is_file():
            problem = self_test(app / EXE, tmp / "selftest")
            print("--- The installed app's log of its self-test ---")
            for line in log_lines(tmp / "selftest"):
                print(json.dumps(line, ensure_ascii=False))
            if problem is not None:
                problems.append(f"self-test: {problem}")
        problems += uninstall(app, logs)
        problems += [f"the shortcut {lnk} is still there" for lnk in places() if lnk.exists()]
        if installed(guid):
            problems.append("Windows still lists the app as installed")
    if snapshot(workspaces) != before:
        problems.append(f"the files in {' and '.join(map(str, workspaces))} changed")
    for log in sorted(logs.glob("*.log")) if problems else ():
        print(f"--- {log.name} ---\n{log.read_text(encoding='utf-8', errors='replace')}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("setup", type=Path, help="the installer to check")
    setup = ap.parse_args(argv).setup.resolve()
    if sys.platform != "win32" or not setup.is_file():
        print(f"The check runs on Windows only, on an installer file: {setup} is none, or this is not Windows.")
        return 2
    guid = app_id()
    if installed(guid):
        print(f"{APP_NAME} is installed on this PC already: check the installer on a PC without it, as CI does.")
        return 2
    workspaces = [default_workspace(), demo_folder(default_workspace())]
    made = [folder for folder in workspaces if not folder.exists()]
    for folder in made:  # a user's folders the installer did not create
        folder.mkdir(parents=True)
        (folder / "settings.json").write_text('{"language": "en"}\n', encoding="utf-8")
        (folder / "aoi.sqlite").write_bytes(b"a station's records, made by tools/check_installer.py")
    try:
        with tempfile.TemporaryDirectory(prefix="aoi-installer-", ignore_cleanup_errors=True) as tmp:
            problems = check(setup, Path(tmp).resolve(), guid, workspaces)
    finally:
        for folder in made:
            shutil.rmtree(folder, ignore_errors=True)
    if problems:
        print("Installer check failed: " + "; ".join(problems) + ".")
        return 1
    print(
        "Installer check passed: it installed silently with its shortcuts, the installed app inspected its synthetic "
        "board with the expected verdict, and the uninstaller removed the program files and kept the workspace."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
