"""Application services: the only layer the UI calls.

Keeps the Qt pages thin and lets the same workflows run headless (tests, CLI,
and later a Stage 3 robot cycle or Stage 4 MES hook).
"""

from __future__ import annotations

import contextlib
import contextvars
import csv
import errno
import functools
import hashlib
import io
import json
import math
import os
import random
import secrets
import threading
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Concatenate, Literal, ParamSpec, TypeVar, cast

import numpy as np

from .. import defects as taxonomy
from .. import logging_setup
from ..config import Settings, resolve_device
from ..data import atomic, credentials
from ..data.db import Database, DbError, is_busy, new_uuid
from ..data.errors import WorkspaceError
from ..data.paths import inside, one_folder_name, resolve, to_stored
from ..data.workspace_lock import WorkspaceLock
from ..errors import QT_TRANSLATE_NOOP, AoiError, Phrase, joined
from ..hal import VIEWS
from ..times import local_date, now_utc
from . import anomaly, crypto, datasets, golden, imaging, labels, run_progress, stores
from .compare import Region, changed_regions
from .imaging import (
    align_to_reference,
    encode_image,
    list_images,
    load_image,
    load_image_sha256,
    registration,
    save_image,
    warp_to,
)
from .inspector import NG, OK, WARN, AiEvidence, InspectionResult, Inspector, JudgedBy, ai_check, draw_overlay, re_grade
from .jobs import JobCancelled, Jobs
from .labels import DefectBox
from .maps import load_maps, map_paths, picture_shape, save_maps
from .recipe import Recipe
from .sample_import import LABELS, REFUSED, ImportFile, ImportReport

ALARM_LIMIT = 1000  # REQ-INSP-006: the alarms a screen shows and that survive a restart
BUSY_ALARM_WAIT_MS = 200  # how long the alarm of a locked database's error, or an Inspection alarm, waits, not 5 s
ALIGNING = QT_TRANSLATE_NOOP("Training", "Aligning {count} images to the reference board")  # a progress line (#199)
# what a training run does now, as its progress names it (REQ-TRN-008)
READING = QT_TRANSLATE_NOOP("Training", "Aligning image {n} of {count}")
BAND = QT_TRANSLATE_NOOP("Training", "Golden board, part {band} of {bands}: image {n} of {count}")
MEDIAN = QT_TRANSLATE_NOOP("Training", "Building the Golden board: step {n} of {count}")
EPOCH = QT_TRANSLATE_NOOP("Training", "Training epoch {epoch} of {epochs}")
CALIBRATING = QT_TRANSLATE_NOOP("Training", "Calibrating: map {n} of {count}")
SAVING = QT_TRANSLATE_NOOP("Training", "Saving AI model {version}")
NO_TYPE = QT_TRANSLATE_NOOP("Errors", "no defect type was given")  # why AOI-TRN-013 refused an NG sample
NOT_A_TYPE = QT_TRANSLATE_NOOP("Errors", "{name} is not one of them")
STEM_CHARS = 40  # how much of a source file's stem names its evidence or sample file (#245)
WINDOWS = os.name == "nt"
MAX_PATH = 260  # the UTF-16 units of a path, its ending NUL included, that Windows takes with long paths off
NAME_MAX = 255  # the UTF-16 units of one name in a path that Windows takes, long paths on or off
NO_BOARD_MODEL = QT_TRANSLATE_NOOP("Errors", "there is no board model of that name")  # AOI-RCP-008's reasons (S29)
SCALE_NUMBERS = QT_TRANSLATE_NOOP(
    "Errors",
    "a length of {length} px over {distance} mm gives no scale: both must be numbers above 0, and the scale from"
    " {least} to {most} px per mm",
)
# px per mm a scale set holds: from 2, so that no ROI of an image up to 20000 px wide is over MAX_MM (AOI-RCP-011),
# and up to 100000, so that no size in mm overflows in px (S29 review)
MIN_SCALE, MAX_SCALE = 2, 100000


@dataclass(frozen=True)
class ErrorReport:
    """What a user sees of an error: the code, a title, what happened and what to do. Never a stack trace."""

    code: str
    title: str
    what: str
    action: str

    @classmethod
    def of(cls, exc: BaseException, context: str = "") -> ErrorReport:
        """The report for any exception: an AoiError's own code, else AOI-SET-007 naming the exception type."""
        if not isinstance(exc, AoiError):  # the context, a page title or a phrase, is shown in the UI language (#198)
            where = QT_TRANSLATE_NOOP("Errors", " ({context})").fill(context=context) if context else ""
            exc = AoiError("AOI-SET-007", error_type=type(exc).__name__, context=where)
        return cls(exc.code, exc.title, exc.what, exc.action)


@dataclass(frozen=True)
class CsvFile:
    """One file of a CSV export: where it goes, its rows, what they are (the audit entry's object type) and its header
    when `rows` may be empty."""

    path: str | Path
    rows: list[dict[str, Any]]
    what: str = "inspections"
    fieldnames: list[str] | None = None


@dataclass(frozen=True)
class BoardStatus:
    """Where the six-step workflow stands for a board model (the Home page's cards)."""

    ok_samples: int
    ng_samples: int
    model_version: str | None  # the active AI model, or None while none is trained
    recipe_revision: int  # the stored revision in use; revision 1 is the default recipe, stored with the board model
    recipe_is_default: bool  # the revision in use is that stored default (by "system"): no ROI drawn yet
    last_test: dict[str, Any] | None  # metrics of the latest AI model test run
    inspected: int
    ng: int


@dataclass(frozen=True)
class Actor:
    """A user as one value: name, role and UUID (None for a picked name with no users row). `set_user` replaces it as
    a whole, so a reader on another thread never pairs one user's UUID with another's role (#177)."""

    name: str
    role: str
    uuid: str | None


# Who acts in this thread or job: set by `requires` for the call it checks, and by `AppContext.jobs` for each job from
# the moment it is submitted, so a job acts as the user who started it whoever signs in meanwhile (#177).
_ACTING: contextvars.ContextVar[tuple[AppContext, Actor] | None] = contextvars.ContextVar("aoi_acting", default=None)

ROLES = ("Operator", "Engineer", "Admin")  # lowest to highest (GUI §8, docs/ARCHITECTURE.md §5)
ROLES_FROM = {  # a role and the roles above it, as AOI-USR-001 names them: one phrase each, never joined (#198)
    "Operator": QT_TRANSLATE_NOOP("Errors", "Operator, Engineer or Admin"),
    "Engineer": QT_TRANSLATE_NOOP("Errors", "Engineer or Admin"),
    "Admin": QT_TRANSLATE_NOOP("Errors", "Admin"),
}
REQUIRED_ROLE: dict[str, str] = {}  # AppContext write, or Engineer-only call -> the lowest role allowed to call it
P = ParamSpec("P")
R = TypeVar("R")
# A stored result's golden board, as `judged_reference` finds it.
Judged = Literal["same", "none", "unrecorded", "missing", "unreadable", "changed"]


def _calibration(model: dict[str, Any] | None) -> tuple[float, float] | None:
    """An AI model registry row's image and pixel thresholds, as training stored them from the AI model file's
    metadata; None for no row, or one without two finite numbers above 0 (only a row changed by hand has none)."""
    try:
        cal = json.loads(model["metrics"]) if model else {}
        found = cal["image_threshold"], cal["pixel_threshold"]
        image_thr, pixel_thr = (math.nan if isinstance(v, bool) else float(v) for v in found)
    except (ValueError, TypeError, KeyError, OverflowError):
        return None
    return (image_thr, pixel_thr) if min(image_thr, pixel_thr) > 0 and math.isfinite(image_thr + pixel_thr) else None


def requires(
    role: str, what: str
) -> Callable[[Callable[Concatenate[AppContext, P], R]], Callable[Concatenate[AppContext, P], R]]:
    """The one role check for every write, and for what only an Engineer does without writing (re-evaluating a result
    with other thresholds, REQ-CMP-005) (ADR 0002, decision 5): refuse with AOI-USR-001 when the current role is below
    `role`. `what` names the action in the message: "Saving a recipe needs the Engineer or Admin role."; it is a phrase
    marked QT_TRANSLATE_NOOP("Errors", …), so the dialog shows it in the UI language.
    The user checked is the one acting (`AppContext.actor`), and the call, with every audit entry and record it writes,
    acts as that user to its end, whoever signs in meanwhile (#177)."""

    def wrap(fn: Callable[Concatenate[AppContext, P], R]) -> Callable[Concatenate[AppContext, P], R]:
        REQUIRED_ROLE[fn.__name__] = role

        @functools.wraps(fn)
        def checked(self: AppContext, *args: P.args, **kwargs: P.kwargs) -> R:
            actor = self.actor
            if actor.role not in ROLES or ROLES.index(actor.role) < ROLES.index(role):
                raise AoiError("AOI-USR-001", what=what, roles=ROLES_FROM[role])
            token = _ACTING.set((self, actor))
            try:
                return fn(self, *args, **kwargs)
            finally:
                _ACTING.reset(token)

        return cast("Callable[Concatenate[AppContext, P], R]", checked)

    return wrap


def transactional(fn: Callable[Concatenate[AppContext, P], R]) -> Callable[Concatenate[AppContext, P], R]:
    """Run a write that touches only the database, its audit entry included, in one transaction: both are stored or
    neither is (#178). Goes under `requires`, so a refused call opens none."""

    @functools.wraps(fn)
    def run(self: AppContext, *args: P.args, **kwargs: P.kwargs) -> R:
        with self.db.transaction():
            return fn(self, *args, **kwargs)

    return cast("Callable[Concatenate[AppContext, P], R]", run)


def _stem(path: str | Path) -> str:
    """The start of a source file's stem that names the file the app keeps of it, beside its UUID (#245): with the
    longest ending, `_<UUID>_WARN_diff.png`, and the temporary name around it, a name of at most 225 bytes in UTF-8."""
    return Path(path).stem[:STEM_CHARS]


def _too_long(e: OSError) -> bool:
    """The system refused a path as too long: ENAMETOOLONG, or on Windows ERROR_FILENAME_EXCED_RANGE or a file not found
    at a path of MAX_PATH UTF-16 units or more, which is how open() fails there with long paths off (#245), or a path
    holding a name of more than NAME_MAX units, which Windows refuses with long paths on as a name not valid (S35)."""
    if e.errno == errno.ENAMETOOLONG or getattr(e, "winerror", None) == 206:
        return True
    if not WINDOWS:
        return False
    paths = [str(p) for p in (e.filename, e.filename2) if p]
    if any(_units(name) > NAME_MAX for p in paths for name in PureWindowsPath(p).parts):
        return True
    return isinstance(e, FileNotFoundError) and _units(str(e.filename or "")) >= MAX_PATH


