"""The demo workspace (REQ-SET-007; S53): the bundle the build makes, its load and reset, and the production workspace
they never touch. Results on its synthetic boards prove the demo's path works and are never quoted as accuracy."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from unittest import mock

import pytest

from aoi.config import Settings
from aoi.core import demo
from aoi.core.services import AppContext
from aoi.data import credentials
from aoi.errors import AoiError


def hashes(folder: Path) -> dict[str, str]:
    """Every file under `folder` with its SHA-256, read here rather than through the code under test."""
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}  # fmt: skip


def production(tmp_path: Path) -> Path:
    """A production workspace with its settings.json, a database and a result file, as a station holds them."""
    root = tmp_path / "AOI_Workspace"
    AppContext(Settings(workspace=str(root), device="cpu")).close()
    (root / "results" / "2026-10-09").mkdir(parents=True)
    (root / "results" / "2026-10-09" / "board_OK.png").write_bytes(b"a result the demo must never touch")
    (root / "settings.json").write_text(json.dumps({"workspace": str(root), "language": "ko"}), encoding="utf-8")
    return root


def run_boards(bundle: Path, folder: Path, keys: credentials.Credentials) -> list[str]:
    """Open the demo workspace as the app does and inspect its demo boards in run order, saving each result."""
    manifest = demo.read_bundle(bundle)
    ctx = AppContext(Settings(workspace=str(folder), device="cpu"), keys)
    try:
        return [ctx.inspect_file(manifest["board_model"], str(folder / b["file"])).verdict for b in manifest["boards"]]
    finally:
        ctx.close()


@pytest.fixture
def bundle(demo_bundle: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The session's demo bundle, as the app finds it (`demo.bundle_dir`)."""
    monkeypatch.setenv("AOI_DEMO_BUNDLE", str(demo_bundle))
    assert demo.bundle_dir() == demo_bundle
    return demo_bundle


def test_req_set_007_bundle_holds_the_ten_boards_with_one_failing(bundle: Path) -> None:
    manifest = demo.read_bundle(bundle)
    verdicts = [b["verdict"] for b in manifest["boards"]]
    assert verdicts == ["OK"] * 3 + ["NG"] + ["OK"] * 6, verdicts
    assert manifest["board_model"] == "DEMO-TBOX-A1"
    assert not any((bundle / demo.WORKSPACE / name).exists() for name in demo.BUILD_ONLY)
    card = next((bundle / demo.WORKSPACE / "models").rglob("*.card.md")).read_text(encoding="utf-8")
    assert "nothing on this card is a measure of accuracy" in card  # synthetic boards: never quoted as accuracy


def test_req_set_007_load_and_reset_under_10s(bundle: Path, tmp_path: Path) -> None:
    keys = credentials.MemoryCredentials()  # a station's key store: the demo store's key goes there at each load
    folder = demo.demo_folder(production(tmp_path))
    started = time.monotonic()
    demo.load(bundle, folder, {"language": "en"}, keys)
    loaded_in = time.monotonic() - started
    assert run_boards(bundle, folder, keys) == ["OK"] * 3 + ["NG"] + ["OK"] * 6  # the same verdicts as at the build
    assert len(list((folder / "results").rglob("*_NG.png"))) == 1
    seconds = demo.reset(bundle, folder, keys)
    assert loaded_in < 10 and seconds < 10, (loaded_in, seconds)
    after = hashes(folder)
    assert {k: v for k, v in after.items() if k not in demo.KEEP} == hashes(bundle / demo.WORKSPACE)
    assert json.loads((folder / "settings.json").read_text(encoding="utf-8"))["workspace"] == str(folder)
    assert demo.is_demo(folder)
    assert run_boards(bundle, folder, keys)[3] == "NG"  # the store's key is still there: a reset changes no key


