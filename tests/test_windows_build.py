"""The Windows build inspects a board on its own (REQ-SET-012, stage S56; ADR 0007).

The built app has no console and needs no click, so CI's smoke test (tools/smoke_test_build.py) starts it twice: once
as a user would, and once as `AOI-PoC-Inspector.exe --self-test WORKSPACE`, which inspects one board of the synthetic
regression set through AppContext and exits 0 only with the verdict tests/regression/expected.json records for it.
These tests run the same entry point from source, `main.py --self-test WORKSPACE BOARDS`, with the boards
tools/make_selftest_data.py writes, as installer/aoi.spec does for the build. The boards are drawings: a pass says the
app judges as the code does, never how well it finds defects.
"""

from __future__ import annotations

import importlib.metadata as md
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2
import pytest
import yaml

from aoi import selftest
from aoi.config import APP_VERSION
from tools import make_selftest_data
from tools.smoke_test_build import CONSOLE, GUI, log_lines, subsystem

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((ROOT / "tests" / "regression" / "expected.json").read_text(encoding="utf-8"))
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def boards(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The self-test's boards, as installer/aoi.spec writes them into the build."""
    out = tmp_path_factory.mktemp("selftest")
    make_selftest_data.write(out)
    return out


def self_test(workspace: Path, boards: Path) -> tuple[int, list[dict[str, Any]]]:
    """`main.py --self-test` in an interpreter of its own, as a start from source: its exit code and its log."""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    args = [sys.executable, str(ROOT / "main.py"), "--self-test", str(workspace), str(boards)]
    proc = subprocess.run(args, env=env, cwd=ROOT, capture_output=True, text=True, timeout=300, check=False)
    return proc.returncode, log_lines(workspace)


def events(lines: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [line for line in lines if line.get("event") == event]


def test_req_set_012_the_self_test_boards_come_from_the_regression_set(boards: Path) -> None:
    """The golden board and one NG board of the regression set, with its recipe and the verdict expected.json holds."""
    spec = json.loads((boards / "selftest.json").read_text(encoding="utf-8"))
    entry = next(b for b in EXPECTED["boards"] if b["name"] == spec["board"])
    assert (spec["recipe"], spec["seed"]) == (EXPECTED["recipe"], EXPECTED["seed"])
    assert (entry["label"], entry["verdict"], spec["expected"]) == ("NG", "NG", "NG")
    assert sorted(p.name for p in boards.iterdir()) == sorted(["selftest.json", spec["golden"], spec["board"]])
    for name in (spec["golden"], spec["board"]):
        assert cv2.imread(str(boards / name)).shape == (480, 640, 3)
    assert "Never accuracy." in spec["about"]


def test_req_set_012_the_self_test_inspects_a_synthetic_board_and_exits_0(boards: Path, tmp_path: Path) -> None:
    """Through AppContext, as a station would: the golden board imported, the recipe saved, the board inspected and its
    record saved, then one line with the verdict and the expected one, and no error in the log."""
    code, lines = self_test(tmp_path / "workspace", boards)
    assert code == 0, lines
    (line,) = events(lines, "selftest.verdict")
    board = make_selftest_data.BOARD
    assert {k: line[k] for k in ("level", "board", "verdict", "expected", "passed")} == {
        "level": "INFO",
        "board": board,
        "verdict": "NG",
        "expected": "NG",
        "passed": True,
    }
    assert [(s["board_model"], s["verdict"]) for s in events(lines, "inspection.saved")] == [("REGRESSION", "NG")]
    assert not [line for line in lines if line["level"] in ("ERROR", "CRITICAL")]


def test_req_set_012_a_verdict_other_than_the_expected_one_exits_1(boards: Path, tmp_path: Path) -> None:
    other = tmp_path / "boards"
    shutil.copytree(boards, other)
    spec = json.loads((other / "selftest.json").read_text(encoding="utf-8"))
    (other / "selftest.json").write_text(json.dumps({**spec, "expected": "OK"}), encoding="utf-8")
    code, lines = self_test(tmp_path / "workspace", other)
    assert code == 1
    (line,) = events(lines, "selftest.verdict")
    assert (line["level"], line["verdict"], line["expected"], line["passed"]) == ("ERROR", "NG", "OK", False)


def test_req_set_012_the_self_test_opens_only_a_new_or_empty_folder(boards: Path, tmp_path: Path) -> None:
    """It adds a board model, so it never runs on a station's workspace: a folder with anything in it is refused before
    it is opened, and wrong arguments too (exit 2)."""
    station = tmp_path / "station"
    station.mkdir()
    (station / "aoi.sqlite").write_bytes(b"")
    assert selftest.main([str(station), str(boards)]) == 2
    assert sorted(p.name for p in station.iterdir()) == ["aoi.sqlite"]
    assert selftest.main([]) == 2
    assert selftest.main([str(tmp_path / "new")]) == 2  # from source the boards are named; a built app has its own
    assert not (tmp_path / "new").exists()


def test_req_set_012_the_windows_build_runs_on_v_tags_too() -> None:
    """A pushed v* tag builds, as main and the pull requests that change the build or its self-test still do."""
    on = WORKFLOW[True]  # YAML 1.1 reads the key "on" as true
    assert on["push"] == {"branches": ["main"], "tags": ["v*"]} and "workflow_dispatch" in on
    paths = {"installer/**", "tools/smoke_test_build.py", "tools/make_selftest_data.py", "aoi/selftest.py"}
    assert paths <= set(on["pull_request"]["paths"])
    assert WORKFLOW["jobs"]["windows"]["runs-on"] == "windows-latest"


def info_step(tmp_path: Path, tag: str) -> subprocess.CompletedProcess[str]:
    """The workflow's step that writes BUILD-INFO.txt and names the artifact, run on a stand-in build folder."""
    (step,) = [s for s in WORKFLOW["jobs"]["windows"]["steps"] if s.get("id") == "info"]
    (tmp_path / "dist" / "AOI-PoC-Inspector").mkdir(parents=True, exist_ok=True)
    (tmp_path / "dist" / "AOI-PoC-Inspector" / "AOI-PoC-Inspector.exe").write_bytes(b"MZ")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "GITHUB_OUTPUT": str(tmp_path / "output"), "TAG": tag}
    env |= {"COMMIT": "a" * 40, "HEAD_SHA": "a" * 40, "REF": f"refs/tags/{tag}", "RUN_URL": "https://example.invalid/1"}
    return subprocess.run([sys.executable, "-c", step["run"]], cwd=tmp_path, env=env, capture_output=True, text=True)


def test_req_set_012_a_tag_s_build_is_named_for_the_tag(tmp_path: Path) -> None:
    """The artifact and BUILD-INFO.txt carry the tag, which must name the version the app says it is."""
    tag = f"v{APP_VERSION}"
    assert info_step(tmp_path, tag).returncode == 0
    output = (tmp_path / "output").read_text(encoding="utf-8")
    assert output == f"name=AOI-PoC-Inspector-{tag}-gaaaaaaa-windows-x64-unsigned\n"
    info = (tmp_path / "dist" / "AOI-PoC-Inspector" / "BUILD-INFO.txt").read_text(encoding="utf-8")
    assert info.startswith(f"AOI PoC Inspector {APP_VERSION}, internal test build {tag} gaaaaaaa\n")
    assert "Not a release." in info
    assert info_step(tmp_path / "main", "").returncode == 0  # a push to main, as before: named for the version
    untagged = (tmp_path / "main" / "output").read_text(encoding="utf-8")
    assert untagged == f"name=AOI-PoC-Inspector-{APP_VERSION}-gaaaaaaa-windows-x64-unsigned\n"
    refused = info_step(tmp_path, "v99.0.0")
    assert refused.returncode == 1
    assert f"The tag v99.0.0 does not name version {APP_VERSION}" in refused.stderr


def test_req_set_012_the_smoke_test_tells_a_windowed_exe_from_a_console_one() -> None:
    """Windows opens a console window only for an .exe of the console subsystem; pip's launchers are one of each."""
    pip = md.distribution("pip")
    assert subsystem(Path(str(pip.locate_file("pip/_vendor/distlib/w64.exe")))) == GUI
    assert subsystem(Path(str(pip.locate_file("pip/_vendor/distlib/t64.exe")))) == CONSOLE
    assert subsystem(ROOT / "main.py") is None  # not a Windows executable
