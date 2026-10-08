#!/usr/bin/env python
"""Start a built app on an empty workspace and check that it opens (REQ-SET-012; .github/workflows/build.yml).

    python tools/smoke_test_build.py dist/AOI-PoC-Inspector/AOI-PoC-Inspector.exe

The app runs as a user would start it, on a new workspace folder (AOI_WORKSPACE). It passes when the app's log
records "app.start", the app then keeps running for HOLD seconds with no error in its log, and its database holds
every migration in aoi/data/migrations. It fails (exit 1) when the app exits, logs an error, has not logged
"app.start" after TIMEOUT seconds, or applied other migrations. The app is closed either way and its log printed.
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
TIMEOUT = 300  # seconds to "app.start": the first start of a fresh build is slow while antivirus reads every file
HOLD = 15  # seconds the app must keep running after it, with no error logged


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


def check(exe: Path, workspace: Path) -> str | None:
    """None when the app opens and keeps running; otherwise why not."""
    env = {**os.environ, "AOI_WORKSPACE": str(workspace)}
    proc = subprocess.Popen([str(exe)], env=env)  # noqa: S603 (the build under test, started without a shell)
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("exe", type=Path, help="the built executable")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="aoi-smoke-", ignore_cleanup_errors=True) as tmp:
        workspace = Path(tmp) / "workspace"
        problem = check(args.exe.resolve(), workspace)
        for line in log_lines(workspace):
            print(json.dumps(line, ensure_ascii=False))
    if problem is not None:
        print(f"Smoke test failed: {problem}.")
        return 1
    print(f"Smoke test passed: the app opened, ran {HOLD} s with no error and applied every migration.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
