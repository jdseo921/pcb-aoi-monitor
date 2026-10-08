"""The hashed lock files (stage S04, #17): every package is pinned and hashed, and the pins agree with the inputs.

tools/make_lock.py writes the five lock files, and CI's "Lock files match their inputs" job regenerates them from the
package indexes. These checks need no network, so a hand edit that drops a hash or a pin that drifts from
requirements.txt fails in every test run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools import make_lock as ml

ROOT = Path(__file__).resolve().parents[1]
PYPI_LOCKS = ["requirements.lock", "requirements-dev.lock", "requirements-build.lock"]
# Each tool lock: the runtime pins plus its own inputs (the Windows build tools since REQ-SET-012, ADR 0007)
TOOL_LOCKS = {"requirements-dev.txt": "requirements-dev.lock", "requirements-build.txt": "requirements-build.lock"}
TORCH_LOCKS = {build: f"requirements-torch-{build}.lock" for build in ml.TORCH_BUILDS}
HASH = re.compile(r"^    --hash=sha256:[0-9a-f]{64}( \\)?$")


def entries(name: str) -> dict[str, tuple[str, str | None]]:
    """Package name -> (pinned version, marker or None); fails on a package without a hash or an exact pin."""
    out: dict[str, tuple[str, str | None]] = {}
    for pkg, body in ml.blocks((ROOT / name).read_text(encoding="utf-8")):
        first, *hashes = body.split("\n")
        req, _, marker = first.rstrip(" \\").partition(";")
        assert "==" in req, f"{name}: {pkg} is not pinned exactly: {first}"
        assert hashes and all(HASH.match(h) for h in hashes), f"{name}: {pkg} has no sha256 hash: {first}"
        assert pkg not in out, f"{name}: {pkg} is listed twice"
        out[pkg] = (req.split("==", 1)[1].strip(), marker.strip() or None)
    return out


def direct_pins(name: str) -> dict[str, str]:
    pins = {}
    for raw in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if line:
            pkg, version = line.split("==", 1)
            pins[ml.norm(pkg)] = version.strip()
    return pins


@pytest.mark.parametrize("name", [*PYPI_LOCKS, *TORCH_LOCKS.values()])
def test_every_locked_package_is_pinned_and_hashed(name: str) -> None:
    assert entries(name), f"{name} lists no package"


def test_the_pypi_locks_pin_the_direct_requirements_and_agree_with_each_other() -> None:
    runtime = entries("requirements.lock")
    for pkg, version in direct_pins("requirements.txt").items():
        if pkg == "torch":
            continue
        assert runtime[pkg][0] == version, f"requirements.lock pins {pkg} {runtime[pkg][0]}, requirements.txt {version}"
    for txt, lock in TOOL_LOCKS.items():
        tools = entries(lock)
        for pkg, version in direct_pins(txt).items():
            assert tools[pkg][0] == version, f"{lock} pins {pkg} {tools[pkg][0]}, {txt} {version}"
        for pkg, (version, _) in runtime.items():
            assert tools[pkg][0] == version, f"{pkg}: {lock} {tools[pkg][0]}, requirements.lock {version}"


def test_pytorch_and_its_nvidia_libraries_stay_out_of_the_pypi_locks() -> None:
    for name in PYPI_LOCKS:
        names = entries(name)
        assert "torch" not in names, f"{name} lists torch: it comes from requirements-torch-*.lock"
        assert not [pkg for pkg in names if ml.GPU_ONLY.match(pkg)], f"{name} lists an NVIDIA package"


def test_each_pytorch_lock_holds_the_pinned_version_of_its_own_build() -> None:
    torch = direct_pins("requirements.txt")["torch"]
    runtime = entries("requirements.lock")
    for build, name in TORCH_LOCKS.items():
        index, label = ml.TORCH_BUILDS[build]
        text = (ROOT / name).read_text(encoding="utf-8")
        assert f"--index-url {index}\n" in text, f"{name} does not name its index {index}"
        locked = entries(name)
        assert locked.pop("torch") == (f"{torch}+{label}", None)
        for pkg, (_, marker) in locked.items():  # the CUDA build's NVIDIA libraries: Linux only, never shared
            assert marker == ml.LINUX, f"{name}: {pkg} must carry {ml.LINUX}"
            assert pkg not in runtime, f"{name}: {pkg} is also in requirements.lock"


@pytest.mark.parametrize("txt", TOOL_LOCKS)
def test_windows_only_requirements_keep_their_marker(txt: str) -> None:
    locked = entries(TOOL_LOCKS[txt])
    for raw in (ROOT / txt).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ";" in line:
            req, marker = (part.strip() for part in line.split(";", 1))
            pkg, version = req.split("==", 1)
            assert locked[ml.norm(pkg)] == (version, marker), f"{TOOL_LOCKS[txt]} must list {line}"


def test_a_marker_goes_before_the_hashes() -> None:
    block = "colorama==0.4.6 \\\n    --hash=sha256:" + "0" * 64
    assert ml.with_marker(block, 'sys_platform == "win32"').split("\n")[0] == (
        'colorama==0.4.6 ; sys_platform == "win32" \\'
    )
    assert ml.blocks(f"--index-url https://example.invalid\n# note\n{block}\n") == [("colorama", block)]
