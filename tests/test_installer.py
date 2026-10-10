"""The internal Windows installer, unsigned (REQ-SET-012, stage S57; ADR 0007).

installer/aoi.iss wraps the PyInstaller one-folder build in an Inno Setup installer. Inno Setup's compiler runs on
Windows only, so CI compiles it (.github/workflows/build.yml) and installs, self-tests and uninstalls the result; these
tests read the script itself: the settings a reviewer would check, parsed as Inno Setup reads them.
"""

from __future__ import annotations

import re
from pathlib import Path

from aoi.config import APP_NAME, APP_VERSION

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
