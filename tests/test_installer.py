"""The internal Windows installer, unsigned (REQ-SET-012, stage S57; ADR 0007).

installer/aoi.iss wraps the PyInstaller one-folder build in an Inno Setup installer. Inno Setup's compiler runs on
Windows only, so CI compiles it (.github/workflows/build.yml) and installs, self-tests and uninstalls the result; these
tests read the script itself, the settings a reviewer would check, parsed as Inno Setup reads them; and the workflow
and tools/check_installer.py, which does the install, the self-test and the uninstall on the runner.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

from aoi.config import APP_NAME, APP_VERSION
from tools import check_installer, smoke_test_build
from tools import third_party_notices as tpn

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "installer" / "aoi.iss"
# Fixed for the life of the product: Windows finds an earlier install by it, to upgrade or remove it
APP_ID = "{7D122A0A-06CC-4538-A441-BD5D560E2255}"
PARAM = re.compile(r'(\w+):\s*("(?:[^"]|"")*"|[^;]*)\s*(?:;|$)')  # Name: "value"; Flags: a b


def script() -> str:
    """The script with each line that ends in ISPP's " \\" joined to the next, as Inno Setup's preprocessor reads it."""
    return re.sub(r" \\\n\s*", " ", ISS.read_text(encoding="utf-8"))


def sections(text: str) -> dict[str, list[str]]:
    """The script's lines by section, without blank lines and comments; preprocessor lines go under "#"."""
    out: dict[str, list[str]] = {"#": []}
    current = "#"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("#"):
            out["#"].append(line)
        elif line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            out.setdefault(current, [])
        else:
            out[current].append(line)
    return out


def directives(lines: list[str]) -> dict[str, str]:
    """[Setup] or [Messages]: Name=value, one per line."""
    return dict(line.split("=", 1) for line in lines)


def entry(line: str) -> dict[str, str]:
    """[Files], [Icons] and the like: Name: "value"; Name: value, with "" for a quote inside quotes."""
    found = {}
    for key, value in PARAM.findall(line):
        found[key] = value[1:-1].replace('""', '"') if value.startswith('"') else value.strip()
    return found


def defines() -> dict[str, str]:
    """ISPP's #define lines: the text of a string or of strings joined by +, else the expression as written."""
    found = {}
    for name, expr in re.findall(r"^\s*#define (\w+) (.+)$", script(), re.MULTILINE):
        strings = re.fullmatch(r'"[^"]*"(?:\s*\+\s*"[^"]*")*', expr)
        found[name] = "".join(re.findall(r'"([^"]*)"', expr)) if strings else expr
    return found


def messages() -> dict[str, str]:
    """[Messages], with the {#Name} of each #define replaced by its text, as the preprocessor does."""
    names, said = defines(), directives(sections(script())["Messages"])
    return {key: re.sub(r"\{#(\w+)\}", lambda m: names[m[1]], text) for key, text in said.items()}


def test_req_set_012_the_installer_installs_per_machine_on_64_bit_windows_10_or_later() -> None:
    """Into Program Files for every user of the PC, with admin rights; x64 Windows from Windows 10 build 19044, the
    oldest the Customers & Launch platform table supports (Windows 10 IoT Enterprise LTSC 2021)."""
    setup = directives(sections(script())["Setup"])
    assert setup["AppId"] == "{" + APP_ID  # "{{" is a brace in Inno Setup
    assert setup["PrivilegesRequired"] == "admin" and "PrivilegesRequiredOverridesAllowed" not in setup
    assert setup["DefaultDirName"] == r"{autopf}\{#AppName}"
    assert setup["ArchitecturesAllowed"] == setup["ArchitecturesInstallIn64BitMode"] == "x64compatible"
    assert setup["MinVersion"] == "10.0.19044"
    assert defines()["AppName"] == APP_NAME


def test_req_set_012_the_installer_takes_the_version_the_build_passes_in() -> None:
    """CI passes aoi/config.py's version (ISCC /DAppVersion=...); a compile without it stops, and none is written in."""
    text = script()
    assert re.search(r"^#ifndef AppVersion\n\s*#error .+\n#endif$", text, re.MULTILINE)
    setup = directives(sections(text)["Setup"])
    assert setup["AppVersion"] == "{#AppVersion}"
    assert setup["OutputBaseFilename"] == "AOI-PoC-Inspector-{#AppVersion}-setup-x64-unsigned"
    assert APP_VERSION not in text