def _units(text: str) -> int:
    """The UTF-16 units Windows counts in a path or name: one for each character, two outside the BMP."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _remove(files: list[Path]) -> None:
    """Remove files a write made before it failed, so none is left that its records or audit entry do not name."""
    for f in files:
        with contextlib.suppress(OSError):
            f.unlink(missing_ok=True)


class AppContext:
    def __init__(self, settings: Settings | None = None, key_store: credentials.Credentials | None = None) -> None:
        self.settings = settings or Settings.load()
        # each customer's dataset store key (REQ-TRN-017): Credential Manager on a station, never the workspace
        self.credentials = key_store if key_store is not None else credentials.default()
        self._keys: dict[str, bytes] = {}  # store UUID -> its key, read once and checked against its check value
        try:
            self.settings.ensure_dirs()
        except OSError as e:  # a drive not connected, a file where the folder must go (REQ-SET-019)
            raise WorkspaceError("AOI-SET-011", path=str(self.settings.root), error=str(e)) from e
        # One copy of the app per workspace: a second one is refused with AOI-SET-012 before it opens or deletes
        # anything, so the sweep below only meets what a crash left (#204)
        self._lock = WorkspaceLock.acquire(self.settings.root)
        try:
            self.log = logging_setup.setup(self.settings.root)
        except BaseException:
            self._lock.release()
            raise
        try:
            self.db = Database(self.settings.db_path, self.settings.root)
        except BaseException:
            logging_setup.close(self.log)  # nor is the refused workspace's log file (REQ-SET-016)
            self._lock.release()
            raise
        try:  # the first writes: the drive may refuse them, or another program hold the database (#171, #204)
            self.device = resolve_device(self.settings.device)
            swept, skipped = atomic.sweep_temp_files(self.settings.root)  # a crash mid-write leaves only a temp file
            for path, reason in skipped:  # harmless: kept, and tried again at the next start (#204)
                rel = path.relative_to(self.settings.root).as_posix()
                self.log.warning("sweep.skipped", extra={"path": rel, "reason": reason})
            extra = {"workspace": str(self.settings.root), "device": self.device, "swept": swept}
            self.log.info("app.start", extra=extra)
            self.set_user(self.start_user())  # the role the users table holds, never one written here (#197)
            archived = self.db.archive_old(self.settings.log_retention_days)  # retention is a system action
            self.log.info("retention.archived", extra={"days": self.settings.log_retention_days, "archived": archived})
            self._sweep_ok_maps()  # the map files of OK results past their retention go too (REQ-INSP-012, S25c)
            for board_model in self.db.board_models():
                self._ensure_recipe(board_model)  # a workspace from before S25: its results name a stored revision too
        except BaseException as e:
            self.db.close()  # a refused workspace holds no file open while another folder is chosen (REQ-SET-016)
            logging_setup.close(self.log)
            self._lock.release()
            if isinstance(e, DbError):  # a coded refusal the folder picker follows, not AOI-SET-007
                raise self.db.refusal(e) from e
            raise
        # board model -> (device, (version, model, uuid)): the weights of the active version, on the device they sit on
        self._model_cache: dict[str, tuple[str, tuple[str, anomaly.AnomalyModel, str]]] = {}
        # background work (REQ-SET-021): screens submit through aoi/ui/workers, tests directly; a job acts as the user
        # who submitted it (#177)
        self.jobs = Jobs(context=self._acting_context)
        self._golden_alarmed: set[tuple[str, str | None, str]] = set()  # each (board model, file, code) alarmed (#195)
        self._golden_lock = threading.Lock()  # the Recipe Editor reads on the UI thread, Compare on the pool's
        self._closed = False

    # --- dataset -------------------------------------------------------------

    def close(self) -> None:
        """Release the database and the log file, as a restart or a change of workspace does; a workspace folder
        can be moved only once nothing holds a file in it open."""
        if self._closed:  # the window closes it, and main.py again after the event loop (#171)
            return
        self._closed = True
        self.jobs.shutdown()  # a running job may still read the database or write a file
        self.db.close()
        logging_setup.close(self.log)
        self._lock.release()  # last: another copy may open the workspace now (#204)

    def set_user(self, name: str) -> None:
        """Make `name` the current user, with the UUID and the role the users table holds for them: the table is the
        only source of a role, so the role check and every audit entry name the stored one (#197). A name the table
        does not hold is refused with AOI-USR-003. G1 keeps v0.1's user picker (ADR 0002), so this records who was
        picked, not who proved it. A job already submitted, and a role-checked call already running, go on as the user
        who started them (#177)."""
        row = next((u for u in self.db.users() if u["name"] == name), None)
        if row is None:
            raise AoiError("AOI-USR-003", name=name)
        self._actor = Actor(name, str(row["role"]), str(row["uuid"]))

    def start_user(self, setting_up: bool = False) -> str:
        """The name of the user a start signs in: while the station is set up (no board model yet), the first user
        the table holds as Admin; otherwise 'operator'. Without either (a table edited outside the app), the first
        user of the lowest stored role. Its role is the stored one, whatever the name (#197)."""
        users = self.db.users()  # never empty: the database seeds operator, engineer and admin
        if setting_up and (admin := next((u for u in users if u["role"] == "Admin"), None)):
            return str(admin["name"])
        if any(u["name"] == "operator" for u in users):
            return "operator"
        rank = {r: i for i, r in enumerate(ROLES)}
        return str(min(users, key=lambda u: rank.get(u["role"], len(ROLES)))["name"]) if users else "operator"

    @property
    def actor(self) -> Actor:
        """The user acting now: in a role-checked call, or in a job, the one it started as; else the signed-in user."""
        acting = _ACTING.get()
        return acting[1] if acting is not None and acting[0] is self else self._actor

    @property
    def user(self) -> str:
        return self.actor.name

    @property
    def role(self) -> str:
        return self.actor.role

    @property
    def user_uuid(self) -> str | None:
        return self.actor.uuid

    def _acting_context(self) -> contextvars.Context:
        """The context a job runs in: the submitter's, acting as the user acting at submit (#177)."""
        context = contextvars.copy_context()
        context.run(_ACTING.set, (self, self.actor))
        return context

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Importing samples"))
    def import_samples(
        self,
        board_model: str,
        paths: list[str],
        label: str,
        defect_type: str | None = None,
        side: str = "Top",
        progress: Callable[[int, int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        already: list[dict[str, Any]] | None = None,
    ) -> int:
        """Copy uploads into the workspace so training data survives the source folder moving; returns how many were
        added. Each file goes through `_copy_checked` (REQ-TRN-001): checked as Inspection checks an image, never
        written, its SHA-256 recorded with the sample; an image the board model already has, or one earlier in
        `paths`, is skipped (decision Q31), and the audit entry counts it and names the sample that has it by UUID and
        SHA-256 (`skipped`, `already`). An NG import names one of the 33 DCT types (AOI-TRN-013). All or nothing
        (#178): a file refused, or one that cannot be copied (AOI-TRN-008, or AOI-TRN-011 when the system refuses the
        copy's path as too long, #245), stops the import with its code and removes the copies made; then the samples, a
        new board model's default recipe and reference, and the audit entry, which names each sample added by its UUID
        and SHA-256 (`samples`), commit together. `progress(done, total)` follows each file, and once `should_stop()` is
        true the files not yet copied are left out, the ones copied are added and the audit entry says so
        (`cancelled`); `import_files` passes one file a call and stops between calls, so the entries it writes never
        say so. `already`, when given, gets the sample each skipped image is already (`import_files` names it)."""
        self._refuse_unsafe_name(board_model)  # a new board model is created by its first import
        self._refuse_case_variant(board_model)
        first = paths[0] if paths else ""
        if label not in LABELS:  # the copy's folder is named after it, and the samples table holds no other
            raise AoiError("AOI-TRN-018", path=first, label=label, labels=", ".join(LABELS))
        self._refuse_untyped(first, label, defect_type)
        if side not in VIEWS:  # a dataset version names its folders by view (S35): no other name reaches a path
            raise AoiError("AOI-TRN-017", path=first, view=side, views=", ".join(VIEWS))
        dest = self.settings.images_dir / board_model / label
        if not inside(dest, self.settings.images_dir):  # a board model named before names were checked (#112)
            raise AoiError("AOI-TRN-019", name=board_model)
        known: dict[str, dict[str, Any]] = {}  # each image copied so far, by SHA-256: a second one is skipped too
        copies: list[tuple[Path, str, str]] = []  # each copy, its sample UUID (which its file name carries, #245), hash
        stopped, kept = False, list[tuple[str, dict[str, Any]]]()  # each image skipped: its SHA-256, the sample with it
        try:
            for p in paths:
                if should_stop is not None and should_stop():
                    stopped = True
                    break
                src, uid = Path(p), new_uuid()
                target = dest / f"{_stem(src)}_{uid}{src.suffix.lower()}"
                digest, same = self._copy_checked(board_model, src, target, known, len(paths))
                if same is not None:
                    kept.append((digest, same))
                else:
                    copies.append((target, uid, digest))
                    known[digest] = {"uuid": uid, "path": str(target), "label": label}
                if progress is not None:
                    progress(len(copies) + len(kept), len(paths))
            with self.db.transaction():
                for target, uid, digest in copies:  # the first creates a new board model
                    self.db.add_sample(
                        board_model, str(target), label, defect_type, side, uid, self.user_uuid, sha256=digest
                    )
                if copies:
                    self._ensure_recipe(board_model)
                if not self.db.reference(board_model):
                    oks = self.db.samples(board_model, "OK")
                    if oks:
                        self.db.set_reference(board_model, oks[0]["path"])
                after: dict[str, Any] = {"label": label, "defect_type": defect_type, "side": side, "added": len(copies)}
                after |= {"skipped": len(kept), "cancelled": stopped}
                after["samples"] = [{"uuid": uid, "sha256": digest} for _, uid, digest in copies]
                after["already"] = [{"uuid": had["uuid"], "sha256": digest} for digest, had in kept]
                self.audit("sample.import", "board_model", board_model, None, after)
        except BaseException:
            _remove([target for target, _, _ in copies])
            raise
        if already is not None:
            already.extend(had for _, had in kept)
        return len(copies)

    def _refuse_untyped(self, path: str, label: str, defect_type: str | None) -> None:
        """Refuse an NG sample without one of the 33 DCT types, named as the classification table names it
        (AOI-TRN-013, REQ-TRN-001): no type, "Unknown" or the AI model's "Anomaly" is never a sample's type."""
        if label == "NG" and defect_type not in taxonomy.names():
            why = NOT_A_TYPE.fill(name=defect_type) if defect_type else NO_TYPE
            raise AoiError("AOI-TRN-013", path=path, why=why)

    def _copy_checked(
        self, board_model: str, src: Path, target: Path, known: dict[str, dict[str, Any]], count: int
    ) -> tuple[str, dict[str, Any] | None]:
        """Copy one sample's source file to `target` and return its SHA-256 and None (REQ-TRN-001). The source is only
        read: its bytes are checked and decoded as Inspection checks an image (`checked_bytes`: AOI-INSP-001, -004 to
        -007, decision Q30) and hashed; an image already imported, one `board_model` has (one indexed lookup) or one
        of `known`, copies nothing and comes back with that sample (decision Q31). The copy is a crash-safe write; then
        the source and the copy are read again, and a SHA-256 other than the one checked (a writer still at the source)
        refuses the file with AOI-TRN-014 and removes the copy. A board model in a customer's dataset store gets its
        copy encrypted from the bytes checked, never written plain, and read back decrypted (REQ-TRN-017). A source
        lost since its check (removed, unreadable) is refused with AOI-INSP-001, as Inspection's check would; a copy
        that cannot be written raises AOI-TRN-008, or AOI-TRN-011 when the system refuses its path as too long
        (#245)."""
        data = imaging.checked_bytes(src, self.settings.max_image_megapixels, self.settings.max_image_megabytes)
        digest = hashlib.sha256(data).hexdigest()
        if (had := known.get(digest) or self.db.sample_with_sha256(board_model, digest)) is not None:
            return digest, had
        sealed = self._sealed(to_stored(target, self.settings.root), data)  # the bytes checked, in the store's form
        del data  # up to the size limit in memory: not kept through the copy
        try:
            if sealed is None:
                atomic.copy_file(src, target)
            else:  # a board model in a customer's dataset store: its copy is encrypted from the start (REQ-TRN-017)
                atomic.write_bytes(target, sealed)
                del sealed
        except OSError as e:  # gone, unreadable, the workspace drive full, or a path the system refuses
            if str(e.filename) == str(src):  # the source's own: that file's to fix, listed by import_files
                raise AoiError("AOI-INSP-001", str(e), path=str(src)) from e
            if _too_long(e):  # the copy's path (#245)
                where = {"workspace": str(self.settings.root), "count": count}
                raise AoiError("AOI-TRN-011", str(e), path=str(src), **where) from e
            why = e.strerror or str(e)
            raise AoiError("AOI-TRN-008", str(e), path=str(src), reason=why, count=count) from e
        try:
            same = _sha256(src) == digest == self._file_sha256(target)
        except (OSError, AoiError):  # the source gone right after its copy, or a copy that does not read back
            same = False
        if not same:
            _remove([target])
            raise AoiError("AOI-TRN-014", path=str(src))
        return digest, None

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Importing samples"))
    def import_files(
        self,
        board_model: str,
        files: list[ImportFile],
        progress: Callable[[int, int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> ImportReport:
        """Import each file with its own label, defect type and view, one `import_samples` call each, so what went in
        stays when Cancel or an error stops the rest (#178, #206); the import sheet on Training runs it on the pool
        (REQ-TRN-001). A file refused with a code in `REFUSED` (Inspection's checks, a source lost before its copy
        among them, an NG with no type, a source changed while copied, a view or a label not known), one with no label
        (AOI-TRN-016) and an image the board model already has (AOI-TRN-015, naming that sample and its label, decision
        Q31) is listed with its error and the import goes on; any other error, such as a copy the workspace refuses or
        the database, stops it at that file. `progress(done, total)` follows each file, and once `should_stop()` is
        true the files not yet imported are left."""
        report = ImportReport()
        for i, f in enumerate(files):
            if should_stop is not None and should_stop():
                report.left = files[i:]
                break
            try:
                if f.label is None:
                    raise AoiError("AOI-TRN-016", path=f.path)
                had: list[dict[str, Any]] = []
                if not self.import_samples(board_model, [f.path], f.label, f.defect_type, f.side, already=had):
                    sample = {"sample": Path(had[0]["path"]).name, "label": had[0]["label"]}
                    raise AoiError("AOI-TRN-015", path=f.path, board_model=board_model, **sample)
                report.added.append(f)
            except Exception as e:
                if not (isinstance(e, AoiError) and e.code in REFUSED):
                    report.stopped, report.left = (f, e), files[i + 1 :]
                    break
                report.refused.append((f, e))
            if progress is not None:
                progress(i + 1, len(files))
        return report

    # --- training ------------------------------------------------------------
    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Training an AI model"))
    def train(
        self,
        dataset_uuid: str,
        epochs: int | None = None,
        image_size: int | None = None,
        progress: Callable[[run_progress.RunProgress], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        use: str = "own",
    ) -> dict[str, Any]:
        """Train an AI model of a frozen dataset version's board model on the version's training set, for `use` (its
        customer's own AI models by default), then save, register, activate and audit it (REQ-TRN-007). The OK images
        train it and make the Golden board; the NG images only calibrate its threshold; the locked validation set is
        never read. Refused, before any image is read, as `_training_set` gives. A file whose SHA-256, of the bytes
        read, is not the one frozen stops the run with AOI-TRN-045. The run reads the device once, before it loads
        anything, and keeps it to the end (#201).

        Memory (REQ-TRN-007): each image is read, registered onto the board model's reference board (else the first OK
        image) and warped, then kept only as its tensor at the network's input size and its band of the Golden board's
        median (aoi/core/golden.py); each later band reads the OK images again and warps them with the homography kept.
        So a run holds one image at the camera's resolution at a time, one band of every OK image, and the tensors.

        Progress (REQ-TRN-008): `progress(RunProgress)` follows every image read, step of the Golden board's median,
        training step and calibration map, each with the time left (aoi/core/run_progress.py), known from the second
        report on: a step of each other kind is timed on the first image read (`Median.probe`, `anomaly.probe`).
        `should_stop()` is asked after each, and once it is true the run raises JobCancelled there, having saved
        nothing; it is asked for the last time once the AI model's files are written, which it then removes."""
        device = self.device  # not self.device later: save_settings may change it while the samples load and align
        say = progress or (lambda p: None)
        stop = should_stop or (lambda: False)
        frozen, ok_items, ng_items = self._training_set(dataset_uuid, use)
        board_model = frozen["board_model"]
        out = self.settings.models_dir / board_model
        cfg = anomaly.TrainConfig(
            image_size=image_size or self.settings.image_size,
            epochs=epochs or self.settings.default_epochs,
            device=device,
        )
        n_ok, n_ng = len(ok_items), len(ng_items)
        maps = (anomaly.held_out(n_ok, cfg.val_fraction) or n_ok) + n_ng  # held-out OK maps, else every OK's; the NG's
        eta = run_progress.Eta({"read": 1 + n_ok + n_ng, "step": cfg.epochs * cfg.steps_per_epoch, "map": maps})

        def check() -> None:  # Cancel, or the window closing: nothing saved, registered, activated or audited (#171)
            if stop():
                raise JobCancelled(f"training {board_model}")

        def read(phase: Phrase) -> None:  # an image read: reported, then the run stops there if asked
            eta.tick("read")
            say(eta.report(phase))
            check()

        def engine(kind: str, n: int, total: int, note: str) -> None:  # anomaly.train's steps and maps
            if n > eta.done[kind]:
                eta.tick(kind)
            epoch = max(1, -(-n // cfg.steps_per_epoch))  # the epoch of step n, the first before any
            phase = EPOCH.fill(epoch=epoch, epochs=cfg.epochs) if kind == "step" else CALIBRATING.fill(n=n, count=total)
            say(eta.report(phase, note))

        aligning = ALIGNING.fill(count=n_ok + n_ng)
        say(eta.report(aligning, aligning))
        check()
        ref_path = self.db.reference(board_model)
        if ref_path and Path(ref_path).exists():  # the board model's reference board, as Inspection aligns to it
            anchor = self.load_image(ref_path)
        else:
            anchor = self._read_frozen(frozen, ok_items[0])
        eta.tick("read")
        size = (anchor.shape[1], anchor.shape[0])
        band = golden.BAND_BYTES  # read here rather than as Median's defaults, so a test can set them
        board = golden.Median(n_ok, (anchor.shape[0], anchor.shape[1]), band, golden.STEP_BYTES)
        bands = len(board.bands)
        eta.counts["read"] += (bands - 1) * n_ok  # each later band reads the OK images again
        eta.counts["median"] = board.steps
        step_s, map_s = anomaly.probe(anomaly.prepare(anchor, cfg.image_size), cfg)
        eta.sample("step", step_s)  # each kind timed on the first image read, so the time left is known from here on
        eta.sample("map", map_s)
        eta.sample("median", board.probe())

        def built() -> None:  # a step of a band's median: reported, then the run stops there if asked
            eta.tick("median")
            say(eta.report(MEDIAN.fill(n=eta.done["median"], count=board.steps)))
            check()

        say(eta.report(aligning))
        check()
        kept: list[np.ndarray | None] = []
        ok_in: list[anomaly.Prepared] = []
        for n, item in enumerate(ok_items, 1):
            image = self._read_frozen(frozen, item)
            homography = registration(image, anchor)[0]
            warped = warp_to(image, homography, size)
            del image  # the image at the camera's resolution goes; its tensor and its first band stay
            kept.append(homography)
            ok_in.append(anomaly.prepare(warped, cfg.image_size))
            read(READING.fill(n=n, count=n_ok + n_ng))
            board.add(warped, built)
        ng_in: list[anomaly.Prepared] = []
        for n, item in enumerate(ng_items, n_ok + 1):
            aligned = align_to_reference(self._read_frozen(frozen, item), anchor)[0]
            ng_in.append(anomaly.prepare(aligned, cfg.image_size))
            read(READING.fill(n=n, count=n_ok + n_ng))
        for part in range(2, bands + 1):  # each later band of the median: every OK image read again, warped as before
            for n, (item, homography) in enumerate(zip(ok_items, kept, strict=True), 1):
                warped = warp_to(self._read_frozen(frozen, item), homography, size)
                read(BAND.fill(band=part, bands=bands, n=n, count=n_ok))
                board.add(warped, built)
        model = anomaly.train(ok_in, ng_in, cfg, engine, should_stop)
        check()
        previous = self.db.active_model(board_model)
        out.mkdir(parents=True, exist_ok=True)

        def files(v: str) -> list[Path]:
            return [out / f"{board_model}_{v}.pt", out / f"{board_model}_{v}_golden.png"]

        # never a name whose file is on disk: a result may name a Golden board that a run left unregistered (#178)
        version = self.db.next_model_version(board_model, lambda v: any(f.exists() for f in files(v)))
        path, golden_path = files(version)
        say(eta.report(SAVING.fill(version=version)))
        model_uuid = new_uuid()  # in the file's metadata and in the registry row, so an exported .pt names its record
        model.meta.update(board_model=board_model, version=version, uuid=model_uuid, created_at=now_utc())
        model.meta.update(dataset=frozen["name"], dataset_uuid=dataset_uuid, use=use)
        try:
            model.save(path)
            save_image(golden_path, board.board)
            model.meta["golden_image"] = to_stored(golden_path, self.settings.root)
            check()  # the last chance to stop: once registered, the run ends with it; the files go below
            summary = {k: v for k, v in model.meta.items() if k not in ("loss_history", "err_mean", "err_std")}
            with self.db.transaction():  # the Golden board in use, the active version and the entry change together
                before = self.db.reference(board_model)
                self.db.set_reference(board_model, str(golden_path))
                self.db.register_model(board_model, version, str(path), summary, activate=True, uid=model_uuid)
                old = {
                    "active_version": previous["version"] if previous else None,
                    "reference": to_stored(Path(before), self.settings.root) if before else None,
                }
                self.audit("model.train", "model", model_uuid, old, {"version": version, "metrics": summary})
        except BaseException:
            _remove(files(version))  # not registered: no file is left for a later run to take for its own
            raise
        self._model_cache.pop(board_model, None)
        self.log.info("training.finished", extra={"board_model": board_model, "model_version": version})
        return model.meta

    def load_model(self, board_model: str) -> tuple[str, anomaly.AnomalyModel, str] | None:
        """The active model of a board model as (version, model, uuid), the three from one row so a record never names
        one version's UUID with another's weights; the weights are cached by version and device. A load that was
        running when save_settings changed the device returns its model to its caller but does not cache it, and a
        cached model is used only on the device in use, so no later board runs on the old device (#201)."""
        rec = self.db.active_model(board_model)
        if not rec:
            return None
        device = self.device
        cached = self._model_cache.get(board_model)
        if cached and cached[0] == device and cached[1][0] == rec["version"]:
            return cached[1]
        m = anomaly.AnomalyModel.load(rec["path"], device)
        if m.meta.get("uuid") != rec["uuid"]:  # another AI model's file in its place, such as one written over it
            why = QT_TRANSLATE_NOOP("Errors", "its UUID {found} is not {uuid}, as in the AI model registry").fill(
                found=m.meta.get("uuid") or QT_TRANSLATE_NOOP("Errors", "(none)"), uuid=rec["uuid"]
            )
            raise anomaly.ModelFileError("AOI-TRN-001", path=rec["path"], reason=why)
        loaded = (rec["version"], m, str(rec["uuid"]))
        if self.device == device:
            self._model_cache[board_model] = (device, loaded)
        return loaded

    # --- recipe --------------------------------------------------------------
    def recipe(self, board_model: str) -> tuple[int, Recipe]:
        """The recipe revision in use: (revision, recipe); the defaults as revision 0 only for a board model that was
        made outside AppContext and so has no stored revision."""
        latest = self.db.latest_recipe(board_model)
        if latest:
            return latest[0], Recipe.from_dict(latest[1])
        return 0, Recipe(board_model=board_model)

    def _ensure_recipe(self, board_model: str) -> None:
        """Store the default recipe as revision 1 for a board model that has no revision yet, so every result names
        the stored recipe revision, and its UUID, that decided it (REQ-INSP-012). No verdict changes: the defaults
        were the recipe in use. Recorded as the system's, with an audit entry, since a recipe decides verdicts; the
        revision and its entry are stored together or not at all (#178)."""
        with self.db.transaction():
            if self.db.latest_recipe(board_model) is not None:
                return
            body = Recipe(board_model=board_model).to_dict()
            rev, uid = self.db.save_recipe(board_model, body, "system")
            reason = "default recipe stored as revision 1"
            self.db.add_audit(None, None, "recipe.default", "recipe", uid, None, body, reason)
        self.log.info("recipe.default", extra={"board_model": board_model, "revision": rev})

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Saving a recipe"))
    @transactional
    def save_recipe(self, recipe: Recipe, reason: str | None = None) -> int:
        """Store the next recipe revision and audit it with the revision before (a recipe decides verdicts); a minimum
        defect size under 4 px (AOI-RCP-007) is saved all the same, the notice added to the entry's reason. A revision
        that sets, changes or clears the override of the AI score threshold is also audited as `recipe.ai_threshold`
        of the board model (REQ-TRN-015): before and after, the revision, the override (None: none), the threshold
        that judges (the override, else the active AI model's calibrated value; None with neither), that AI model's
        version and its calibrated value (None while none is active or its calibration cannot be read). A size in mm
        the engine cannot apply is refused with AOI-RCP-011 (`Recipe.mm_refusal`), and any recipe while the board
        model's scale cannot be read with AOI-RCP-012, nothing stored (S29 review)."""
        if (refused := recipe.mm_refusal()) is not None:
            raise refused
        scale = self.db.scale(recipe.board_model)  # AOI-RCP-012 for one that cannot be read
        latest = self.db.latest_recipe(recipe.board_model)
        if (notice := recipe.size_notice(scale)) is not None:  # saved, and kept with it
            reason = f"{reason} {notice}" if reason else str(notice)  # in the audit entry (REQ-INSP-014)
        rev, uid = self.db.save_recipe(recipe.board_model, recipe.to_dict(), self.user)
        self.audit("recipe.save", "recipe", uid, latest[1] if latest else None, recipe.to_dict(), reason)
        old = (latest[1].get("anomaly_threshold") if latest else None) or None  # 0 judges as none: the engine's `or`
        if (new := recipe.anomaly_threshold or None) != old:
            model = self.db.active_model(recipe.board_model)
            cal = _calibration(model)
            named = {"ai_model": model["version"] if model else None, "calibrated": cal[0] if cal else None}
            before = {
                "revision": latest[0] if latest else None,
                "override": old,
                "threshold": old or named["calibrated"],
            }
            after = {"revision": rev, "override": new, "threshold": new or named["calibrated"]}
            self.audit("recipe.ai_threshold", "board_model", recipe.board_model, before | named, after | named, reason)
        return rev

    # --- audit trail (REQ-LOG-004) --------------------------------------------
    def audit(
        self,
        action: str,
        object_type: str,
        object_uuid: str | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reason: str | None = None,
    ) -> str:
        """Append an audit entry as the user acting (`actor`): who did `action` to which object, with the object before
        and after, and why. Returns the entry's UUID. Entries can never be changed or removed (migration 0003)."""
        actor = self.actor  # one read: the UUID and the role are one user's
        return self.db.add_audit(actor.uuid, actor.role, action, object_type, object_uuid, before, after, reason)

    def audit_entries(
        self,
        object_type: str | None = None,
        object_uuid: str | None = None,
        action: str | None = None,
        since: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Read audit entries, newest first, filtered by object type, object UUID, action and a UTC time floor. Every
        entry has the same fields: the audit columns, with `before` and `after` decoded from JSON (None when the entry
        has none) in place of the raw `before_json` and `after_json`."""
        return self.db.audit_entries(object_type, object_uuid, action, since, limit)

    # --- inspection ----------------------------------------------------------
    def load_image(self, path: str | Path) -> np.ndarray:
        """Read an image under the settings' size limits (REQ-INSP-001). Every image a screen or a service opens comes
        through here, so one pair of settings governs them all; `tests/test_layers.py` fails a page that reads one
        itself. A file of a customer's dataset store is decrypted in memory first (`_plain_bytes`, REQ-TRN-017)."""
        limits = (self.settings.max_image_megapixels, self.settings.max_image_megabytes)
        return load_image(path, *limits, read=self._plain_bytes)

    def _load_image_sha256(self, path: str | Path) -> tuple[np.ndarray, str]:
        limits = (self.settings.max_image_megapixels, self.settings.max_image_megabytes)
        return load_image_sha256(path, *limits, read=self._plain_bytes)

    def inspector(
        self, board_model: str, recipe: Recipe | None = None, side: str = "Top", reference: np.ndarray | None = None
    ) -> Inspector:
        """The engine for a board model: its latest recipe (or `recipe`), its active AI model and its reference image
        (or `reference`, such as another stored OK board on the Compare page). Screens never build an Inspector.
        The engine names the active AI model version and the recipe revision it applies, with their UUIDs, for the
        records it produces (REQ-INSP-012; the recipe says whether the AI check runs, #246); a `recipe` that differs
        from the stored revision names none. Likewise the golden board file it read, with the SHA-256 of its bytes
        (REQ-CMP-003); a `reference` passed in names none. AOI-INSP-009 when the database names a golden board whose
        file is gone or cannot be read: a board is never judged as if none were set (#169)."""
        latest = self.db.latest_recipe(board_model)
        rev: int | None
        rev, rcp, recipe_uuid = (latest[0], Recipe.from_dict(latest[1]), latest[2]) if latest else (0, None, None)
        rcp = rcp or Recipe(board_model=board_model)
        if recipe is not None and recipe.to_dict() != rcp.to_dict():
            rev, recipe_uuid = None, None  # an unsaved recipe (thresholds tried on Compare) has no revision
        mv = self.load_model(board_model)
        golden = self.db.reference(board_model) if reference is None else None
        sha: str | None = None
        if golden:
            try:
                reference, sha = self._load_image_sha256(golden)  # one read: the bytes hashed are the bytes judged
            except AoiError as e:  # the comparison and the alignment the AI model was trained on would silently go
                unreadable = QT_TRANSLATE_NOOP("Errors", "it cannot be read ({code} {title})").fill(
                    code=e.code, title=e.title
                )
                why = unreadable if Path(golden).exists() else QT_TRANSLATE_NOOP("Errors", "the file is gone")
                raise AoiError("AOI-INSP-009", detail=str(e), board=board_model, file=golden, reason=why) from e
        model, version, model_uuid = (mv[1], mv[0], mv[2]) if mv else (None, None, None)
        scale = self.db.scale(board_model)  # the recipe's sizes in mm are applied at it (REQ-RCP-006)
        args = (model, reference, side, version, rev, model_uuid, recipe_uuid, golden, sha, scale)
        return Inspector(recipe or rcp, *args)

    def engine_is_current(self, board_model: str, insp: Inspector | JudgedBy) -> bool:
        """Whether `insp` was built from what `inspector(board_model)` would use now: the active AI model, the latest
        recipe revision, the Golden board and the scale, by UUID, path and value (`Inspector.inputs`). It reads the
        database only, no image or weights, so the Inspection page asks before each board whether the engine it keeps
        is still the one to use: training, an activation, a saved recipe or a scale set makes it stale (#243, S29). AI
        Model Test asks it with the `JudgedBy` of a run before a row is previewed (#250), so both pages agree on when a
        result is current; that page then passes over the AI model for a run judged with the AI check off (#246), and
        the scale for a recipe that holds no size in mm (S29)."""
        active = self.db.active_model(board_model)
        latest = self.db.latest_recipe(board_model)
        model, recipe = str(active["uuid"]) if active else None, latest[2] if latest else None
        return insp.inputs == (model, recipe, self.db.reference(board_model), self.db.scale(board_model))

    def inspect(
        self,
        board_model: str,
        image: np.ndarray,
        recipe: Recipe | None = None,
        side: str = "Top",
        reference: np.ndarray | None = None,
    ) -> InspectionResult:
        """Inspect one image in memory without saving a record (the Compare page); `re_evaluate` judges a stored one
        again without the AI model."""
        return self.inspector(board_model, recipe, side, reference).inspect(image)

    def inspect_file(
        self, board_model: str, path: str, inspector: Inspector | None = None, save: bool = True, side: str = "Top"
    ) -> InspectionResult:
        """Inspect an image file and, by default, save the record (the headless path: tools, a future CLI or robot
        cycle). `side` is the view the record carries (REQ-INSP-010) when no `inspector` is given."""
        insp = inspector or self.inspector(board_model, side=side)
        res = insp.inspect(self.load_image(path))
        if save:
            self.log_result(board_model, path, res, insp)
        return res

    def log_result(self, board_model: str, path: str, res: InspectionResult, insp: Inspector) -> int:
        """Save a result with its evidence (REQ-INSP-008, spec 4.1): the overlay PNG and the two maps beside it, then
        one transaction with the row, the whole result as JSON, its checks, its defects and an NG board's alarm
        (REQ-INSP-006), naming the AI model version active when the board was judged and the recipe revision that judged
        it, which says whether the AI check ran, as the result's notes do (REQ-INSP-012, #246), and the golden board it
        was judged against (REQ-CMP-003). The overlay is `<stem>_<record UUID>_<verdict>.png`, the stem cut by
        `_stem`, and never replaces a file: a name already taken refuses the save with FileExistsError, and a path the
        system refuses as too long with AOI-INSP-014 (#245). A save that fails before its row commits removes the files
        it wrote, so none is left that no record names (#246). Called on the pool thread by the Inspection page."""
        day = local_date()  # the folder is named for the operator's shift date; the stored time is UTC
        uid = new_uuid()  # the record's, as the uuid column and the CSV export give it
        overlay = self.settings.results_dir / day / f"{_stem(path)}_{uid}_{res.verdict}.png"
        files = [overlay, *map_paths(overlay.with_suffix(""))]  # every file this save may write
        taken = [f for f in files if os.path.lexists(f)]
        if taken:  # only a defect gets here; the workspace lock keeps out a second copy of the app (#204)
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(taken[0]))
        pixel_threshold = insp.model.pixel_threshold if insp.model is not None else None  # the AI map's, kept (S28a)
        try:  # until the row commits, a failure takes back what this save wrote (#246)
            try:
                save_image(overlay, draw_overlay(res))
                diff_map_path, ai_map_path = save_maps(res, overlay.with_suffix(""), pixel_threshold=pixel_threshold)
            except OSError as e:
                if not _too_long(e):
                    raise
                raise AoiError("AOI-INSP-014", str(e), file=Path(path).name, workspace=str(self.settings.root)) from e
            doc = res.to_dict()
            alarm = None
            if res.verdict == NG:  # a phrase: the alarm list shows it in the UI language, its message stays English
                text = QT_TRANSLATE_NOOP("Errors", "{file}: {defects} defect(s)").fill(
                    file=Path(path).name, defects=len(res.defects)
                )
                alarm = ("NG", text, "AOI-INSP-003")
            iid = self.db.add_inspection(
                {
                    "board_model": board_model,
                    "model_version": insp.model_version,
                    "model_uuid": insp.model_uuid,
                    "recipe_rev": insp.recipe_rev,
                    "recipe_uuid": insp.recipe_uuid,
                    "image_path": path,
                    "overlay_path": str(overlay),
                    "diff_map_path": diff_map_path,
                    "ai_map_path": ai_map_path,
                    "reference_path": insp.reference_path,
                    "reference_sha256": insp.reference_sha256,
                    "view": res.view,
                    "result": res.verdict,
                    "score": res.score,
                    "metrics": res.metrics_dict(),
                    "result_json": doc,
                    "operator": self.user,
                },
                [d.as_row() for d in res.defects],
                doc["checks"],
                alarm,  # in the record's transaction: a saved NG board always has its alarm (REQ-INSP-006, #179)
                uid=uid,
            )
        except BaseException:
            _remove(files)
            raise
        # The row has committed: its files are named now and stay, whatever the log lines below meet.
        if alarm is not None:
            self.log.info("alarm", extra={"alarm_level": alarm[0], "code": alarm[2], "text": alarm[1]})
        self.log.info(
            "inspection.saved",
            extra={
                "inspection_id": iid,
                "board_model": board_model,
                "verdict": res.verdict,
                "view": res.view,
                "defects": len(res.defects),
                "model_version": insp.model_version,
                "recipe_rev": insp.recipe_rev,
                "elapsed_ms": round(res.elapsed_ms, 1),
            },
        )
        return iid

    # --- alarms and errors (REQ-INSP-006, REQ-LOG-005, REQ-SET-019) -----------
    def alarm(
        self, level: str, message: str, code: str | None = None, wait_ms: int | None = None, log_text: str | None = None
    ) -> None:
        """Store an alarm (NG, WARN or ERROR) with its code; it survives a restart and reaches the log. A `message`
        that is a phrase is stored with it, so the alarm list shows it in the UI language (#198). `wait_ms` bounds the
        wait for another program's lock on the database; `log_text` is what the log holds of a `message` that names a
        person (#195)."""
        self.db.alarm(level, message, code, wait_ms)
        self.log.info("alarm", extra={"alarm_level": level, "code": code, "text": log_text or message})

    def alarms(self, limit: int = ALARM_LIMIT) -> list[dict[str, Any]]:
        """The newest alarms first: time (UTC), level, code and message."""
        return self.db.alarms(limit)

    def report_error(self, exc: BaseException, context: str = "") -> ErrorReport:
        """The one handler for an error a user will see: log it with the build version and the stack trace,
        store an alarm with its code, and return the plain report the dialog shows. A plain exception becomes
        AOI-SET-007 (unexpected error); its text stays in the log, but a database another program holds while the app
        works is AOI-SET-013, and its alarm waits only BUSY_ALARM_WAIT_MS for the lock (#195). It never raises (an alarm
        refused is logged)."""
        busy = is_busy(exc) or is_busy(exc.__cause__)
        if is_busy(exc):  # not unexpected: the user can close the other program and try again
            held = AoiError("AOI-SET-013", detail=str(exc), path=str(self.db.path), error=str(exc))
            held.__cause__ = exc  # the log keeps SQLite's error and its trace
            exc = held.with_traceback(exc.__traceback__)
        report = ErrorReport.of(exc, context)  # the dialog and the alarm name a user; the log only by UUID (#195)
        safe = exc.log_safe(self._pseudonym) if isinstance(exc, AoiError) else exc
        self.log.error(
            "error.shown",
            exc_info=(type(safe), safe, exc.__traceback__),
            extra={"code": report.code, "context": context, "detail": getattr(safe, "detail", None) or str(safe)},
        )
        try:
            log_text = safe.what if isinstance(safe, AoiError) else None
            self.alarm("ERROR", report.what, report.code, BUSY_ALARM_WAIT_MS if busy else None, log_text)
        except Exception:  # #171: the report, and so the coded dialog, must not depend on the database
            self.log.warning("alarm.not_stored", exc_info=True, extra={"code": report.code})
        return report

    def _pseudonym(self, name: object) -> str:
        """A user named by UUID for the log, which holds no personal data beyond it (REQ-LOG-004, #195)."""
        try:
            uid = self.db.user_uuid(str(name))
        except DbError:
            uid = None
        return f"user {uid or '<unknown>'}"

    def golden_board_unreadable(self, board_model: str, error: AoiError) -> None:
        """Record the error a Golden board pane shows for a file it cannot read (#176): a log warning each time, and an
        ERROR alarm with the code shown once per board model, file and code, so a page shown again, both panes showing
        it, or the file going back to a state already alarmed, add no other (#195). It never raises: the page must open
        either way."""
        self.log.warning("golden_board.unreadable", extra={"board_model": board_model, "code": error.code})
        key: tuple[str, str | None, str] | None = None
        try:
            key = (board_model, self.db.reference(board_model), error.code)
            with self._golden_lock:
                if key in self._golden_alarmed:
                    return
                self._golden_alarmed.add(key)
            self.alarm("ERROR", error.what, error.code, BUSY_ALARM_WAIT_MS)  # a pane reads it on the UI thread
        except Exception:  # the database refuses the alarm (#171): the next read tries again
            if key is not None:
                self._golden_alarmed.discard(key)
            self.log.warning("alarm.not_stored", exc_info=True, extra={"code": error.code})

    # --- batch test (AI Model Test screen) -----------------------------------
    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Running an AI model test"))
    def batch_test(
        self, board_model: str, folder: str, progress: Callable[[int, int], None] | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]], JudgedBy]:
        """Validate the active AI model on a folder and store the run: (metrics, rows, judged_by), one row per image,
        and the recipe revision and Golden board that judged them all, the AI model version active then and whether the
        recipe ran the AI check (#250, #246; beside the rows, not in them, since the CSV export writes every key of a
        row). Ground truth comes from sub-folder names: under `ng`/`defect` NG, under `ok`/`good` OK, elsewhere no
        label ("?"); `pass_fail` is PASS when the verdict (WARN as NG) matches
        the label, FAIL when not and NO_LABEL without one; `ai_check` says whether the AI check judged it, RAN, OFF or
        NO_AI_MODEL, as for an inspection record (#246). Each row ends with the run's UUID, the AI model version active
        then and its UUID (run_uuid, model_version, model_uuid; None without an AI model), as the CSV export writes them
        (REQ-SET-017)."""
        insp = self.inspector(board_model)
        files = list_images(folder)
        rows = []
        for i, f in enumerate(files, 1):
            parts = {p.lower() for p in f.relative_to(folder).parts[:-1]}
            gt = NG if parts & {"ng", "defect", "defects", "bad"} else OK if parts & {"ok", "good"} else None
            res = insp.inspect(self.load_image(f))
            pred = NG if res.verdict in (NG, WARN) else OK
            rows.append(
                {
                    "image": str(f),
                    "gt": gt or "?",
                    "ai_result": res.verdict,
                    "score": round(res.score, 3),
                    "defects": len(res.defects),
                    "pass_fail": "NO_LABEL" if gt is None else "PASS" if gt == pred else "FAIL",  # vs the label (#207)
                    "ai_check": ai_check(res),  # stored with the run: its AI model may not have judged it (#246)
                }
            )
            if progress:
                progress(i, len(files))
        metrics = classification_metrics(rows)
        model_version = insp.model_version or "-"
        with self.db.transaction():  # the run and its entry, or neither (#178)
            run_uuid = self.db.add_test_run(board_model, model_version, folder, metrics, rows, insp.model_uuid)
            ids = {"run_uuid": run_uuid, "model_version": insp.model_version, "model_uuid": insp.model_uuid}
            after = {"folder": to_stored(Path(folder).absolute(), self.settings.root), **ids, **metrics}
            self.audit("test.run", "board_model", board_model, None, after)
        return metrics, [{**r, **ids} for r in rows], insp.judged_by

    # --- what the screens read (REQ-USR-001: pages call only AppContext, never the database) ---
    def board_models(self) -> list[str]:
        """Board model names, sorted."""
        return self.db.board_models()

    def reference_image(self, board_model: str) -> str | None:
        """Absolute path of the board model's reference (golden) image, or None when none is set."""
        return self.db.reference(board_model)

    def samples(self, board_model: str, label: str | None = None) -> list[dict[str, Any]]:
        """Training samples (id, uuid, side, path, added_at) with their current label (label, defect_type, label_uuid,
        labelled_by: a user's UUID or None, labelled_by_name, labelled_at), oldest first; `label` filters OK, NG or
        UNSURE. Training and the counts read OK and NG only, so an UNSURE image is in neither (REQ-TRN-002)."""
        return self.db.samples(board_model, label)

    def sample_path(self, sample_id: int) -> str:
        """Absolute path of one sample image."""
        return str(self.db.sample(sample_id)["path"])

    def models(self, board_model: str) -> list[dict[str, Any]]:
        """Trained model versions (id, version, path, metrics JSON, active, created_at), newest first."""
        return self.db.models(board_model)

    def model(self, model_id: int) -> dict[str, Any]:
        """One model version by id, with its absolute path."""
        return self.db.model(model_id)

    def active_model(self, board_model: str) -> dict[str, Any] | None:
        """The model version inspections use, or None when none is trained."""
        return self.db.active_model(board_model)

    def calibrated_threshold(
        self, board_model: str, model_uuid: str | None = None, version: str | None = None
    ) -> float | None:
        """The AI score threshold an AI model of `board_model` was calibrated to (REQ-TRN-015), from its registry row:
        the active one's, which judges the next board whose recipe holds no override, or, with `model_uuid`, that of
        the AI model a stored result names, which Re-evaluate applies (ADR 0006 decision 2). None while no AI model is
        active. AOI-TRN-012 when the row holds no usable calibration, or the registry holds no AI model `model_uuid`,
        named then by the `version` the stored result gives (else by its UUID)."""
        if model_uuid is None:
            model = self.db.active_model(board_model)
            if model is None:
                return None
        elif (model := next((m for m in self.db.models(board_model) if m["uuid"] == model_uuid), None)) is None:
            raise AoiError("AOI-TRN-012", version=version or model_uuid, board=board_model)
        return self.calibration_of(model)

    def calibration_of(self, model: dict[str, Any]) -> float:
        """The calibrated AI score threshold an AI model registry row (one of `models()`) holds, read as
        `calibrated_threshold` reads it, for a page that lists the rows (Training: one registry read for all).
        AOI-TRN-012 when the row holds no usable calibration (only a row changed by hand)."""
        if (cal := _calibration(model)) is None:
            raise AoiError("AOI-TRN-012", version=model["version"], board=model["board_model"])
        return cal[0]

    def recipe_history(self, board_model: str) -> list[dict[str, Any]]:
        """Recipe revisions (revision, uuid, user, created_at), newest first; revision 1 by "system" is the default."""
        return self.db.recipe_history(board_model)

    def inspections(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        board_model: str | None = None,
        operator: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """Inspection records, newest first, filtered by local calendar dates (YYYY-MM-DD), board model and operator,
        each with its defect_count and absolute image and overlay paths."""
        return self.db.inspections(date_from, date_to, board_model, operator, include_archived)

    def defects_for(self, inspection_id: int) -> list[dict[str, Any]]:
        """The defects of one inspection (no, type, score, side, x, y, w, h), in order."""
        return self.db.defects_for(inspection_id)

    def checks_for(self, inspection_id: int) -> list[dict[str, Any]]:
        """The checks that decided one inspection (no, region, metric, source, value, threshold, rule, result,
        explain), in order; [] for a record from before migration 0006 (REQ-INSP-012)."""
        return self.db.checks_for(inspection_id)

    def checks_for_many(self, inspection_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        """The checks of many inspections in one pass, {inspection_id: [checks in order]}, as the CSV export needs
        them; an id without checks maps to []."""
        return self.db.checks_for_many(inspection_ids)

    def inspection(self, inspection_id: int) -> dict[str, Any] | None:
        """One inspection record by id (its UUID, time, board model, the model version and recipe revision with their
        UUIDs, the paths, the golden board's SHA-256, verdict and score), or None for an unknown id; Compare opens a
        stored result from it (REQ-INSP-009)."""
        return self.db.inspection(inspection_id)

    def inspection_result(self, inspection_id: int, with_maps: bool = False) -> InspectionResult | None:
        """One stored result read back without its images (verdict, checks, defects, compare metrics and regions, as
        decided) for Compare (REQ-INSP-008); with `with_maps`, the stored maps too, where their files exist
        (REQ-INSP-012), and AOI-CMP-003 for one there that cannot be read or is not the map stored (in colour, or not
        the size of its board picture, #249). None for a record from before migration 0006; AOI-CMP-002 for a stored
        result that cannot be read (damaged: not JSON, or a scale or time that is no number, S29 review)."""
        try:
            doc = self.db.inspection_result(inspection_id)
            res = InspectionResult.from_dict(doc) if doc is not None else None
        except (ValueError, KeyError, TypeError, AttributeError) as e:  # as Logs & Export's CSV skips one (#246)
            rec = self.db.inspection(inspection_id)
            file = Path(rec["image_path"]).name if rec else "?"
            raise AoiError("AOI-CMP-002", detail=str(e), id=inspection_id, file=file) from e
        if res is None or not with_maps:
            return res
        rec = self.db.inspection(inspection_id)
        return load_maps(res, *self.db.map_paths(inspection_id), picture_shape(rec["overlay_path"] if rec else None))

    def judged_reference(self, inspection_id: int) -> tuple[np.ndarray | None, Judged]:
        """The golden board a stored result was judged against (REQ-CMP-003): its image and "same" while its file holds
        the bytes it had then; else None and why not: "none" (judged without one: no Compare check is stored),
        "unrecorded" (saved before migration 0008), "missing" (no file at that path), "unreadable" (AOI-INSP-001 to
        -007 now) or "changed" (other bytes there); the last three are logged. Compare calls it on the pool thread."""
        rec = self.db.inspection(inspection_id)
        path, sha = (rec["reference_path"], rec["reference_sha256"]) if rec else (None, None)
        if not (path and sha):
            compared = any(c["source"] == "Compare" for c in self.db.checks_for(inspection_id))
            return None, "unrecorded" if compared else "none"
        why: Judged = "missing"
        if Path(path).is_file():
            try:
                img, now = self._load_image_sha256(path)
            except AoiError:  # locked, refused or damaged: the stored picture and maps still show
                why = "unreadable"
            else:
                if now == sha:
                    return img, "same"
                why = "changed"
        extra = {"inspection_id": inspection_id, "reason": why, "file": Path(path).name}
        self.log.warning("compare.golden_board_not_as_judged", extra=extra)
        return None, why

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Re-evaluating a result"))
    def re_evaluate(self, result_uuid: str, thresholds: Recipe) -> InspectionResult:
        """A stored result judged again by `thresholds` (its board model's recipe with the thresholds an Engineer is
        trying) from the maps stored with it, without aligning, comparing or running the AI model (REQ-CMP-005,
        docs/adr/0006-judging-a-stored-result-again.md): the checks, defects and verdict that recipe gives the board,
        within 300 ms at 5 MP. Only the maps the thresholds use are read. Nothing is stored: Save to Recipe stores the
        thresholds. The AI score is the stored check's and the AI model's calibration the registry's, for the AI model
        the record names by UUID (REQ-INSP-012).

        Raises AOI-USR-001 below the Engineer role; AOI-CMP-002 for an unknown UUID or a result stored without its
        decision table; AOI-CMP-005 when `thresholds` are another board model's; AOI-CMP-003 when a map it reads is
        there but cannot be read; AOI-CMP-004 when a map, or the AI model's calibration, that a check `thresholds`
        uses was judged on is gone; and AOI-INSP-010 when `thresholds` leave no check that ran on the board. A map that
        is not the map stored (in colour, or not the size of the result's board picture) cannot be read (#249). Sizes in
        mm are applied at the scale the result was judged at, or, for one judged without a scale, at the board model's
        now, which the result it returns keeps (REQ-RCP-006). A stored result that cannot be read is AOI-CMP-002 too
        (S29 review)."""
        iid = self.db.inspection_id(result_uuid)
        rec = self.db.inspection(iid) if iid is not None else None
        res = self.inspection_result(iid) if iid is not None else None
        file = (
            Path(rec["image_path"]).name if rec and rec["image_path"] else QT_TRANSLATE_NOOP("Errors", "file unknown")
        )
        if rec is None or res is None or iid is None:
            raise AoiError("AOI-CMP-002", id=result_uuid, file=file)
        if thresholds.board_model != rec["board_model"]:
            raise AoiError("AOI-CMP-005", tried=thresholds.board_model, file=file, judged=rec["board_model"])
        diff_path, ai_path = self.db.map_paths(iid)
        shape = picture_shape(rec["overlay_path"])  # the size the board was judged at: its maps' (#249)
        if res.px_per_mm is None:  # judged without a scale: judged again at the board model's now, kept with it (S29)
            res.px_per_mm = self.db.scale(rec["board_model"])
        thresholds = thresholds.in_px(res.px_per_mm)  # in px before the regions are found while the AI map decodes
        changed: list[tuple[np.ndarray, list[Region], dict[str, Any]]] = []  # found while the AI map decodes (#249)
        load_maps(
            res,
            diff_path if thresholds.use_compare else None,
            ai_path if thresholds.use_ai else None,
            shape,
            on_diff=lambda d: changed.append(changed_regions(d, thresholds.diff_threshold, thresholds.min_defect_area)),
        )
        missing: list[str] = []  # only what the thresholds use, as re_grade asks for it
        if thresholds.use_compare and res.compare is not None and res.compare.diff_map is None:
            missing.append(QT_TRANSLATE_NOOP("Errors", "difference map"))
        ai, check = None, next((c for c in res.checks if c.source == "AI"), None)
        if thresholds.use_ai and check is not None:
            model = next((m for m in self.db.models(rec["board_model"]) if m["uuid"] == rec["model_uuid"]), None)
            if (cal := _calibration(model)) is not None:
                ai = AiEvidence(check.value, *cal, check.explain)
            else:
                version = rec["model_version"] or rec["model_uuid"]
                calibration = QT_TRANSLATE_NOOP("Errors", "the calibration of AI model {version}").fill(version=version)
                missing.append(calibration if version else QT_TRANSLATE_NOOP("Errors", "the AI model's calibration"))
            if res.anomaly_map is None:
                missing.append(QT_TRANSLATE_NOOP("Errors", "AI score map"))
        if missing:
            days = self.settings.map_retention_days_ok
            raise AoiError(
                "AOI-CMP-004",
                file=file,
                missing=joined(QT_TRANSLATE_NOOP("Errors", "{first}, {rest}"), missing),
                days=days,
            )
        return re_grade(res, thresholds, ai, changed=changed[0] if changed else None)

    def users(self) -> list[dict[str, Any]]:
        """Users (uuid, name, role), oldest first."""
        return self.db.users()

    def board_status(self, board_model: str) -> BoardStatus:
        """Sample counts, active model, recipe revision, last test metrics and inspection counts of a board model."""
        model = self.db.active_model(board_model)
        history = self.db.recipe_history(board_model)  # newest first
        run = self.db.latest_test_run(board_model)
        inspected, ng = self.db.inspection_counts(board_model)
        return BoardStatus(
            ok_samples=len(self.db.samples(board_model, "OK")),
            ng_samples=len(self.db.samples(board_model, "NG")),
            model_version=model["version"] if model else None,
            recipe_revision=history[0]["revision"] if history else 0,
            recipe_is_default=not history or history[0]["user"] == "system",
            last_test=run["metrics"] if run else None,
            inspected=inspected,
            ng=ng,
        )

    # --- what the screens change: each checks the role and appends an audit entry (REQ-USR-001, REQ-LOG-004) ---
    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Creating a board model"))
    @transactional
    def ensure_board_model(self, name: str) -> None:
        """Create a board model unless it exists."""
        if name in self.db.board_models():
            return
        self._refuse_unsafe_name(name)
        self._refuse_case_variant(name)
        self.db.ensure_board_model(name)
        self.audit("board_model.create", "board_model", name, None, {"name": name})
        self._ensure_recipe(name)

    def _refuse_unsafe_name(self, name: str) -> None:
        """Refuse a new board model whose name cannot name its folders under images/ and models/ on Windows as on Linux
        (AOI-TRN-019, `one_folder_name`): a name with / or .., a device name such as CON, one ending with a dot."""
        if not one_folder_name(name) and name not in self.db.board_models():
            raise AoiError("AOI-TRN-019", name=name)

    def _refuse_case_variant(self, name: str) -> None:
        """Refuse a new board model whose name differs from an existing one's only in case (AOI-TRN-005): on Windows,
        where file names ignore case, both would write the same AI model and golden board files."""
        names = self.db.board_models()
        same = next((n for n in names if n.casefold() == name.casefold()), None) if name not in names else None
        if same is not None:
            raise AoiError("AOI-TRN-005", name=name, existing=same)

    def scale(self, board_model: str) -> float | None:
        """The board model's scale in px per mm (REQ-RCP-006), or None until one is set: its recipe's sizes in px;
        AOI-RCP-012 for one stored that cannot be read, as for every reader of it (`Database.scale`)."""
        return self.db.scale(board_model)

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Setting a board model's scale"))
    @transactional
    def set_scale(self, board_model: str, length_px: float, distance_mm: float) -> float:
        """Set the board model's scale from a known length on its calibration image, the Golden board (REQ-RCP-006;
        Calibrate Scale… on the Recipe Editor): `length_px` px on the image are `distance_mm` mm on the board. Returns
        the scale in px per mm, at which its recipe's sizes in mm judge every board from then on, so it can change
        verdicts: audited as board_model.scale with the scale before and after, the length, the distance and the Golden
        board file. Refused with AOI-RCP-008, before anything is written, unless both are numbers above 0, not true or
        false, whose ratio is from MIN_SCALE to MAX_SCALE, or for a board model that does not exist. It replaces a
        stored scale that cannot be read (AOI-RCP-012), which its entry keeps as it was stored (S29 review)."""
        numbers = all(isinstance(v, int | float) and not isinstance(v, bool) for v in (length_px, distance_mm))
        scale = length_px / distance_mm if numbers and distance_mm > 0 else math.nan  # a bool is none (S29 review)
        if board_model not in self.db.board_models():
            raise AoiError("AOI-RCP-008", board_model=board_model, reason=NO_BOARD_MODEL)
        if not (numbers and 0 < length_px < math.inf and MIN_SCALE <= scale <= MAX_SCALE):
            reason = SCALE_NUMBERS.fill(length=length_px, distance=distance_mm, least=MIN_SCALE, most=MAX_SCALE)
            raise AoiError("AOI-RCP-008", board_model=board_model, reason=reason)
        try:
            before: object = self.db.scale(board_model)
        except AoiError as e:  # AOI-RCP-012: replaced
            before = e.params["value"]
        golden = self.db.reference(board_model)
        self.db.set_scale(board_model, scale)
        image = to_stored(Path(golden), self.settings.root) if golden else None
        after = {"px_per_mm": scale, "length_px": length_px, "distance_mm": distance_mm, "image": image}
        self.audit("board_model.scale", "board_model", board_model, {"px_per_mm": before}, after)
        return scale

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Changing the reference image"))
    @transactional
    def set_reference(self, board_model: str, sample_id: int) -> None:
        """Make a stored OK sample the reference image: inspections compare against it from now on, and the next
        training run aligns its boards to it before it learns the golden template. An NG sample is refused
        (AOI-TRN-006), and a board model it would create meets the rule a first import's does (AOI-TRN-019,
        AOI-TRN-005)."""
        self._refuse_unsafe_name(board_model)
        self._refuse_case_variant(board_model)
        sample = self.db.sample(sample_id)
        if sample["label"] != "OK":
            raise AoiError("AOI-TRN-006", sample=Path(sample["path"]).name, label=sample["label"])
        before, path = self.db.reference(board_model), sample["path"]
        self.db.set_reference(board_model, path)
        root = self.settings.root
        old = {"reference": to_stored(Path(before), root) if before else None}
        self.audit("board_model.reference", "board_model", board_model, old, {"reference": to_stored(Path(path), root)})

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Relabelling a sample"))
    @transactional
    def update_sample(self, sample_id: int, label: str, defect_type: str | None) -> None:
        """Relabel a sample OK or NG (else AOI-TRN-018) and set its defect type as an import does (REQ-TRN-001): one of
        the 33 DCT types for NG (else AOI-TRN-013), none for OK, whatever is given, with a new label row; the one before
        stays in history (REQ-TRN-002). A sample a labeller gave that label and type already is left as it is; one
        carried over with no labeller is labelled again, by the user acting, so it can be checked. The reference sample
        cannot be relabelled NG (AOI-TRN-007): inspections would compare against a defective board. The new label row
        is checked as `set_label` checks one."""
        before = self.db.sample(sample_id)
        name = Path(before["path"]).name
        if label not in LABELS:
            raise AoiError("AOI-TRN-018", path=name, label=label, labels=", ".join(LABELS))
        self._refuse_untyped(name, label, defect_type)
        defect_type = defect_type if label == "NG" else None
        if (before["label"], before["defect_type"]) == (label, defect_type) and before["labelled_by"] is not None:
            return  # labelled so already: no new row, so its labeller and any check of it stay
        self._write_label(before, label, defect_type, None, None)  # an image that stays NG keeps its boxes
        old = {"label": before["label"], "defect_type": before["defect_type"]}
        self.audit("sample.update", "sample", before["uuid"], old, {"label": label, "defect_type": defect_type})

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Removing a sample"))
    @transactional
    def delete_sample(self, sample_id: int) -> None:
        """Remove a sample's record; its image file stays in the workspace. The reference sample cannot be removed
        (AOI-TRN-007)."""
        before = self.db.sample(sample_id)
        self._refuse_reference_change(before, QT_TRANSLATE_NOOP("Errors", "removed"))
        self.db.delete_sample(sample_id)
        old = {"label": before["label"], "path": to_stored(Path(before["path"]), self.settings.root)}
        self.audit("sample.delete", "sample", before["uuid"], old, None)

    def _refuse_reference_change(self, sample: dict[str, Any], change: str) -> None:
        """Refuse a change that would leave inspections comparing against a board that is not a good sample (#168):
        the reference an import picked, or one an Engineer set, stays an OK sample until another is set."""
        reference = self.db.reference(sample["board_model"])
        if reference is not None and Path(reference) == Path(sample["path"]):
            raise AoiError("AOI-TRN-007", sample=Path(sample["path"]).name, change=change)

    # --- labels and defect boxes (REQ-TRN-002, REQ-TRN-003; S32): a relabel adds rows, the old ones stay in history ---
    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Labelling an image"))
    def set_label(
        self, sample_uuid: str, label: str, defect_type: str | None = None, boxes: list[DefectBox] | None = None
    ) -> str:
        """Give a sample a new current label, OK, NG or UNSURE, with an NG image's defect type and boxes (None keeps the
        boxes of an image that stays NG), each box with its type's severity; audited as `label.set` with the label
        before and after. The rows replaced stay, superseded by the new label row, whose UUID is returned. Refused with
        AOI-TRN-030 or AOI-TRN-031 for a label or box the image cannot take, AOI-TRN-032 for a sample the workspace
        does not hold and AOI-TRN-007 for the reference sample labelled other than OK."""
        return self._set_label(sample_uuid, (label, defect_type), boxes)

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Drawing defect boxes"))
    def set_boxes(self, sample_uuid: str, boxes: list[DefectBox]) -> str:
        """Replace the defect boxes of an NG image: `set_label` with its label and defect type as they are."""
        return self._set_label(sample_uuid, None, boxes)

    def _set_label(self, sample_uuid: str, given: tuple[str, str | None] | None, boxes: list[DefectBox] | None) -> str:
        """`set_label`, with `given` None for the label and type the sample has. The image's size, which the box checks
        need, is read before the write transaction opens, so no file is read while the database is locked."""
        size = self._image_size(self._sample(sample_uuid)["path"]) if boxes else None
        with self.db.transaction():
            sample = self._sample(sample_uuid)
            label, defect_type = given or (sample["label"], sample["defect_type"])
            before = self._label_state(sample)
            uid, rows = self._write_label(sample, label, defect_type, boxes, size)
            after = {"label_uuid": uid, "label": label, "defect_type": defect_type, "boxes": rows}
            self.audit("label.set", "sample", sample_uuid, before, after)
        return uid

    def label_history(self, sample_uuid: str) -> list[dict[str, Any]]:
        """Every label a sample has had, newest first (uuid, label, defect_type, labelled_by: a user's UUID, None for a
        label carried over from before history was kept, labelled_by_name, at_utc, superseded_by: the label row that
        replaced it, None for the current one), each with `boxes`, the defect boxes drawn with it."""
        return self.db.label_history(sample_uuid)

    def boxes(self, sample_uuid: str) -> list[dict[str, Any]]:
        """A sample's current defect boxes (uuid, label_uuid, x, y, w, h, dct_type, severity, labelled_by, at_utc), in
        the order drawn; none for an image that is not NG."""
        return self.db.boxes(sample_uuid)

    def box_history(self, sample_uuid: str) -> list[dict[str, Any]]:
        """Every defect box a sample has had, newest first; a replaced one names the label row that replaced it."""
        return self.db.boxes(sample_uuid, every=True)[::-1]

    def unsure_samples(self, board_model: str) -> list[dict[str, Any]]:
        """The images labelled UNSURE, as `samples` gives them, for the customer's quality engineer (REQ-TRN-002)."""
        return self.db.samples(board_model, "UNSURE")

    def _sample(self, sample_uuid: str) -> dict[str, Any]:
        if (sample := self.db.sample_by_uuid(sample_uuid)) is None:
            raise AoiError("AOI-TRN-032", sample=sample_uuid)
        return sample

    def _label_state(self, sample: dict[str, Any]) -> dict[str, Any]:
        """A sample's current label as its audit entries hold it."""
        boxes = [{k: b[k] for k in ("x", "y", "w", "h", "dct_type", "severity")} for b in self.db.boxes(sample["uuid"])]
        return {k: sample[k] for k in ("label_uuid", "label", "defect_type")} | {"boxes": boxes}

    def _write_label(
        self, sample: dict[str, Any], label: str, dtype: str | None, boxes: list[DefectBox] | None, size: labels.Size
    ) -> tuple[str, list[dict[str, Any]]]:
        """Check and store a new label as the user acting, in the caller's transaction, with the image's `size` for the
        boxes given: (its UUID, the box rows)."""
        if boxes is None:  # the boxes stay with an image that stays NG; any other label has none
            keep = self.db.boxes(sample["uuid"]) if label == "NG" else []
            boxes = [DefectBox(b["x"], b["y"], b["w"], b["h"], b["dct_type"]) for b in keep]
        labels.check(Path(sample["path"]).name, size, label, dtype, boxes)
        if label != "OK":
            change = QT_TRANSLATE_NOOP("Errors", "relabelled {label}").fill(label=label)
            self._refuse_reference_change(sample, change)
        rows = [b.row() for b in boxes]
        return self.db.add_label(sample["uuid"], label, dtype, rows, self.user_uuid), rows

    # --- second-user label checks (REQ-TRN-004; S34): every NG label and a seeded random 10 % of the OK labels ---
    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Checking a label"))
    @transactional
    def check_label(self, sample_uuid: str) -> str:
        """Record that the user acting checked a sample's current label row; returns the check's UUID, audited as
        `label.check`. The labeller cannot check it (AOI-TRN-033): a second user does, by name under ADR 0002 until
        sign-in ships. AOI-TRN-034 refuses a label checked already, an UNSURE label, an NG image with no defect box and
        a label with no labeller recorded (carried over by migration 0014)."""
        sample = self._sample(sample_uuid)
        why = None
        if sample["checked_by"] is not None:
            why = QT_TRANSLATE_NOOP("Errors", "it is checked already")
        elif sample["label"] == "UNSURE":
            why = QT_TRANSLATE_NOOP("Errors", "an UNSURE image is left out of training, so its label is not checked")
        elif sample["label"] == "NG" and not self.db.boxes(sample_uuid):
            why = QT_TRANSLATE_NOOP("Errors", "an NG image needs at least one defect box: draw its boxes first")
        elif sample["labelled_by"] is None:
            why = QT_TRANSLATE_NOOP("Errors", "no labeller is recorded for it: label it again first")
        if why is not None:
            raise AoiError("AOI-TRN-034", sample=Path(sample["path"]).name, reason=why)
        if sample["labelled_by"] == self.user_uuid:
            raise AoiError("AOI-TRN-033", sample=Path(sample["path"]).name)
        uid = self.db.add_check(sample["label_uuid"], sample_uuid, self.user_uuid)
        after = {"check_uuid": uid, "label_uuid": sample["label_uuid"], "label": sample["label"]}
        self.audit("label.check", "sample", sample_uuid, None, after)
        return uid

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Drawing OK labels for a check"))
    @transactional
    def draw_ok_checks(self, board_model: str, view: str, seed: int | None = None) -> dict[str, Any] | None:
        """Draw at random, with a recorded seed (a new one when None), OK labels of a board model and view for a second
        user to check, so that the drawn ones still OK number 10 % of its OK labels, rounded up; a draw adds to the
        earlier ones and never replaces one. Returns the draw (uuid, side, seed, ok_labels, sample_uuids), audited as
        `label.draw`, or None, writing nothing, when the earlier draws are enough."""
        status = self.label_check_status(board_model, view)
        need = status["ok_needed"] - len(status["ok_drawn"])
        if need <= 0:
            return None
        drawn = {u for d in self.db.ok_check_draws(board_model, view) for u in d["sample_uuids"]}
        pool = [s["uuid"] for s in self._in_view(board_model, view, "OK") if s["uuid"] not in drawn]
        seed = secrets.randbelow(2**31) if seed is None else seed
        picked = random.Random(seed).sample(pool, need)  # noqa: S311 - no secret: seed and draw are audited
        draw = self.db.add_ok_check_draw(board_model, view, seed, status["ok"], picked, self.user_uuid)
        self.audit("label.draw", "board_model", board_model, None, draw)
        return draw

    def label_check_status(self, board_model: str, view: str) -> dict[str, Any]:
        """The second-user checks of a board model and view (REQ-TRN-004): `ok` and `ng`, its OK and NG labels;
        `ng_unchecked`, the NG samples whose label is not checked; `ok_needed`, 10 % of the OK labels rounded up;
        `ok_drawn` and `ok_checked`, the drawn samples still OK and those of them checked; and `ready`, never with no OK
        or NG label. A view other than Top, Side or Bottom is refused with AOI-TRN-038, here and in each call below."""
        ok, ng = self._in_view(board_model, view, "OK"), self._in_view(board_model, view, "NG")
        drawn = {u for d in self.db.ok_check_draws(board_model, view) for u in d["sample_uuids"]}
        ok_drawn = [s for s in ok if s["uuid"] in drawn]
        status: dict[str, Any] = {"ok": len(ok), "ng": len(ng), "ok_needed": -(-len(ok) // 10)}
        status["ng_unchecked"] = [s["uuid"] for s in ng if s["checked_by"] is None]
        status["ok_drawn"] = [s["uuid"] for s in ok_drawn]
        status["ok_checked"] = [s["uuid"] for s in ok_drawn if s["checked_by"] is not None]
        enough = len(status["ok_checked"]) >= status["ok_needed"]
        status["ready"] = bool(ok or ng) and not status["ng_unchecked"] and enough  # no label: nothing to freeze
        return status

    def labels_ready_to_freeze(self, board_model: str, view: str) -> bool:
        """True once every NG label of the board model and view, and drawn OK labels numbering at least 10 % of its OK
        labels, are checked by a second user (REQ-TRN-004); a dataset of that view is frozen only then (S35)."""
        return bool(self.label_check_status(board_model, view)["ready"])

    def _in_view(self, board_model: str, view: str, label: str) -> list[dict[str, Any]]:
        if view not in VIEWS:  # a view names a dataset version and its folder, so no other text may reach a path
            raise AoiError("AOI-TRN-038", view=view)
        return [s for s in self.db.samples(board_model, label) if s["side"] == view]

    # --- labeller agreement (REQ-TRN-016; S34): two users label a calibration set blind; each check is stored ---
    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Making a calibration set"))
    @transactional
    def make_calibration_set(self, board_model: str, sample_uuids: list[str]) -> str:
        """Fix a calibration set of a board model: 100 different images (proposed), each labelled OK or NG now; returns
        its UUID, audited as `calibration.make`. AOI-TRN-035 refuses any other set."""
        current = {s["uuid"]: s["label"] for s in self.db.samples(board_model)}
        why = None
        if len(set(sample_uuids)) != len(sample_uuids) or len(sample_uuids) != labels.CALIBRATION_IMAGES:
            why = QT_TRANSLATE_NOOP("Errors", "it holds {n} different images, not {size}")
            why = why.fill(n=len(set(sample_uuids)), size=labels.CALIBRATION_IMAGES)
        elif other := [u for u in sample_uuids if current.get(u) not in ("OK", "NG")]:
            why = QT_TRANSLATE_NOOP("Errors", "{n} of its images are not labelled OK or NG under {board_model}")
            why = why.fill(n=len(other), board_model=board_model)
        if why is not None:
            raise AoiError("AOI-TRN-035", reason=why)
        row = {"board_model": board_model, "sample_uuids": json.dumps(sample_uuids), "made_by": self.user_uuid}
        uid = self.db.add_row("calibration_sets", **row)
        self.audit("calibration.make", "calibration_set", uid, None, {**row, "sample_uuids": sample_uuids})
        return uid

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Labelling a calibration image blind"))
    @transactional
    def label_blind(self, set_uuid: str, sample_uuid: str, label: str, defect_type: str | None = None) -> str:
        """Record the user acting's own label of an image of a calibration set, kept apart from the image's label: OK,
        or NG with one of the 33 defect types, once per image and user. Returns its UUID, audited as `label.blind`.
        AOI-TRN-036 refuses an image outside the set, any other label, and a second blind label of an image."""
        cal, sample = self.db.calibration_sets("", set_uuid), self.db.sample_by_uuid(sample_uuid)
        why = None
        if not cal or sample_uuid not in cal[0]["sample_uuids"]:
            why = QT_TRANSLATE_NOOP("Errors", "it is not an image of the calibration set")
        elif not labels.blind_label_ok(label, defect_type):
            why = QT_TRANSLATE_NOOP("Errors", "a blind label is OK, or NG with one of the 33 defect types")
        elif sample_uuid in self.db.blind_labels(set_uuid, self.user_uuid):
            why = QT_TRANSLATE_NOOP("Errors", "you labelled it blind already")
        if why is not None:
            raise AoiError("AOI-TRN-036", sample=Path(sample["path"]).name if sample else sample_uuid, reason=why)
        row = {"set_uuid": set_uuid, "sample_uuid": sample_uuid, "label": label, "defect_type": defect_type}
        uid = self.db.add_row("blind_labels", **row, labelled_by=self.user_uuid)
        self.audit("label.blind", "calibration_set", set_uuid, None, {"uuid": uid, **row})
        return uid

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Running an agreement check"))
    @transactional
    def run_agreement_check(self, set_uuid: str, labeller_a: str, labeller_b: str) -> dict[str, Any]:
        """Compare two users' (UUIDs) blind labels of every image of a calibration set, as labels.agreement does, and
        store the check with its counts, targets and labellers; returns it as `agreement_checks` reads it, audited as
        `agreement.check`. AOI-TRN-037 refuses one user twice and a labeller who has not labelled every image blind."""
        cal = next(iter(self.db.calibration_sets("", set_uuid)), None)
        a, b = (self.db.blind_labels(set_uuid, u) for u in (labeller_a, labeller_b))
        why = None
        if cal is None:
            why = QT_TRANSLATE_NOOP("Errors", "the workspace holds no such calibration set")
        elif labeller_a == labeller_b:
            why = QT_TRANSLATE_NOOP("Errors", "the two labellers are one user")
        elif min(len(a), len(b)) < len(cal["sample_uuids"]):
            why = QT_TRANSLATE_NOOP("Errors", "a labeller has labelled {n} of its {size} images blind")
            why = why.fill(n=min(len(a), len(b)), size=len(cal["sample_uuids"]))
        if cal is None or why is not None:
            raise AoiError("AOI-TRN-037", reason=why)
        counts = labels.agreement(a, b) | {"set_uuid": set_uuid, "board_model": cal["board_model"]}
        counts |= {"labeller_a": labeller_a, "labeller_b": labeller_b, "run_by": self.user_uuid}
        uid = self.db.add_row("agreement_checks", **counts | {"agreed": int(counts["agreed"])})
        check = self.db.agreement_checks(cal["board_model"], uid)[0]
        self.audit("agreement.check", "calibration_set", set_uuid, None, check)
        return check

    def calibration_sets(self, board_model: str) -> list[dict[str, Any]]:
        """A board model's calibration sets, newest first (uuid, board_model, sample_uuids, made_by, at_utc)."""
        return self.db.calibration_sets(board_model)

    def agreement_checks(self, board_model: str) -> list[dict[str, Any]]:
        """A board model's agreement checks, newest first (uuid, set_uuid, labeller_a, labeller_b, images, ok_ng_agree,
        both_ng, type_agree, ok_ng_target, type_target, agreed 1 or 0, run_by, at_utc)."""
        return self.db.agreement_checks(board_model)

    # --- frozen dataset versions (REQ-TRN-005; S35): rows and manifest never change; a change goes into v<N+1> ---
    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Freezing a dataset version"))
    def freeze_dataset(
        self, board_model: str, view: str, revision: str, customer: str, allowed_uses: Sequence[str] = ("own",)
    ) -> dict[str, Any]:
        """Freeze the OK and NG images of a board model and view as version N, one more than the view's last, named by
        `datasets.name`: writes datasets/<name>/manifest.json (each file's relative path, SHA-256, label row and label,
        boxes, labeller, checker); stores the version with its SHA-256, the customer, the uses (own by default, each
        once) and the agreement check that decides (`_newest_check`); audited as `dataset.freeze`. Refused, writing
        nothing, in this order: a view not in aoi.hal.VIEWS (AOI-TRN-038), a board model name with no Latin letter or
        digit (AOI-TRN-039), then as `_refuse_input` and `_refuse_freeze` give; `_refuse_freeze` runs once before any
        file is read, so a freeze it refuses reads no image file first. The files are hashed next, with no lock held
        (AOI-INSP-001 for one that cannot be read). Then, with the database lock held, one write transaction finds N,
        checks the name and the gate again and reads the files' labels and boxes, stores the rows and the audit entry,
        and moves the manifest into place (atomic.staged) just before it commits; a failed commit puts back the manifest
        it replaced before the lock is released, so no other freeze comes between. A freeze that dies before the move
        leaves no manifest; one that dies between the move and the commit leaves a manifest no row names, which the next
        freeze of that name replaces. A second freeze of the view waits for the first. AOI-TRN-041 for a manifest that
        cannot be written, AOI-TRN-042 for one whose path the system refuses as too long."""
        uses = list(dict.fromkeys(allowed_uses))  # a use given twice is kept once
        paths = [s["path"] for label in ("OK", "NG") for s in self._in_view(board_model, view, label)]  # AOI-TRN-038
        self._refuse_input(board_model, view, revision, customer, uses)
        name = datasets.name(board_model, revision, view, self._next_version(board_model, view))
        self._refuse_freeze(name, board_model, view, customer)  # before any file is read, and again in the transaction
        known = {p: (self._sha256(p), to_stored(p, self.settings.root)) for p in paths}  # file work, before the lock
        # the manifest's exit runs after the commit and before the lock is released
        with self.db.locked(), contextlib.ExitStack() as manifest, self.db.transaction():
            n = self._next_version(board_model, view)  # again, in the transaction that stores it
            name = datasets.name(board_model, revision, view, n)
            agreed = self._refuse_freeze(name, board_model, view, customer)
            version: dict[str, Any] = {"uuid": new_uuid(), "name": name, "board_model": board_model}
            version |= {"revision": revision, "view": view, "version": n, "customer": customer.strip()}
            version |= {"allowed_uses": uses, "agreement_check_uuid": agreed["uuid"], "frozen_by": self.user_uuid}
            version |= {"frozen_at": now_utc()}
            draws = [{k: v for k, v in d.items() if k != "id"} for d in self.db.ok_check_draws(board_model, view)]
            head = version | {
                "agreement_check": {k: v for k, v in agreed.items() if k != "id"},
                "ok_check_draws": draws,
            }
            in_view = [s for s in self.db.samples(board_model) if s["side"] == view and s["label"] != "UNSURE"]
            boxes = self.db.current_boxes(board_model)  # one query, not one per file, while the lock is held
            files = [self._frozen_file(s, known, boxes.get(s["uuid"], [])) for s in in_view]
            data, sha = datasets.manifest(head, files)
            rel = f"{datasets.FOLDER}/{name}/manifest.json"
            self.db.add_dataset(version | {"manifest_path": rel, "manifest_sha256": sha}, files)
            manifest.enter_context(_manifest_write(name, rel, self.settings.root))
            # sealed once the row names the version's board model, so its store is found (REQ-TRN-017)
            move_in = manifest.enter_context(atomic.staged(self.settings.root / rel, self._sealed(rel, data) or data))
            keep = ("name", "customer", "allowed_uses", "agreement_check_uuid")
            after = {k: version[k] for k in keep} | {"files": len(files), "manifest_sha256": sha}
            self.audit("dataset.freeze", "dataset", version["uuid"], None, after)
            move_in()
        return self.db.datasets(board_model, version["uuid"])[0]

    def datasets(self, board_model: str) -> list[dict[str, Any]]:
        """A board model's frozen versions, newest first, as the datasets table holds them (docs/ARCHITECTURE.md)."""
        return self.db.datasets(board_model)

    def dataset_items(self, dataset_uuid: str) -> list[dict[str, Any]]:
        """A frozen version's files as its manifest lists them, each with its row's id, uuid and dataset_uuid."""
        return self.db.dataset_items(dataset_uuid)

    def verify_dataset(self, dataset_uuid: str) -> dict[str, Any]:
        """Re-hash a frozen version's manifest and each of its files against the SHA-256 stored at the freeze
        (REQ-TRN-005), writing nothing: `manifest` is same, changed or missing; `files` counts the files, and `matched`,
        `changed` and `missing` list their relative paths in the manifest's order. AOI-TRN-028 for a version the
        workspace does not hold. Hashes on this thread; the Datasets tab runs it on the pool. A file of a customer's
        dataset store is hashed decrypted, and one that does not decrypt (changed, moved, damaged) is changed; a key
        this station does not hold is AOI-TRN-025 (REQ-TRN-017)."""
        if not (found := self.db.datasets("", dataset_uuid)):
            raise AoiError("AOI-TRN-028", dataset=dataset_uuid)
        sha = self._verified_sha256(self.settings.root / found[0]["manifest_path"])
        result: dict[str, Any] = {"matched": [], "changed": [], "missing": []}
        result["manifest"] = "missing" if sha is None else "same" if sha == found[0]["manifest_sha256"] else "changed"
        items = self.db.dataset_items(dataset_uuid)
        for item in items:
            sha = self._verified_sha256(resolve(item["path"], self.settings.root))
            result["missing" if sha is None else "matched" if sha == item["sha256"] else "changed"].append(item["path"])
        return result | {"files": len(items)}

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Locking a validation set"))
    @transactional
    def lock_validation_set(self, dataset_uuid: str, seed: int | None = None) -> dict[str, Any]:
        """Split a frozen version once, with a recorded seed (a new one when None), into its training set and a locked
        validation set (REQ-TRN-006; S36), as `datasets.split` draws them: 50 OK files, and 30 % of the NG files rounded
        up, by defect type where it can; a file whose SHA-256 any earlier split locked is locked again, and files no
        split put in training are drawn first. Audited as `dataset.lock`; returns `validation_split`. Nothing unlocks or
        splits a version again: a new split needs a new version. Refused with AOI-TRN-022, writing nothing, for a
        version the workspace does not hold, one split already and one with fewer than 50 OK files. Reads the rows,
        not the files: a file changed since the freeze keeps the SHA-256 the freeze stored, as verify_dataset shows."""
        found = self.db.datasets("", dataset_uuid)
        items = self.db.dataset_items(dataset_uuid) if found else []
        ok, why = sum(i["label"] == "OK" for i in items), None
        if not found:
            why = QT_TRANSLATE_NOOP("Errors", "the workspace holds no such dataset version")
        elif self.db.validation_split(dataset_uuid) is not None:
            why = QT_TRANSLATE_NOOP("Errors", "its validation set is locked already, and a version is split only once")
        elif ok < datasets.VALIDATION_OK:
            why = QT_TRANSLATE_NOOP("Errors", "it holds {ok} OK image(s), and a validation set holds {least}")
            why = why.fill(ok=ok, least=datasets.VALIDATION_OK)
        if why is not None:
            raise AoiError("AOI-TRN-022", name=found[0]["name"] if found else dataset_uuid, reason=why)
        seed = secrets.randbelow(2**31) if seed is None else seed
        parts = datasets.split(items, seed, self.db.split_sha256("validation"), self.db.split_sha256("train"))
        split = {"uuid": new_uuid(), "dataset_uuid": dataset_uuid, "seed": seed, "locked_by": self.user_uuid}
        self.db.add_split(split | {"locked_at": now_utc()}, parts)
        after: dict[str, Any] = {"split_uuid": split["uuid"], "seed": seed}
        for part, files in parts.items():
            after |= {f"{part}_{label.lower()}": sum(f["label"] == label for f in files) for label in ("OK", "NG")}
        after["validation_ng_types"] = dict(
            Counter(datasets.stratum(f) for f in parts["validation"] if f["label"] == "NG")
        )
        self.audit("dataset.lock", "dataset", dataset_uuid, None, after)
        return self.db.validation_split(dataset_uuid) or {}

    def validation_split(self, dataset_uuid: str) -> dict[str, Any] | None:
        """A frozen version's split as the database holds it: uuid, dataset_uuid, seed, locked_by, locked_at, and the
        dataset item UUIDs of its "train" and "validation" parts; None while it is not split."""
        return self.db.validation_split(dataset_uuid)

    # --- training from a frozen version (REQ-TRN-007, REQ-TRN-017; S39) ------------------------------------------
    def _training_set(
        self, dataset_uuid: str, use: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """A frozen version and the OK and NG files of its training set, in the manifest's order; else, from the rows
        alone, the first reason not to train: no such version (AOI-TRN-045); a board model name the rule for a new one
        refuses (AOI-TRN-019, AOI-TRN-005), as its folder under models/ does; its board model in no customer's dataset
        store, in a shredded one or in another customer's than the version names, or `use` not among the uses the
        version allows (AOI-TRN-046, audited as `training.refused`, REQ-TRN-017); no locked validation set, or fewer
        than datasets.TRAIN_OK OK files in its training set (AOI-TRN-045); a file of the training set whose SHA-256
        any split locked for validation (AOI-TRN-043, REQ-TRN-006). The validation set's files are never listed."""
        found = self.db.datasets("", dataset_uuid)
        if not found:
            none = QT_TRANSLATE_NOOP("Errors", "the workspace holds no such dataset version")
            raise AoiError("AOI-TRN-045", name=dataset_uuid, reason=none)
        version, why = found[0], cast(Phrase | None, None)
        customer, board_model = version["customer"], version["board_model"]
        self._refuse_unsafe_name(board_model)  # the run writes the board model's row and its folder
        self._refuse_case_variant(board_model)
        if not inside(self.settings.models_dir / board_model, self.settings.models_dir):  # named before the rule (#112)
            raise AoiError("AOI-TRN-019", name=board_model)
        if (store := self.db.board_model_store(board_model)) is None:
            why = QT_TRANSLATE_NOOP("Errors", "its images are in no customer's dataset store; an Admin moves them in")
        elif store["shredded_at"]:
            why = QT_TRANSLATE_NOOP("Errors", "its dataset store was shredded on {date}")
            why = why.fill(date=store["shredded_at"][:10])
        elif store["customer"] != customer:
            why = QT_TRANSLATE_NOOP("Errors", "its images are in the dataset store of {store}, not of {customer}")
            why = why.fill(store=store["customer"], customer=customer)
        elif use not in version["allowed_uses"]:
            why = QT_TRANSLATE_NOOP("Errors", "{customer} allowed only {uses}")
            why = why.fill(customer=customer, uses=", ".join(version["allowed_uses"]))
        if why is not None:
            with self.db.transaction():
                after = {"use": use, "customer": customer, "code": "AOI-TRN-046"}
                self.audit("training.refused", "dataset", dataset_uuid, None, after, reason=str(why))
            raise AoiError("AOI-TRN-046", name=version["name"], use=use, reason=why)
        split = self.db.validation_split(dataset_uuid)
        train = set(split["train"]) if split else set()
        items = [i for i in self.db.dataset_items(dataset_uuid) if i["uuid"] in train]
        ok, ng = ([i for i in items if i["label"] == label] for label in ("OK", "NG"))
        if split is None:
            why = QT_TRANSLATE_NOOP("Errors", "its validation set is not locked; training reads only a training set")
        elif len(ok) < datasets.TRAIN_OK:
            why = QT_TRANSLATE_NOOP("Errors", "its training set holds {ok} OK image(s), and training needs {least}")
            why = why.fill(ok=len(ok), least=datasets.TRAIN_OK)
        if why is not None:
            raise AoiError("AOI-TRN-045", name=version["name"], reason=why)
        locked = self.db.split_sha256("validation")  # by content, whatever its path or version (REQ-TRN-006)
        if held := [i for i in items if i["sha256"] in locked]:
            raise AoiError("AOI-TRN-043", name=version["name"], count=len(held))
        return version, ok, ng

    def training_version(self, board_model: str) -> dict[str, Any]:
        """The newest frozen version of `board_model` whose validation set is locked: the one Training trains from
        (REQ-TRN-007). AOI-TRN-045 when no version of it is."""
        for version in self.db.datasets(board_model):
            if self.db.validation_split(version["uuid"]) is not None:
                return version
        why = QT_TRANSLATE_NOOP("Errors", "no frozen dataset version of it has a locked validation set")
        raise AoiError("AOI-TRN-045", name=board_model, reason=why)

    def _read_frozen(self, version: dict[str, Any], item: dict[str, Any]) -> np.ndarray:
        """A file of a frozen version, decoded (decrypted in memory first when in a store); AOI-TRN-045 when the
        SHA-256 of the bytes read is not the one frozen: the file changed since the freeze, or another is in its
        place."""
        image, sha = self._load_image_sha256(resolve(item["path"], self.settings.root))
        if sha != item["sha256"]:
            why = QT_TRANSLATE_NOOP("Errors", "{file} is not the file frozen, by its SHA-256").fill(file=item["path"])
            raise AoiError("AOI-TRN-045", name=version["name"], reason=why)
        return image

    # --- customer dataset stores (REQ-TRN-017; S38; ADR 0010) ---------------------------------------------------
    @requires("Admin", QT_TRANSLATE_NOOP("Errors", "Creating a customer's dataset store"))
    @transactional
    def create_store(self, customer: str) -> dict[str, Any]:
        """A new encrypted dataset store for `customer`: a random 256-bit key, saved in the key store under the store's
        UUID (Windows Credential Manager on a station) and never in the workspace, with its key id and check value in
        `dataset_stores`; audited as `store.create` (no key). Returns the store with `sheet`, the key as the recovery
        sheet prints it: the caller shows or prints it once, for the person who holds the data under the contract.
        AOI-TRN-044, writing nothing, for no customer and for a customer whose store is not shredded."""
        name, why = customer.strip(), None
        if not name:
            why = QT_TRANSLATE_NOOP("Errors", "no customer is given")
        elif any(s["customer"].casefold() == name.casefold() and not s["shredded_at"] for s in self.db.stores()):
            why = QT_TRANSLATE_NOOP("Errors", "the customer has a store already, and has one at a time")
        if why is not None:
            raise AoiError("AOI-TRN-044", store=name or QT_TRANSLATE_NOOP("Errors", "a new customer"), reason=why)
        key, key_id = crypto.new_key()
        store: dict[str, Any] = {"uuid": new_uuid(), "customer": name, "key_id": key_id.hex()}
        store |= {"check_value": crypto.check_value(key), "created_by": self.user_uuid, "created_at": now_utc()}
        self.db.add_store(store)
        self.audit("store.create", "dataset_store", store["uuid"], None, {k: store[k] for k in ("customer", "key_id")})
        self._save_key(store, key)  # last before the commit: a key whose store is not stored would open nothing
        return {k: v for k, v in store.items() if k != "check_value"} | {"sheet": crypto.sheet(key)}

    @requires("Admin", QT_TRANSLATE_NOOP("Errors", "Restoring a dataset store's key"))
    @transactional
    def restore_store_key(self, store_uuid: str, sheet: str) -> None:
        """Save a store's key again from its recovery sheet, typed on a new PC or Windows account (ADR 0010, decision
        7); audited as `store.restore`. AOI-TRN-044, writing nothing, for a store the workspace does not hold, one
        shredded, and a sheet whose key is not the store's (by its check value)."""
        store = self._store(store_uuid)
        key = crypto.key_from_sheet(sheet)
        if key is None or crypto.check_value(key) != store["check_value"]:
            why = QT_TRANSLATE_NOOP("Errors", "the key typed is not this store's key; check each group of four")
            raise AoiError("AOI-TRN-044", store=store["customer"], reason=why)
        self.audit("store.restore", "dataset_store", store_uuid, None, {"key_id": store["key_id"]})
        self._save_key(store, key)

    @requires("Admin", QT_TRANSLATE_NOOP("Errors", "Moving a board model into a dataset store"))
    def move_in(self, board_model: str, store_uuid: str) -> dict[str, int]:
        """Put `board_model` in a store for good and encrypt its files there (ADR 0010, decision 5): every file under
        images/<board model>/ and the manifest of each of its frozen versions, keeping its path. Each plain file is
        encrypted into a crash-safe write, read back and decrypted, and kept only when the SHA-256 matches; else its
        plain bytes are written back and AOI-TRN-044 stops the move. The board model's row in `board_model_stores` and
        the audit entry `store.move_in` (files to move) are written first, so from then on a plain file of it is
        refused (AOI-TRN-025) and an interrupted move is finished by calling this again, which skips the files already
        moved. Returns the counts `moved` and `already`. AOI-TRN-044, writing nothing, for a store the workspace does
        not hold or that is shredded, a board model that does not exist, one in another store, and a file encrypted
        under another store's key; AOI-TRN-019 for a board model whose name is not one folder's (#112)."""
        store = self._store(store_uuid)
        key = self._key(store)  # AOI-TRN-025 for a key this station does not hold
        current, why = self.db.board_model_store(board_model), None
        if board_model not in self.db.board_models():
            why = QT_TRANSLATE_NOOP("Errors", "the workspace holds no board model {board}").fill(board=board_model)
        elif current is not None and current["uuid"] != store_uuid:
            why = QT_TRANSLATE_NOOP("Errors", "{board} is in the store of {other}, and a board model never leaves it")
            why = why.fill(board=board_model, other=current["customer"])
        if why is not None:
            raise AoiError("AOI-TRN-044", store=store["customer"], reason=why)
        if not one_folder_name(board_model):  # named before names were checked (#112): "." would be all of images/
            raise AoiError("AOI-TRN-019", name=board_model)
        files = stores.files_of(self.settings.root, board_model, [d["name"] for d in self.db.datasets(board_model)])
        try:
            heads = [(f, stores.header_of(f)) for f in files]
        except OSError as e:
            why = QT_TRANSLATE_NOOP("Errors", "a file of it could not be read ({reason})").fill(reason=str(e))
            raise AoiError("AOI-TRN-044", str(e), store=store["customer"], reason=why) from e
        if foreign := [f for f, h in heads if h is not None and h.key_id.hex() != store["key_id"]]:
            why = crypto.OTHER_KEY.fill(file=to_stored(foreign[0], self.settings.root))
            raise AoiError("AOI-TRN-044", store=store["customer"], reason=why)
        plain = [f for f, h in heads if h is None]
        with self.db.transaction():
            if current is None:
                row = {"uuid": new_uuid(), "board_model": board_model, "store_uuid": store_uuid}
                self.db.add_board_model_store(row | {"set_by": self.user_uuid, "set_at": now_utc()})
            after = {"board_model": board_model, "files": len(plain), "resumed": current is not None}
            self.audit("store.move_in", "dataset_store", store_uuid, None, after)
        for f in plain:
            self._encrypt_in_place(store, key, f)
        return {"moved": len(plain), "already": len(files) - len(plain)}

    @requires("Admin", QT_TRANSLATE_NOOP("Errors", "Shredding a customer's dataset store"))
    def shred_store(self, store_uuid: str) -> dict[str, int]:
        """End a store for good when its engagement ends (ADR 0010, decision 9). Its key is deleted from this
        station's key store first, which alone leaves every copy of its files unreadable, a backup's included, once
        the recovery sheet is destroyed too. Then a row of `store_shreds` and the audit entry `store.shred` record it,
        with the key id and the counts, and the files of its board models are deleted: under images/, each frozen
        version's folder under datasets/, and their AI models and golden boards under models/. Rows stay (ADR 0009),
        and a file of the store is refused from then on with AOI-TRN-025. Calling this again finishes a shred stopped
        part-way, deleting what is left, and is audited too. Returns the counts `files` (images and manifests) and
        `models`. AOI-TRN-044 for a store the workspace does not hold, a key the key store would not delete (nothing
        changed) and a file that would not go (the rest went, and the shred stays recorded)."""
        if (store := self.db.store(store_uuid)) is None:
            why = QT_TRANSLATE_NOOP("Errors", "the workspace holds no such store")
            raise AoiError("AOI-TRN-044", store=store_uuid, reason=why)
        root, models = self.settings.root, self.settings.models_dir
        boards = [(b, [d["name"] for d in self.db.datasets(b)]) for b in store["board_models"]]
        files = [f for b, versions in boards for f in stores.files_of(root, b, versions)]
        derived = [
            f for b, _ in boards if (models / b).is_dir() for f in sorted((models / b).rglob("*")) if f.is_file()
        ]
        if not store["shredded_at"]:
            try:
                self.credentials.delete(credentials.STORE_PREFIX + store_uuid)  # first: from here nothing of it opens
            except OSError as e:
                why = QT_TRANSLATE_NOOP("Errors", "this station's key store did not delete the key ({reason})")
                raise AoiError("AOI-TRN-044", str(e), store=store["customer"], reason=why.fill(reason=str(e))) from e
            self._keys.pop(store_uuid, None)
        with self.db.transaction():
            if not store["shredded_at"]:
                row = {"uuid": new_uuid(), "store_uuid": store_uuid, "key_id": store["key_id"], "files": len(files)}
                self.db.add_shred(row | {"shredded_by": self.user_uuid, "shredded_at": now_utc()})
            after = {"customer": store["customer"], "key_id": store["key_id"], "board_models": store["board_models"]}
            after |= {"files": len(files), "models": len(derived), "resumed": bool(store["shredded_at"])}
            self.audit("store.shred", "dataset_store", store_uuid, None, after)
        folders = [root / stores.IMAGES / b for b, _ in boards] + [models / b for b, _ in boards]
        folders += [root / datasets.FOLDER / name for _, versions in boards for name in versions]
        if left := _deleted(files + derived, folders):
            why = QT_TRANSLATE_NOOP("Errors", "{count} file(s) would not go, {file} first ({detail}); shred it again")
            reason = why.fill(count=len(left), file=to_stored(left[0][0], root), detail=str(left[0][1]))
            raise AoiError("AOI-TRN-044", store=store["customer"], reason=reason)
        return {"files": len(files), "models": len(derived)}

    def stores(self) -> list[dict[str, Any]]:
        """Every dataset store, oldest first: uuid, customer, key_id, created_by, created_at, shredded_at (None while
        it is not shredded) and its board_models. No key."""
        return [{k: v for k, v in s.items() if k != "check_value"} for s in self.db.stores()]

    def store_of(self, board_model: str) -> dict[str, Any] | None:
        """The store `board_model` is in, as `stores` lists it, or None for a board model in none (its files plain)."""
        found = self.db.board_model_store(board_model)
        return None if found is None else {k: v for k, v in found.items() if k != "check_value"}

    def _store(self, store_uuid: str) -> dict[str, Any]:
        """A store that is not shredded; AOI-TRN-044 for one the workspace does not hold or that is shredded."""
        store = self.db.store(store_uuid)
        if store is None or store["shredded_at"]:
            why = QT_TRANSLATE_NOOP("Errors", "the workspace holds no such store, or it is shredded")
            raise AoiError("AOI-TRN-044", store=store["customer"] if store else store_uuid, reason=why)
        return store

    def _save_key(self, store: dict[str, Any], key: bytes) -> None:
        try:
            self.credentials.write(credentials.STORE_PREFIX + store["uuid"], key)
        except OSError as e:
            why = QT_TRANSLATE_NOOP("Errors", "this station's key store refused the key ({reason})")
            raise AoiError("AOI-TRN-044", str(e), store=store["customer"], reason=why.fill(reason=str(e))) from e
        self._keys.pop(store["uuid"], None)

    def _key(self, store: dict[str, Any]) -> bytes:
        """The store's key from this station's key store, checked against its check value; AOI-TRN-025 when this
        station holds none or holds another."""
        if (key := self._keys.get(store["uuid"])) is not None:
            return key
        try:
            key = self.credentials.read(credentials.STORE_PREFIX + store["uuid"])
        except OSError as e:
            why = QT_TRANSLATE_NOOP("Errors", "this station's key store could not be read ({reason})")
            raise AoiError("AOI-TRN-025", str(e), store=store["customer"], reason=why.fill(reason=str(e))) from e
        if key is None:
            why = QT_TRANSLATE_NOOP("Errors", "this station holds no key for it")
        elif crypto.check_value(key) != store["check_value"]:
            why = QT_TRANSLATE_NOOP("Errors", "the key this station holds is not its key")
        else:
            self._keys[store["uuid"]] = key
            return key
        raise AoiError("AOI-TRN-025", store=store["customer"], reason=why)

    def _encrypt_in_place(self, store: dict[str, Any], key: bytes, path: Path) -> None:
        """Encrypt one plain file of a store where it is, with a crash-safe write; keep it only once it reads back
        decrypted to the same SHA-256, else write the plain bytes back and refuse with AOI-TRN-044."""
        stored, key_id = to_stored(path, self.settings.root), bytes.fromhex(store["key_id"])
        try:
            plain = path.read_bytes()
        except OSError as e:
            why = QT_TRANSLATE_NOOP("Errors", "{file} could not be read ({detail})").fill(file=stored, detail=str(e))
            raise AoiError("AOI-TRN-044", str(e), store=store["customer"], reason=why) from e
        error: Exception | None = None
        try:
            atomic.write_bytes(path, crypto.encrypt(key, key_id, store["uuid"], stored, plain))
            back = crypto.decrypt(key, key_id, store["uuid"], stored, path.read_bytes())
        except (OSError, crypto.NotOpened) as e:  # a write the disk refused leaves the plain file as it was
            back, error = b"", e
        if error is not None or hashlib.sha256(back).digest() != hashlib.sha256(plain).digest():
            with contextlib.suppress(OSError):
                atomic.write_bytes(path, plain)
            why = QT_TRANSLATE_NOOP("Errors", "{file} did not read back as written, and was left plain ({detail})")
            raise AoiError("AOI-TRN-044", store=store["customer"], reason=why.fill(file=stored, detail=str(error)))

    def _store_for(self, path: str | Path) -> tuple[dict[str, Any], str] | None:
        """The store a workspace file is in, with the path as the rows store it: a file under images/<board model>/,
        or a version's folder under datasets/, of a board model in a store; else None, and the file is plain."""
        stored = to_stored(path, self.settings.root)
        found = stores.owner(stored)
        if found is None:
            return None
        board_model = found[1] if found[0] == stores.IMAGES else self.db.dataset_board_model(found[1])
        store = self.db.board_model_store(board_model) if board_model else None
        return None if store is None else (store, stored)

    def _plain_bytes(self, path: Path) -> bytes:
        """A file's bytes as the app reads them: a file of a customer's dataset store decrypted in memory, any other
        as it is on disk. OSError as reading gives it; AOI-TRN-025 for a store file that does not open (no key, a
        wrong key, not encrypted, changed, moved or damaged) or one of a shredded store."""
        try:
            return self._open(path)
        except crypto.NotOpened as e:  # only a file of a store is decrypted
            found = self._store_for(path)
            customer, stored = (str(found[0]["customer"]), found[1]) if found is not None else ("", str(path))
            raise AoiError("AOI-TRN-025", store=customer, reason=e.reason.fill(file=stored)) from e

    def _open(self, path: str | Path) -> bytes:
        """`_plain_bytes`, with crypto.NotOpened for a store file that does not decrypt."""
        if (found := self._store_for(path)) is None:
            return Path(path).read_bytes()
        store, stored = found
        key = self._live_key(store)  # a shredded store's files are gone: that, not a missing file, is the reason
        return crypto.decrypt(key, bytes.fromhex(store["key_id"]), store["uuid"], stored, Path(path).read_bytes())

    def _live_key(self, store: dict[str, Any]) -> bytes:
        """`_key` of a store that is not shredded; AOI-TRN-025 naming the day it was."""
        if store["shredded_at"]:
            why = QT_TRANSLATE_NOOP("Errors", "it was shredded on {date}").fill(date=store["shredded_at"][:10])
            raise AoiError("AOI-TRN-025", store=store["customer"], reason=why)
        return self._key(store)

    def _image_size(self, path: str) -> tuple[int, int]:
        """`labels.image_size`: a file of a customer's dataset store decrypted whole first, any other with only its
        header read."""
        return labels.image_size(path, None if self._store_for(path) is None else self._plain_bytes)

    def _sealed(self, stored: str, data: bytes) -> bytes | None:
        """`data` encrypted for the workspace path `stored` when that path is in a customer's dataset store, else
        None (the file is written plain)."""
        if (found := self._store_for(self.settings.root / stored)) is None:
            return None
        store = found[0]
        return crypto.encrypt(self._live_key(store), bytes.fromhex(store["key_id"]), store["uuid"], stored, data)

    def _file_sha256(self, path: str | Path) -> str:
        """The SHA-256 of a file's plain bytes: read a block at a time when it is plain, decrypted in memory when it
        is in a customer's dataset store. OSError when it cannot be read; AOI-TRN-025 as `_plain_bytes`."""
        if self._store_for(path) is None:
            return datasets.sha256(path)
        return hashlib.sha256(self._plain_bytes(Path(path))).hexdigest()

    def _verified_sha256(self, path: Path) -> str | None:
        """`_file_sha256` for verify_dataset: None for a file that is missing or cannot be read, and an empty text,
        which matches no stored SHA-256, for a store file that does not decrypt."""
        try:
            return hashlib.sha256(self._open(path)).hexdigest()
        except OSError:
            return None
        except crypto.NotOpened:
            return ""

    def _refuse_input(self, board_model: str, view: str, revision: str, customer: str, uses: list[str]) -> None:
        """The refusals that read only what the freeze was given: no Latin letter or digit in the board model's name
        (AOI-TRN-039), a revision other than 1 to 16 letters and digits (AOI-TRN-027), no customer (AOI-TRN-024), a use
        outside the three (AOI-TRN-027)."""
        if not datasets.token(board_model):
            raise AoiError("AOI-TRN-039", board=board_model)
        name, why = datasets.name(board_model, revision, view, self._next_version(board_model, view)), None
        if not datasets.REVISION.fullmatch(revision):
            why = QT_TRANSLATE_NOOP("Errors", "the board revision {revision} is not 1 to 16 letters and digits")
            why = why.fill(revision=revision)
        elif not customer.strip():
            raise AoiError("AOI-TRN-024", name=name)
        elif not uses or not set(uses) <= set(datasets.ALLOWED_USES):
            why = QT_TRANSLATE_NOOP("Errors", "the allowed uses are one or more of own, shared and demos")
        if why is not None:
            raise AoiError("AOI-TRN-027", name=name, reason=why)

    def _next_version(self, board_model: str, view: str) -> int:
        return 1 + max((d["version"] for d in self.db.datasets(board_model) if d["view"] == view), default=0)

    def _refuse_freeze(self, name: str, board_model: str, view: str, customer: str) -> dict[str, Any]:
        """The agreement check a version is frozen with; else, read in the freeze's transaction, the first reason not to
        freeze: another board model whose name gives the same letters and digits has frozen versions (AOI-TRN-040), a
        version of that name exists or the view holds no OK or NG image (AOI-TRN-027), an NG label not checked
        (AOI-TRN-020), too few drawn OK labels checked (AOI-TRN-021), the newest agreement check missing or short of
        its targets, and the board model in no customer's dataset store, in a shredded one or in another customer's
        than `customer` (AOI-TRN-027; REQ-TRN-017)."""
        frozen = self.db.dataset_names()
        token = datasets.token(board_model)
        other = next((d for d in frozen if d != board_model and datasets.token(d) == token), None)
        if other is not None:
            raise AoiError("AOI-TRN-040", board=board_model, name=name, other=other)
        status = self.label_check_status(board_model, view)  # its `ready` is labels_ready_to_freeze (REQ-TRN-004)
        newest = self._newest_check(board_model, view)
        why = None
        if name in frozen.get(board_model, []):
            why = QT_TRANSLATE_NOOP("Errors", "a dataset version of that name is in the workspace already")
        elif not status["ok"] + status["ng"]:
            why = QT_TRANSLATE_NOOP("Errors", "the view holds no image labelled OK or NG")
        elif status["ng_unchecked"]:
            raise AoiError("AOI-TRN-020", name=name, count=len(status["ng_unchecked"]))
        elif len(status["ok_checked"]) < status["ok_needed"]:
            checked, needed = len(status["ok_checked"]), status["ok_needed"]
            raise AoiError("AOI-TRN-021", name=name, checked=checked, needed=needed, ok=status["ok"])
        elif newest is None:
            why = QT_TRANSLATE_NOOP("Errors", "no agreement check of the board model holds images of this view")
        elif not newest["agreed"]:
            why = QT_TRANSLATE_NOOP("Errors", "the newest agreement check of the view did not reach the targets")
        elif (store := self.db.board_model_store(board_model)) is None:
            why = QT_TRANSLATE_NOOP("Errors", "its images are in no customer's dataset store; an Admin moves them in")
        elif store["shredded_at"]:  # its images are gone, and its board model never joins another store
            why = QT_TRANSLATE_NOOP("Errors", "its dataset store was shredded on {date}")
            why = why.fill(date=store["shredded_at"][:10])
        elif store["customer"] != customer.strip():
            why = QT_TRANSLATE_NOOP("Errors", "its images are in the dataset store of {store}, not of {customer}")
            why = why.fill(store=store["customer"], customer=customer.strip())
        if why is not None or newest is None:
            raise AoiError("AOI-TRN-027", name=name, reason=why)
        return newest

    def _newest_check(self, board_model: str, view: str) -> dict[str, Any] | None:
        """The newest agreement check of the board model whose calibration set holds an image of `view`: it decides,
        so a newer check short of the targets refuses a freeze until a newer one reaches them (ADR 0009)."""
        side = {s["uuid"]: s["side"] for s in self.db.samples(board_model)}
        sets = {c["uuid"]: c["sample_uuids"] for c in self.db.calibration_sets(board_model)}
        checks = self.db.agreement_checks(board_model)
        return next((c for c in checks if view in {side.get(u) for u in sets.get(c["set_uuid"], [])}), None)

    def _sha256(self, path: str) -> str:
        """A file's SHA-256 for a version, of its plain bytes (`_file_sha256`); AOI-INSP-001, with the system's
        reason, for one that cannot be read."""
        try:
            return self._file_sha256(path)
        except OSError as e:
            raise AoiError("AOI-INSP-001", detail=str(e), path=path) from e

    def _frozen_file(
        self, sample: dict[str, Any], known: dict[str, tuple[str, str]], boxes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """One file of a version as its manifest lists it: its SHA-256 and stored path from `known`, read before the
        lock (a file added since, now), and its current `boxes` as `_label_state` gives them."""
        path = sample["path"]
        sha, stored = known.get(path) or (self._sha256(path), to_stored(path, self.settings.root))
        keys = ("label_uuid", "label", "defect_type", "labelled_by", "checked_by")
        head = {"path": stored, "sha256": sha, "sample_uuid": sample["uuid"]}
        drawn = [{k: b[k] for k in ("x", "y", "w", "h", "dct_type", "severity")} for b in boxes]
        return head | {k: sample[k] for k in keys} | {"boxes": drawn}

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Activating an AI model version"))
    @transactional
    def activate_model(self, model_id: int) -> None:
        """Make a model version the one inspections use (an older version: a rollback)."""
        target = self.db.model(model_id)
        previous = self.db.active_model(target["board_model"])
        self.db.activate_model(model_id)
        old = {"active_version": previous["version"] if previous else None}
        self.audit("model.activate", "model", target["uuid"], old, {"active_version": target["version"]})

    @requires("Admin", QT_TRANSLATE_NOOP("Errors", "Changing users"))
    @transactional
    def add_user(self, name: str, role: str) -> None:
        """Add a user, or change the role of an existing one. Taking the Admin role from the last Admin is refused with
        AOI-USR-002 before anything is written or audited: no one could manage users or settings after it (#170)."""
        users = self.db.users()
        if role != "Admin" and [u["name"] for u in users if u["role"] == "Admin"] == [name]:
            raise AoiError("AOI-USR-002", name=name, role=Phrase("Role", role))  # the role's name as the UI shows it
        before = next((u for u in users if u["name"] == name), None)
        self.db.add_user(name, role)
        old = {"role": before["role"]} if before else None
        self.audit("user.change", "user", self.db.user_uuid(name), old, {"name": name, "role": role})
        if name == self._actor.name:  # the signed-in user's own role: the next role check reads the stored one
            self._actor = Actor(name, role, self.db.user_uuid(name))

    @requires("Admin", QT_TRANSLATE_NOOP("Errors", "Changing settings"))
    def save_settings(self, values: dict[str, Any]) -> None:
        """Write the Settings page's values over settings.json (`Settings.save_keys`: each value checked first,
        AOI-SET-008, every other key kept as the file holds it) and audit `settings.change` with the values the file
        held before (#197). The running app follows the device, defaults and retention at once; the workspace waits for
        the restart, its database, log and folders staying on the open one so no file lands in a folder its database
        does not list (REQ-SET-001), and the language is stored only (no translation is loaded before 2H 2027). The AI
        device is resolved again: when it changes, training and inference use the new one from the next call and the
        weights load again on it (load_model; REQ-SET-002, #201). When the entry cannot be written, settings.json goes
        back to what was in effect and the app keeps it (#178)."""
        before = self.settings.save_keys(values)
        try:
            self.audit("settings.change", "settings", None, before, values)
        except BaseException:
            self.settings.save_keys(before)
            raise
        for name, value in values.items():
            if name != "workspace":
                setattr(self.settings, name, value)
        device = resolve_device(self.settings.device)
        if device != self.device:
            self.log.info("device.change", extra={"before": self.device, "after": device})
            self.device = device
            self._model_cache.clear()  # weights loaded on the old device; a run in progress keeps the model it holds

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Archiving records"))
    @transactional
    def archive_old(self, days: int | None = None) -> int:
        """Archive inspections older than `days` (default: the retention setting); returns how many were archived."""
        days = self.settings.log_retention_days if days is None else days
        n = self.db.archive_old(days)
        self.audit("inspection.archive", "inspections", None, None, {"days": days, "archived": n})
        return n

    def _sweep_ok_maps(self, days: int | None = None) -> int:
        """Delete the map files of OK results older than `days` (default: `map_retention_days_ok`) and forget their
        paths; NG and WARN maps stay, a disputed verdict needs its evidence (REQ-INSP-012). A system action at start-up,
        audited as `maps.sweep`; a file that cannot be deleted, or lies outside results/, keeps its row for later."""
        days = self.settings.map_retention_days_ok if days is None else days
        results = self.settings.results_dir.resolve()
        swept, skipped = [], 0  # ids whose maps went; rows kept, with their paths, for the next start
        for r in self.db.ok_maps_older_than(days):
            try:
                for p in (Path(r[k]).resolve() for k in ("diff_map_path", "ai_map_path") if r[k]):
                    if not p.is_relative_to(results):  # only a row edited on disk names a file elsewhere (#112)
                        raise ValueError(f"{p} is outside the results folder")
                    p.unlink(missing_ok=True)
            except (OSError, ValueError) as e:
                skipped += 1
                self.log.warning("maps.sweep_skipped", extra={"inspection_id": r["id"], "reason": str(e)})
                continue
            swept.append(r["id"])
        if swept:
            after = {"days": days, "swept": len(swept), "skipped": skipped}
            with self.db.transaction():  # the paths forgotten and the entry, or neither (#178)
                self.db.clear_map_paths(swept)
                self.db.add_audit(None, None, "maps.sweep", "inspections", None, None, after, "OK maps past retention")
        self.log.info("maps.swept", extra={"days": days, "swept": len(swept), "skipped": skipped})
        return len(swept)

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Exporting an AI model"))
    def export_model(self, model_id: int, dest: str | Path) -> Path:
        """Copy a model version's file to `dest`, whole or not at all. The audit entry stores `dest` relative to the
        workspace when inside it (REQ-SET-001), else in full."""
        model = self.model(model_id)
        try:
            atomic.copy_file(model["path"], dest)
        except OSError as e:
            if e.filename == model["path"]:  # the AI model's own file, not the destination
                raise
            raise _not_written(e, dest) from e
        after = {"version": model["version"], "dest": to_stored(Path(dest).absolute(), self.settings.root)}
        self._audit_files([Path(dest)], "export.model", "model", model["uuid"], after, [Path(model["path"])])
        return Path(dest)

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Exporting overlay images"))
    def export_overlays(
        self,
        inspections: list[dict[str, Any]],
        folder: str | Path,
        progress: Callable[[int, int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> int:
        """Copy the overlay images of `inspections` (records from `inspections()`) into `folder`; returns how many. A
        copy that fails stops the export with AOI-LOG-001; the entry names the files that left before it, which stay
        (#178), and stores `folder` relative to the workspace when inside it (REQ-SET-001), else in full. A page runs
        it on the pool (REQ-SET-021, #194): `progress(done, total)` follows each overlay, and once `should_stop()` is
        true the copies made stay and the audit entry says the export was cancelled."""
        sources = [Path(r["overlay_path"]) for r in inspections if r.get("overlay_path")]
        sources = [p for p in sources if p.exists()]
        copied: list[Path] = []
        failed: tuple[Path, OSError] | None = None
        stopped = False
        for src in sources:
            if should_stop is not None and should_stop():
                stopped = True
                break
            try:
                atomic.copy_file(src, Path(folder) / src.name)
            except OSError as e:  # the drive full or pulled out, a name the folder cannot take
                failed = (Path(folder) / src.name, e)
                break
            copied.append(Path(folder) / src.name)
            if progress is not None:
                progress(len(copied), len(sources))
        stored = to_stored(Path(folder).absolute(), self.settings.root)
        after: dict[str, Any] = {
            "folder": stored, "records": len(inspections), "copied": len(copied), "cancelled": stopped
        }  # fmt: skip
        if failed:
            after["error"] = f"{failed[0].name}: {failed[1].strerror or failed[1]}"
        self._audit_files(copied, "export.overlays", "inspections", None, after, sources)
        if failed:
            params = {"copied": len(copied), "total": len(sources), "folder": str(folder), "file": failed[0].name}
            why = failed[1].strerror or str(failed[1])
            raise AoiError("AOI-LOG-001", str(failed[1]), reason=why, **params) from failed[1]
        return len(copied)

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Exporting CSV"))
    def export_csv(
        self,
        path: str | Path,
        rows: list[dict[str, Any]],
        what: str = "inspections",
        fieldnames: list[str] | None = None,
    ) -> int:
        """Write `rows` as CSV to `path`, whole or not at all, and audit the export; returns the row count. `fieldnames`
        gives the header when `rows` may be empty."""
        self.export_csv_files([CsvFile(path, rows, what, fieldnames)])
        return len(rows)

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Exporting CSV"))
    def export_csv_files(self, files: list[CsvFile]) -> None:
        """Write `files` as CSV, all or none (Logs & Export's records and checks, #195), then audit each, every entry
        or none. A file that cannot be written (another program holds it open) is refused with AOI-LOG-002 naming it;
        when the entries cannot be written the files are removed (#178). Paths are stored as #196 stores them."""
        try:
            atomic.write_all([(f.path, csv_bytes(f.rows, f.fieldnames)) for f in files])
        except OSError as e:
            raise _not_written(e, e.filename) from e
        try:
            with self.db.transaction():
                for f in files:
                    after = {"path": to_stored(Path(f.path).absolute(), self.settings.root), "rows": len(f.rows)}
                    self.audit("export.csv", f.what, None, None, after)
        except BaseException:
            _remove([Path(f.path) for f in files])
            raise

    @requires("Engineer", QT_TRANSLATE_NOOP("Errors", "Exporting a report"))
    def export_report(
        self, path: str | Path, pdf: bytes, board_model: str, run_uuid: str | None, model_version: str | None
    ) -> None:
        """Write the validation report `pdf` (rendered by AI Model Test) to `path`, whole or not at all, and audit the
        export under the test run it reports (#180). An empty `pdf`, or a file that cannot be written, is refused with
        AOI-LOG-002 and nothing is written or audited; a report whose entry cannot be written is removed (#178)."""
        if not pdf:
            raise AoiError(
                "AOI-LOG-002", path=str(path), reason=QT_TRANSLATE_NOOP("Errors", "the report came out empty")
            )
        with _export_write(path):
            atomic.write_bytes(path, pdf)
        after = {
            "path": to_stored(Path(path).absolute(), self.settings.root), "board_model": board_model,
            "run_uuid": run_uuid, "model_version": model_version, "bytes": len(pdf),
        }  # fmt: skip
        self._audit_files([Path(path)], "export.report", "test_run", run_uuid, after)

    @requires("Operator", QT_TRANSLATE_NOOP("Errors", "Saving a board image"))
    def export_board_image(
        self,
        res: InspectionResult,
        board_model: str | None,
        inspection_id: int | None,
        board_file: str,
        dest: str | Path,
    ) -> Path:
        """Save Image… (F9): write `res`'s board picture with its defect boxes to `dest`, whole or not at all, and audit
        it as `export.image` (#241, REQ-LOG-004). The object is the UUID of record `inspection_id`, None for a result
        that was not saved; the entry holds `dest`, stored as the exports store it (#196), `board_model`, the board's
        file name `board_file` and the verdict. A name whose suffix no image format has is AOI-INSP-002, a file that
        cannot be written AOI-LOG-002 naming it. The picture is written beside `dest` first, then its entry and its
        move into place commit together: when the entry cannot be written, the move fails or the commit fails, `dest`
        is left as it was, a file of that name unchanged and no folder made for it left (#178, #241).
        Every role may save (REQ-INSP-005; who may export is open in #151); a page runs it on the pool (REQ-SET-021)."""
        record = self.inspection(inspection_id) if inspection_id is not None else None
        after = {
            "path": to_stored(Path(dest).absolute(), self.settings.root), "board_model": board_model,
            "board": board_file, "verdict": res.verdict,
        }  # fmt: skip
        data = encode_image(dest, draw_overlay(res))
        with _export_write(dest), atomic.staged(dest, data) as move_in:  # a refused entry never touches `dest` (#241)
            with self.db.transaction():  # a failed move rolls the entry back; a failed commit puts `dest` back
                self.audit("export.image", "inspection", record["uuid"] if record else None, None, after)
                move_in()
        return Path(dest)

    def _audit_files(
        self,
        files: list[Path],
        action: str,
        object_type: str,
        object_uuid: str | None,
        after: dict[str, Any],
        sources: list[Path] | None = None,
    ) -> None:
        """Audit an export; when its entry cannot be written, remove the files it wrote, so none leaves the station
        unaudited (#178). A file cannot join a database transaction, so the files are written first. A file that is
        one of its `sources` (exported onto itself) is the station's own and stays."""
        try:
            self.audit(action, object_type, object_uuid, None, after)
        except BaseException:
            own = {p.resolve() for p in sources or []}
            _remove([f for f in files if f.resolve() not in own])
            raise


@contextlib.contextmanager
def _export_write(path: str | Path) -> Iterator[None]:
    """An export that cannot be written (a folder that cannot be made, a file held open, a full disk) becomes
    AOI-LOG-002; atomic.py has left any earlier file of that name as it was."""
    try:
        yield
    except OSError as e:
        raise _not_written(e, path) from e


def _deleted(files: list[Path], folders: list[Path]) -> list[tuple[Path, OSError]]:
    """Delete `files`, then whatever is left in `folders` once they are empty, deepest first; the files that would not
    go, with why. A file already gone counts as deleted."""
    left = []
    for f in files:
        try:
            f.unlink(missing_ok=True)
        except OSError as e:  # held open by another program, or read-only
            left.append((f, e))
    for folder in folders:
        for d in sorted((p for p in folder.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            with contextlib.suppress(OSError):
                d.rmdir()
        with contextlib.suppress(OSError):
            folder.rmdir()
    return left


@contextlib.contextmanager
def _manifest_write(name: str, path: str, root: Path) -> Iterator[None]:
    """A manifest that cannot be written becomes AOI-TRN-042 for a path the system refuses as too long, as AOI-TRN-011
    does for an import, and AOI-TRN-041 naming the file otherwise; atomic.staged has put the workspace back."""
    try:
        yield
    except OSError as e:
        if _too_long(e):
            raise AoiError("AOI-TRN-042", repr(e), name=name, workspace=str(root)) from e
        raise AoiError("AOI-TRN-041", repr(e), name=name, path=path, reason=e.strerror or str(e)) from e


def _not_written(e: OSError, path: object) -> AoiError:
    """AOI-LOG-002 for a file the user named for an export or a save that cannot be written (#180, #195)."""
    return AoiError("AOI-LOG-002", detail=repr(e), path=str(path), reason=e.strerror or str(e))


def classification_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """NG is the positive class. WARN counts as a call (flagged for review)."""
    lab = [r for r in rows if r["gt"] in (OK, NG)]
    tp = sum(r["gt"] == NG and r["ai_result"] != OK for r in lab)
    fn = sum(r["gt"] == NG and r["ai_result"] == OK for r in lab)
    fp = sum(r["gt"] == OK and r["ai_result"] != OK for r in lab)
    tn = sum(r["gt"] == OK and r["ai_result"] == OK for r in lab)
    n = max(1, len(lab))
    return {
        "samples": len(rows),
        "labelled": len(lab),
        "TP": tp,
        "FN": fn,
        "FP": fp,
        "TN": tn,
        "accuracy": (tp + tn) / n,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "false_call_rate": fp / (fp + tn) if fp + tn else 0.0,  # OK boards wrongly flagged
    }


def export_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    """`rows` as a CSV file, whole or not at all."""
    atomic.write_bytes(path, csv_bytes(rows, fieldnames))


def csv_bytes(rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> bytes:
    """`rows` as CSV, UTF-8 with a BOM so Excel opens Korean; the header comes from `fieldnames` or the first row, so a
    file with no rows still names its columns when `fieldnames` is given."""
    buf = io.StringIO(newline="")
    names = fieldnames or (list(rows[0].keys()) if rows else None)
    if names:
        w = csv.DictWriter(buf, fieldnames=names)
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig" if names else "utf-8")
