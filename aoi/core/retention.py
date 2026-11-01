"""The retention sweep's steps (REQ-LOG-010; ADR 0024 D1, D20, D21), which `AppContext.sweep_retention` runs at start
and every SWEEP_EVERY_S on a thread of its own: log files, migration backups, validation runs' overlays, orphan files.
No Qt here."""

from __future__ import annotations

import gzip
import os
import re
import shutil
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

from ..data.atomic import temp_path

SWEEP_EVERY_S = 3600
LOG_GZIP_DAYS, LOG_ARCHIVE_DAYS, LOG_DELETE_DAYS = 7, 30, 90  # D21: gzipped after 7 days, archived at 30, gone at 90
BACKUPS_KEPT = 3  # the newest migration backups kept beside the database
ORPHAN_AGE_S = 3600  # a younger file may be a save whose record is not committed yet
ARCHIVE = "archive"  # under logs/
TEST_RUNS = "test_runs"  # under results/: a validation run's overlays, one folder per run (REQ-TST-003)
COUNTS = ("ok_maps", "logs_gzipped", "logs_archived", "logs_deleted", "backups", "test_runs", "orphans", "skipped")
_LOG = re.compile(r"aoi-(\d{4}-\d{2}-\d{2})\.jsonl(\.gz)?")
_BACKUP = re.compile(r".*\.bak-\d{4}-to-\d{4}-(\d{8}T\d{6}Z)")  # migrate.backup's names; its temp copies differ
_OK_FILE = re.compile(r".*_OK(_prev\.jpg|_diff\.png|_ai2?\.png|\.jpg|\.png)")  # an OK board's files (`log_result`)


def _age(path: Path, today: date) -> int:
    """The age in days of a day's log file, from its name; -1 for a file not named as the log names its files."""
    try:
        return (today - date.fromisoformat(found[1])).days if (found := _LOG.fullmatch(path.name)) else -1
    except ValueError:  # a name with no such day
        return -1


def _each(paths: Iterable[Path], act: Callable[[Path], object], counts: dict[str, int], kind: str) -> None:
    """`act` on each path, counted under `kind`; one the system refuses (held open) is skipped till the next sweep."""
    for p in paths:
        try:
            act(p)
            counts[kind] = counts.get(kind, 0) + 1
        except OSError:
            counts["skipped"] = counts.get("skipped", 0) + 1


def _gzip(p: Path) -> None:
    packed = p.with_name(p.name + ".gz")
    with p.open("rb") as src, gzip.open(tmp := temp_path(packed), "wb") as dst:  # a crash leaves a temp file swept
        shutil.copyfileobj(src, dst)
    os.replace(tmp, packed)
    p.unlink()


def sweep_logs(folder: Path, today: date, delete: bool, counts: dict[str, int]) -> None:
    """Gzip each day's log file LOG_GZIP_DAYS old or more (today's, still open, is never one), move a gzipped one
    LOG_ARCHIVE_DAYS old to logs/archive/, and when `delete` remove one there LOG_DELETE_DAYS old."""
    _each([p for p in folder.glob("aoi-*.jsonl") if _age(p, today) >= LOG_GZIP_DAYS], _gzip, counts, "logs_gzipped")
    archive = folder / ARCHIVE
    old = [p for p in folder.glob("aoi-*.jsonl.gz") if _age(p, today) >= LOG_ARCHIVE_DAYS]
    archive.mkdir(exist_ok=True)
    _each(old, lambda p: os.replace(p, archive / p.name), counts, "logs_archived")
    gone = [p for p in archive.glob("aoi-*.jsonl.gz") if delete and _age(p, today) >= LOG_DELETE_DAYS]
    _each(gone, Path.unlink, counts, "logs_deleted")


def sweep_backups(database: Path, counts: dict[str, int]) -> None:
    """Delete every migration backup beside `database` but the BACKUPS_KEPT newest, by the time in their names."""
    found = [(m[1], p) for p in database.parent.glob(f"{database.name}.bak-*") if (m := _BACKUP.fullmatch(p.name))]
    _each([p for _, p in sorted(found)[:-BACKUPS_KEPT]], Path.unlink, counts, "backups")


def sweep_test_runs(folder: Path, kept: set[str], now: float, counts: dict[str, int]) -> None:
    """Delete each validation run's overlay folder under `folder` whose run is not in `kept` (stored runs newer than
    their days), once ORPHAN_AGE_S old: a run still being judged has not been stored yet."""
    old = [p for p in folder.glob("*") if p.is_dir() and p.name not in kept and now - p.stat().st_mtime >= ORPHAN_AGE_S]
    _each(old, shutil.rmtree, counts, "test_runs")


def sweep_orphans(results: Path, named: set[Path], now: float, counts: dict[str, int]) -> None:
    """Delete the OK boards' files under `results` that no record names, ORPHAN_AGE_S old or more: a save writes its
    files before its record, so a younger one may still get it. An NG or WARN board's file, or any other, is never
    deleted here: after a database restored from a copy, records saved since are gone but their evidence is kept."""
    files = (p for p in results.glob("*/*") if p.parent.name != TEST_RUNS and _OK_FILE.fullmatch(p.name))
    old = [p for p in files if p.resolve() not in named and now - p.stat().st_mtime >= ORPHAN_AGE_S]
    _each(old, Path.unlink, counts, "orphans")