def test_req_set_012_the_installer_installs_the_build_folder_with_its_notices_beside_the_exe() -> None:
    """The whole one-folder build goes into the program folder; the compile stops when the folder lacks the .exe or
    THIRD_PARTY_NOTICES.txt, which installer/aoi.spec writes beside it."""
    text = script()
    (files,) = [entry(line) for line in sections(text)["Files"]]
    assert (files["Source"], files["DestDir"]) == (r"{#BuildDir}\*", "{app}")
    assert {"ignoreversion", "recursesubdirs", "createallsubdirs"} <= set(files["Flags"].split())
    assert re.search(r'^\s*#define BuildDir AddBackslash\(SourcePath\) \+ "\.\.\\dist\\AOI-PoC-Inspector"$', text, re.M)
    assert defines()["AppExe"] == APP_NAME.replace(" ", "-") + ".exe"
    assert '#if !FileExists(BuildDir + "\\" + AppExe) || !FileExists(BuildDir + "\\THIRD_PARTY_NOTICES.txt")' in text
    spec = (ROOT / "installer" / "aoi.spec").read_text(encoding="utf-8")
    assert '(Path(DISTPATH) / NAME / "THIRD_PARTY_NOTICES.txt").write_text(' in spec


def test_req_set_012_start_menu_and_demo_shortcuts_and_an_optional_desktop_one() -> None:
    """The Demo shortcut starts the .exe with --demo, which main.py reads to open the demo workspace (REQ-SET-007)."""
    parts = sections(script())
    exe = r"{app}\{#AppExe}"
    icons = [entry(line) for line in parts["Icons"]]
    assert [(i["Name"], i["Filename"], i.get("Parameters"), i.get("Tasks")) for i in icons] == [
        (r"{autoprograms}\{#AppName}", exe, None, None),
        (r"{autoprograms}\{#AppName} (Demo)", exe, "--demo", None),
        (r"{autodesktop}\{#AppName}", exe, None, "desktopicon"),
    ]
    (task,) = [entry(line) for line in parts["Tasks"]]
    assert task["Name"] == "desktopicon" and task["Flags"] == "unchecked"  # off unless the user ticks it
    assert 'open_demo() if "--demo" in sys.argv[1:]' in (ROOT / "main.py").read_text(encoding="utf-8")


def test_req_set_012_the_uninstaller_removes_the_program_files_and_keeps_the_workspace() -> None:
    """Nothing is installed or deleted outside the program folder, nothing runs at uninstall, and the uninstaller says
    that the workspace, the demo workspace beside it and settings.json stay."""
    parts = sections(script())
    assert not {"Dirs", "Registry", "INI", "Run", "UninstallRun", "UninstallDelete", "Code"} & set(parts)
    for line in parts["Files"] + parts["InstallDelete"]:
        target = entry(line).get("DestDir") or entry(line)["Name"]
        assert target == "{app}" or target.startswith("{app}\\"), line
    said = messages()
    kept = ("Only the program files are removed", "(AOI_Workspace in your", "(AOI_Workspace-Demo)", "settings.json")
    assert all(words in said["ConfirmUninstall"] for words in kept)
    for key in ("UninstalledAll", "UninstalledMost"):
        assert said[key].endswith(" Your workspace, the demo workspace and settings.json were kept.")


def test_req_set_012_the_installer_says_it_is_unsigned_and_for_internal_use_only() -> None:
    """On its welcome page, in its name in Installed apps and in its file name; and nothing signs it."""
    parts = sections(script())
    setup, welcome = directives(parts["Setup"]), messages()["WelcomeLabel2"]
    assert setup["DisableWelcomePage"] == "no" and "SignTool" not in setup
    internal = ("INTERNAL TEST BUILD, NOT SIGNED", "must never go to a customer", "not a release")
    assert all(words in welcome for words in internal) and "never your workspace" in welcome
    assert "Windows SmartScreen and the User Account Control prompt name no publisher" in welcome
    assert setup["AppVerName"] == "{#AppName} {#AppVersion} (internal, unsigned)"
    assert setup["OutputBaseFilename"].endswith("-unsigned")


