"""The support bundle (REQ-LOG-007): one zip an Admin sends us, built from the workspace folder alone, so the command
line (`--support-bundle`) builds it when the window will not open, and the database is only read. It holds the last
DAYS days of logs, settings.json with any secret-looking key dropped, the schema version, BUILD-INFO and the SBOM of
the build, heartbeat.json, alerts.jsonl, alarms and audit as CSV, and the PC's facts. No image unless asked; nothing
REQ-USR-007 keeps out of logs (no password, PIN or hash: the users table is not in it). No Qt here."""

from __future__ import annotations

import contextlib
import ctypes
import gzip
import json
import os
import platform
import shutil
import sqlite3
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote

from ..config import APP_LABEL, BUILD_LINE, default_workspace
from ..data import atomic
from ..logging_setup import scrub
from ..times import now_utc
from . import heartbeat

DAYS = 7
IMAGES_KEPT = 100  # the newest records' overlays, when images are asked for
BUILD_FILES = ("BUILD-INFO.txt", "sbom.cdx.json")  # beside the .exe in a build; none from source
HIDDEN = {"hash", "pin", "key", "keys"}  # with SECRET_KEYS: a key ending in one of these words stays out (not key_id)


def app_folder() -> Path | None:
    """The installed app's folder, where the build files are; None from source."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else None


def ram_bytes() -> int | None:
    if os.name == "nt":

        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong)]
            _fields_ += [(f"f{i}", ctypes.c_ulonglong) for i in range(6)]

        s = Status(ctypes.sizeof(Status))
        return int(s.total) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)) else None  # type: ignore[attr-defined]
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, AttributeError):
        return None


def facts(root: Path) -> dict[str, Any]:
    """The build, the PC and its AI runtime: what a support ticket asks first."""
    import torch  # already loaded by the app; the command line pays for it here only

    gpu = torch.cuda.is_available()
    driver = torch._C._cuda_getDriverVersion() if gpu and hasattr(torch._C, "_cuda_getDriverVersion") else None
    return {
        "app": BUILD_LINE,
        "app_version": APP_LABEL,
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": ram_bytes(),
        "free_bytes": shutil.disk_usage(root).free,
        "python": platform.python_version(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "cuda_available": gpu,
        "gpu": torch.cuda.get_device_name(0) if gpu else None,
        "cuda_driver": driver,  # the CUDA driver API version, 12040 for 12.4
    }


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in scrub(value).items() if k.lower().split("_")[-1] not in HIDDEN}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _uri(db: Path) -> str:
    """The database as a read-only SQLite URI: file:/C:/… for a drive, file:////server/share/… for a share, whose
    file://server/… form SQLite refuses."""
    path = db.resolve().as_posix()
    lead = "//" if path.startswith("//") else "" if path.startswith("/") else "/"
    return f"file:{quote(lead + path, safe='/:')}?mode=ro"


def _rows(db: Path, sql: str, since: str) -> tuple[list[dict[str, Any]], str | None]:
    """Rows read with the database opened read-only, so a damaged or busy one still gives a bundle: (rows, why not)."""
    try:
        with sqlite3.connect(_uri(db), uri=True) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, (since,) if "?" in sql else ())], None
    except sqlite3.Error as e:
        return [], f"{type(e).__name__}: {e}"


def beats(logs: list[Path]) -> bytes:
    """The heartbeat's history: each beat the log holds (`AppContext.heartbeat` logs one a minute), oldest first."""
    found = []
    for p in logs:
        try:
            text = gzip.decompress(p.read_bytes()).decode() if p.suffix == ".gz" else p.read_text("utf-8")
        except (OSError, ValueError):
            continue  # today's, held open, is still read; one that is not shows in the bundle's logs/ anyway
        found += [line for line in text.splitlines() if '"event": "heartbeat"' in line]
    return "".join(f"{line}\n" for line in found).encode()