def test_req_set_007_production_untouched(bundle: Path, tmp_path: Path) -> None:
    root = production(tmp_path)
    before = hashes(root)
    keys = credentials.MemoryCredentials()
    folder = demo.demo_folder(root)
    assert folder.parent == root.parent and folder.name == "AOI_Workspace-Demo"  # beside it, never inside
    demo.load(bundle, folder, {"language": "ko"}, keys)
    run_boards(bundle, folder, keys)
    demo.reset(bundle, folder, keys)
    demo.load(bundle, folder, {"language": "ko"}, keys)  # a second load keeps the demo as it is
    assert hashes(root) == before


def test_req_set_007_a_second_load_keeps_the_demo_as_it_is(bundle: Path, tmp_path: Path) -> None:
    keys = credentials.MemoryCredentials()
    folder = tmp_path / "demo"
    demo.load(bundle, folder, {}, keys)
    run_boards(bundle, folder, keys)
    results = sorted(p.name for p in (folder / "results").rglob("*.png"))
    keys2 = credentials.MemoryCredentials()  # another Windows account: the key comes with the load
    demo.load(bundle, folder, {}, keys2)
    assert sorted(p.name for p in (folder / "results").rglob("*.png")) == results
    assert keys2.read(credentials.STORE_PREFIX + json.loads((bundle / demo.KEY_FILE).read_text())["store_uuid"])


def test_req_set_007_load_never_writes_into_a_folder_that_is_not_a_demo(bundle: Path, tmp_path: Path) -> None:
    folder = tmp_path / "AOI_Workspace-Demo"
    folder.mkdir()
    (folder / "notes.txt").write_text("someone's own files")
    with pytest.raises(AoiError) as e:
        demo.load(bundle, folder, {}, credentials.MemoryCredentials())
    assert e.value.code == "AOI-SET-016" and str(folder) in e.value.message
    assert [p.name for p in folder.iterdir()] == ["notes.txt"]
    with pytest.raises(AoiError) as e:
        demo.reset(bundle, folder, credentials.MemoryCredentials())
    assert e.value.code == "AOI-SET-016"
    assert [p.name for p in folder.iterdir()] == ["notes.txt"]  # nothing deleted


@pytest.mark.parametrize("damage", ["changed", "added", "removed", "manifest"])
def test_req_set_007_a_damaged_bundle_is_refused_before_anything_is_written(
    demo_bundle: Path, tmp_path: Path, damage: str
) -> None:
    bundle = tmp_path / "bundle"
    shutil.copytree(demo_bundle, bundle)
    board = bundle / demo.WORKSPACE / demo.BOARDS / "board_04.png"
    if damage == "changed":
        board.write_bytes(board.read_bytes() + b"x")
    elif damage == "added":
        (bundle / demo.WORKSPACE / "extra.txt").write_text("x")
    elif damage == "removed":
        board.unlink()
    else:
        (bundle / demo.BUNDLE_FILE).write_text("{not json")
    folder = tmp_path / "demo"
    with pytest.raises(AoiError) as e:
        demo.load(bundle, folder, {}, credentials.MemoryCredentials())
    assert e.value.code == "AOI-SET-015"
    if damage != "manifest":
        assert ("extra.txt" if damage == "added" else "board_04.png") in e.value.message
    assert not folder.exists()


def test_req_set_007_a_reset_stopped_by_a_held_file_finishes_the_next_time(bundle: Path, tmp_path: Path) -> None:
    keys = credentials.MemoryCredentials()
    folder = tmp_path / "demo"
    demo.load(bundle, folder, {}, keys)
    run_boards(bundle, folder, keys)
    held = PermissionError(13, "The process cannot access the file", str(folder / "results"))
    with mock.patch("shutil.rmtree", side_effect=held), pytest.raises(AoiError) as e:
        demo.reset(bundle, folder, keys)
    assert e.value.code == "AOI-SET-017" and str(folder / "results") in e.value.message
    assert demo.is_demo(folder)  # still a demo workspace, so the next reset may finish
    demo.reset(bundle, folder, keys)
    assert not list((folder / "results").rglob("*.png"))