def workflow() -> dict[Any, Any]:
    return dict(yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")))


def steps() -> list[dict[str, Any]]:
    return list(workflow()["jobs"]["windows"]["steps"])


def by_id(step_id: str) -> dict[str, Any]:
    (found,) = [step for step in steps() if step.get("id") == step_id]
    return found


def test_req_set_012_ci_compiles_the_installer_with_the_app_s_version_at_a_pinned_inno_setup() -> None:
    """After the build passes its smoke test: Inno Setup at the pinned version, checked, then the .iss compiled with
    the version aoi/config.py holds; the version the notices name is the one CI installs."""
    build = workflow()
    pin = build["env"]["INNO_SETUP_VERSION"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", pin) and pin == tpn.INNO_SETUP_VERSION
    inno = by_id("inno")["run"]
    assert "choco install innosetup --version $env:INNO_SETUP_VERSION " in inno
    assert "$found -ne $env:INNO_SETUP_VERSION" in inno
    # ISCC.exe has no file version (the runner read 0.0.0), so the version is the one Inno Setup's own setup records in
    # its uninstall entry, else Compil32.exe's file version
    assert "Uninstall\\Inno Setup 6_is1" in inno and ").DisplayVersion" in inno and '"Compil32.exe"' in inno
    assert "$iscc).VersionInfo" not in inno
    compiled = by_id("installer")["run"]
    assert '$version = python -c "from aoi.config import APP_VERSION; print(APP_VERSION)"' in compiled
    assert '& $env:ISCC "/DAppVersion=$version" installer\\aoi.iss' in compiled
    assert '"dist\\installer\\AOI-PoC-Inspector-$version-setup-x64-unsigned.exe"' in compiled
    ids = [step.get("id") for step in steps()]
    assert ids.index("build") < ids.index("smoke") < ids.index("info") < ids.index("inno") < ids.index("installer")
    assert {"installer/aoi.iss", "tools/check_installer.py"} <= set(build[True]["pull_request"]["paths"])  # "on"
    assert build["permissions"] == {"contents": "read"}
    for step in steps():  # every action pinned to a full commit
        assert "uses" not in step or re.fullmatch(r"actions/[\w-]+@[0-9a-f]{40}", step["uses"]), step


def test_req_set_012_ci_installs_self_tests_and_uninstalls_the_installer_before_keeping_it() -> None:
    """The installer is checked on the runner by tools/check_installer.py, then kept as an artifact of its own."""
    check = by_id("check_installer")
    assert check["env"] == {"SETUP": "${{ steps.installer.outputs.setup }}"}
    assert check["run"] == "python tools/check_installer.py $env:SETUP"
    (kept,) = [step for step in steps() if step.get("with", {}).get("path") == "${{ steps.installer.outputs.setup }}"]
    assert kept["uses"].startswith("actions/upload-artifact@") and steps().index(kept) > steps().index(check)
    assert kept["with"]["name"] == "${{ steps.info.outputs.name }}-installer"
    assert (kept["with"]["retention-days"], kept["with"]["if-no-files-found"]) == (30, "error")
    assert check_installer.QUIET == ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    assert check_installer.SHORTCUTS == {f"{APP_NAME}.lnk": "", f"{APP_NAME} (Demo).lnk": "--demo"}
    assert check_installer.app_id() == APP_ID
    assert check_installer.self_test is smoke_test_build.self_test  # the build's own self-test, on the installed .exe


def test_req_set_012_the_installer_check_sees_any_change_to_a_workspace(tmp_path: Path) -> None:
    """The uninstall must leave the workspace and the demo workspace as they were: any file changed, added or removed
    shows; the check itself runs on Windows only."""
    workspace, demo = tmp_path / "AOI_Workspace", tmp_path / "AOI_Workspace-Demo"
    for folder in (workspace, demo / "images"):
        folder.mkdir(parents=True)
    (workspace / "settings.json").write_text("{}", encoding="utf-8")
    (demo / "images" / "board.png").write_bytes(b"png")
    before = check_installer.snapshot([workspace, demo])
    assert sorted(Path(p).name for p in before) == ["board.png", "settings.json"]
    (workspace / "settings.json").write_text('{"language": "ko"}', encoding="utf-8")
    assert check_installer.snapshot([workspace, demo]) != before
    (workspace / "settings.json").write_text("{}", encoding="utf-8")
    assert check_installer.snapshot([workspace, demo]) == before
    (workspace / "aoi.sqlite").write_bytes(b"")
    assert check_installer.snapshot([workspace, demo]) != before
    (workspace / "aoi.sqlite").unlink()
    (demo / "images" / "board.png").unlink()
    assert check_installer.snapshot([workspace, demo]) != before
    if sys.platform != "win32":
        assert check_installer.main([str(tmp_path / "setup.exe")]) == 2
