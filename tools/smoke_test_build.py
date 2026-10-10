#!/usr/bin/env python
"""Start a built app, check that it opens and that it inspects (REQ-SET-012; .github/workflows/build.yml).

    python tools/smoke_test_build.py dist/AOI-PoC-Inspector/AOI-PoC-Inspector.exe

The app runs twice, each time on a new workspace folder and, on Windows, with only Windows' own folders on PATH, as
on a station, so a DLL missing from the build is not found in a build tool's folder instead:

1. As a user would start it (AOI_WORKSPACE): it passes when the app's log records "app.start", the app then keeps
   running for HOLD seconds with no error in its log, and its database holds every migration in aoi/data/migrations.
   It fails when the app exits, logs an error, has not logged "app.start" after TIMEOUT seconds, or applied other
   migrations. The app is closed either way.
2. With `--self-test WORKSPACE` (aoi/selftest.py): the app inspects the synthetic board it ships, with no window. It
   passes when the app exits 0 within TIMEOUT seconds, having logged that board's "selftest.verdict" equal to the
   expected verdict and no error.

On Windows the .exe must also be a GUI program, which Windows starts without a console window (CONSOLE is the
subsystem of a console build, which CI makes only to show a failed start's error). Each run's log is printed; any
failure exits 1.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Seconds to "app.start", or to the self-test's end: a fresh build's first start is slow while antivirus reads each file
TIMEOUT = 300
HOLD = 15  # seconds the app must keep running after it, with no error logged
GUI, CONSOLE = 2, 3  # the subsystem in a Windows executable's header: Windows opens a console window for CONSOLE only


def log_lines(workspace: Path) -> list[dict[str, object]]:
    """The app's log so far; a line still being written is left for the next read."""
    lines = []
    for path in sorted((workspace / "logs").glob("*.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return lines


def migrations_applied(workspace: Path) -> list[str]:
    uri = (workspace / "aoi.sqlite").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return [f"{n:04d}_{name}.sql" for n, name in db.execute("SELECT number, name FROM schema_version ORDER BY 1")]


def station_env(workspace: Path) -> dict[str, str]:
    """The environment of a start on a station: the workspace given, and on Windows only Windows' folders on PATH."""
    env = {**os.environ, "AOI_WORKSPACE": str(workspace)}
    if sys.platform == "win32":
        windows = os.environ["SystemRoot"]
        env["PATH"] = os.pathsep.join([os.path.join(windows, "System32"), windows])
    return env


def subsystem(exe: Path) -> int | None:
    """The subsystem a Windows executable's PE header names (GUI, CONSOLE, ...); None for a file that is not one."""
    with exe.open("rb") as f:
        head = f.read(4096)
    pe = int.from_bytes(head[0x3C:0x40], "little")  # where the PE header starts
    if head[:2] != b"MZ" or head[pe : pe + 4] != b"PE\0\0" or len(head) < pe + 94:
        return None
    return int.from_bytes(head[pe + 92 : pe + 94], "little")  # the optional header at pe + 24, Subsystem 68 bytes in


def check(exe: Path, workspace: Path) -> str | None:
    """None when the app opens and keeps running; otherwise why not."""
    proc = subprocess.Popen([str(exe)], env=station_env(workspace))  # noqa: S603 (the build under test, no shell)
    started = time.monotonic()
    opened_at: float | None = None
    try:
        while True:
            time.sleep(1)
            lines = log_lines(workspace)
            errors = [line for line in lines if line.get("level") in ("ERROR", "CRITICAL")]
            if errors:
                return f"the app logged {len(errors)} error(s)"
            if proc.poll() is not None:
                return f"the app exited with code {proc.returncode}"
            now = time.monotonic()
            if opened_at is None and any(line.get("event") == "app.start" for line in lines):
                opened_at = now
                print(f"app.start logged {now - started:.1f} s after the start")
            if opened_at is None and now - started > TIMEOUT:
                return f'no "app.start" in the log after {TIMEOUT} s'
            if opened_at is not None and now - opened_at >= HOLD:
                break
    finally:
        proc.kill()
        proc.wait(timeout=60)
    expected = sorted(p.name for p in (ROOT / "aoi" / "data" / "migrations").glob("*.sql"))
    applied = migrations_applied(workspace)
    if applied != expected:
        return f"the database holds migrations {applied}, not {expected}"
    return None


def self_test(exe: Path, workspace: Path) -> str | None:
    """None when `exe --self-test` inspects its board and gets the expected verdict; otherwise why not."""
    args = [str(exe), "--self-test", str(workspace)]
    try:  # killed at the timeout
        code = subprocess.run(args, env=station_env(workspace), timeout=TIMEOUT, check=False).returncode  # noqa: S603
    except subprocess.TimeoutExpired:
        return f"the self-test had not ended after {TIMEOUT} s"
    lines = log_lines(workspace)
    errors = [line for line in lines if line.get("level") in ("ERROR", "CRITICAL")]
    verdicts = [line for line in lines if line.get("event") == "selftest.verdict"]
    if code != 0 or errors or len(verdicts) != 1 or verdicts[0].get("verdict") != verdicts[0].get("expected"):
        return f"the self-test exited with code {code}, logged {len(errors)} error(s) and {len(verdicts)} verdict(s)"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("exe", type=Path, help="the built executable")
    exe = ap.parse_args().exe.resolve()
    problems = []
    found, wanted = subsystem(exe), CONSOLE if os.environ.get("AOI_BUILD_CONSOLE") == "1" else GUI
    if found is not None and found != wanted:  # None: not a Windows executable, which has no such subsystem
        problems.append(f"the .exe's subsystem is {found}, not {wanted} ({GUI} opens no console window, {CONSOLE} one)")
    with tempfile.TemporaryDirectory(prefix="aoi-smoke-", ignore_cleanup_errors=True) as tmp:
        for name, run in (("start", check), ("self-test", self_test)):
            workspace = Path(tmp) / name
            problem = run(exe, workspace)
            print(f"--- The app's log of the {name} ---")
            for line in log_lines(workspace):
                print(json.dumps(line, ensure_ascii=False))
            if problem is not None:
                problems.append(f"{name}: {problem}")
    if problems:
        print("Smoke test failed: " + "; ".join(problems) + ".")
        return 1
    print(
        f"Smoke test passed: the app opened, ran {HOLD} s with no error and applied every migration, and its self-test "
        "inspected its synthetic board and got the expected verdict."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