def build(root: Path, dest: Path, images: bool = False) -> dict[str, Any]:
    """Write the bundle to `dest` whole or not at all; returns its manifest, which is in it as manifest.json."""
    from .services import csv_bytes  # the app's CSV, with formula-safe cells

    start = datetime.now(UTC) - timedelta(days=DAYS)
    since, cut = start.isoformat(), start.strftime("%Y-%m-%d")
    logs, db = root / "logs", root / "aoi.sqlite"
    files: dict[str, Path] = {}
    for p in sorted(logs.glob("aoi-*.jsonl*")) + sorted(logs.glob("crash*.log")):
        recent = p.stat().st_mtime >= start.timestamp() if p.name.startswith("crash") else p.name[4:14] >= cut
        if recent:
            files[f"logs/{p.name}"] = p
    data: dict[str, bytes] = {
        "heartbeat-history.jsonl": beats([p for k, p in files.items() if k.startswith("logs/aoi-")])
    }
    files[f"logs/{heartbeat.ALERTS}"] = logs / heartbeat.ALERTS
    files[heartbeat.HEARTBEAT] = root / heartbeat.HEARTBEAT
    if (folder := app_folder()) is not None:  # from source there is no build to describe
        files |= {name: folder / name for name in BUILD_FILES}
    settings = default_workspace() / "settings.json"  # the station's, wherever its workspace is (Settings._file)
    if settings.is_file():
        try:
            data["settings.json"] = json.dumps(_clean(json.loads(settings.read_text("utf-8"))), indent=1).encode()
        except (OSError, ValueError) as e:
            data["settings.json"] = f"not read: {type(e).__name__}".encode()
    problems: dict[str, str] = {}
    queries = {
        "schema_version.csv": "SELECT number, name, applied_at FROM schema_version ORDER BY number",
        "alarms.csv": "SELECT * FROM alarms WHERE time >= ? ORDER BY id",
        "audit.csv": "SELECT * FROM audit WHERE at_utc >= ? ORDER BY id",
    }
    for name, sql in queries.items():
        rows, why = _rows(db, sql, since)
        for r in rows:
            for column in ("before_json", "after_json"):
                if r.get(column):
                    r[column] = json.dumps(_clean(json.loads(r[column])), ensure_ascii=False)
        data[name] = csv_bytes(rows)
        if why:
            problems[name] = why
    if images:
        sql = "SELECT overlay_path FROM inspections WHERE time >= ? AND overlay_path IS NOT NULL ORDER BY id DESC"
        rows, _ = _rows(db, f"{sql} LIMIT {IMAGES_KEPT}", since)
        files |= {f"images/{Path(r['overlay_path']).name}": root / r["overlay_path"] for r in rows}
    manifest: dict[str, Any] = {"facts": facts(root), "images": images, "days": DAYS, "not_read": problems}
    manifest["missing"] = sorted(k for k, p in files.items() if not p.is_file())
    manifest["files"] = sorted([k for k, p in files.items() if p.is_file()] + list(data))

    def pack(f: BinaryIO) -> None:
        with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=1, default=str))
            for name, content in data.items():
                z.writestr(name, content)
            for name, p in files.items():
                if p.is_file():
                    z.write(p, name)

    atomic.write_with(dest, pack)
    return manifest


def held(dest: Path, images: bool, manifest: dict[str, Any]) -> dict[str, Any]:
    """What the audit entry `support.bundle` records of a bundle."""
    return {"file": dest.name, "images": images, "files": len(manifest["files"]), "missing": manifest["missing"]}


USAGE = "usage: AOI-PoC-Inspector.exe --support-bundle FILE.zip [WORKSPACE] [--images]"


def main(args: list[str]) -> int:
    """`main.py --support-bundle`, for a station whose window will not open: 0 when the bundle is written, 2 for wrong
    arguments, no workspace, or a bundle not written. Audited with no user, by one INSERT: no migration runs, and the
    workspace may be open in the app meanwhile."""
    from ..config import Settings
    from ..data.db import new_uuid

    images, rest = "--images" in args, [a for a in args if a != "--images"]
    if not 1 <= len(rest) <= 2:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        root = Path(rest[1]) if len(rest) == 2 else Settings.load().root
    except Exception:  # a settings.json that does not load: the station's default workspace
        root = default_workspace()
    if not (root / "aoi.sqlite").is_file():
        print(f"{root} holds no workspace (aoi.sqlite)", file=sys.stderr)
        return 2
    dest = Path(os.path.abspath(rest[0]))
    try:
        manifest = build(root, dest, images)
    except OSError as e:
        print(f"{dest} could not be written: {e}", file=sys.stderr)
        return 2
    after = json.dumps(held(dest, images, manifest), ensure_ascii=False, default=str)
    sql = "INSERT INTO audit(uuid, at_utc, action, object_type, after_json, reason) VALUES(?,?,?,?,?,?)"
    try:
        with contextlib.closing(sqlite3.connect(root / "aoi.sqlite", timeout=10)) as conn, conn:
            conn.execute(sql, (new_uuid(), now_utc(), "support.bundle", "workspace", after, "command line"))
    except sqlite3.Error as e:  # a damaged database: the bundle is what support needs, so it stands
        print(f"The bundle is written; the audit entry is not: {e}", file=sys.stderr)
    print(dest)
    return 0
