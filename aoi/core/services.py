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
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Concatenate, Literal, ParamSpec, TypeVar, cast

import numpy as np

from .. import defects as taxonomy
from .. import logging_setup
from ..config import Settings, resolve_device
from ..data import atomic
from ..data.db import Database, DbError, is_busy, new_uuid
from ..data.errors import WorkspaceError
from ..data.paths import to_stored
from ..data.workspace_lock import WorkspaceLock
from ..errors import QT_TRANSLATE_NOOP, AoiError, Phrase, joined
from ..times import local_date, now_utc
from . import anomaly, imaging
from .compare import Region, changed_regions
from .imaging import align_to_reference, encode_image, list_images, load_image, load_image_sha256, save_image
from .inspector import NG, OK, WARN, AiEvidence, InspectionResult, Inspector, JudgedBy, ai_check, draw_overlay, re_grade
from .jobs import JobCancelled, Jobs
from .maps import load_maps, map_paths, picture_shape, save_maps
from .recipe import Recipe
from .sample_import import REFUSED, ImportFile, ImportReport

ALARM_LIMIT = 1000  # REQ-INSP-006: the alarms a screen shows and that survive a restart
BUSY_ALARM_WAIT_MS = 200  # how long the alarm of a locked database's error, or an Inspection alarm, waits, not 5 s
ALIGNING = QT_TRANSLATE_NOOP("Training", "Aligning {count} images to the reference board")  # a progress line (#199)
NO_TYPE = QT_TRANSLATE_NOOP("Errors", "no defect type was given")  # why AOI-TRN-013 refused an NG sample
NOT_A_TYPE = QT_TRANSLATE_NOOP("Errors", "{name} is not one of them")
STEM_CHARS = 40  # how much of a source file's stem names its evidence or sample file (#245)
WINDOWS = os.name == "nt"
MAX_PATH = 260  # the UTF-16 units of a path, its ending NUL included, that Windows takes with long paths off
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
    at a path of MAX_PATH UTF-16 units or more, which is how open() fails there with long paths off (#245)."""
    if e.errno == errno.ENAMETOOLONG or getattr(e, "winerror", None) == 206:
        return True
    units = len(str(e.filename or "").encode("utf-16-le", "surrogatepass")) // 2  # outside the BMP, 2 units
    return WINDOWS and isinstance(e, FileNotFoundError) and units >= MAX_PATH


def _sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _remove(files: list[Path]) -> None:
    """Remove files a write made before it failed, so none is left that its records or audit entry do not name."""
    for f in files:
        with contextlib.suppress(OSError):
            f.unlink(missing_ok=True)


class AppContext:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.load()
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
        say so."""
        self._refuse_case_variant(board_model)  # a new board model is created by its first import
        self._refuse_untyped(paths[0] if paths else "", label, defect_type)
        dest = self.settings.images_dir / board_model / label
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
                    self.db.add_sample(board_model, str(target), label, defect_type, side, uid, sha256=digest)
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
        refuses the file with AOI-TRN-014 and removes the copy. A copy that cannot be written raises AOI-TRN-008, or
        AOI-TRN-011 when the system refuses its path as too long (#245)."""
        data = imaging.checked_bytes(src, self.settings.max_image_megapixels, self.settings.max_image_megabytes)
        digest = hashlib.sha256(data).hexdigest()
        del data  # up to the size limit in memory: not kept through the copy
        if (had := known.get(digest) or self.db.sample_with_sha256(board_model, digest)) is not None:
            return digest, had
        try:
            atomic.copy_file(src, target)
        except OSError as e:  # gone, unreadable, the workspace drive full, or a path the system refuses
            if _too_long(e) and str(e.filename) != str(src):  # the copy's path, not the picked file's (#245)
                where = {"workspace": str(self.settings.root), "count": count}
                raise AoiError("AOI-TRN-011", str(e), path=str(src), **where) from e
            why = e.strerror or str(e)
            raise AoiError("AOI-TRN-008", str(e), path=str(src), reason=why, count=count) from e
        try:
            same = _sha256(src) == digest == _sha256(target)
        except OSError:  # the source gone right after its copy: it cannot be found unchanged
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
        (REQ-TRN-001). A file refused with a code in `REFUSED` (Inspection's checks, an NG with no type, a source
        changed while copied), one with no label (AOI-TRN-016) and an image the board model already has (AOI-TRN-015,
        decision Q31) is listed with its error and the import goes on; any other error, such as a copy the workspace
        refuses or the database, stops it at that file. `progress(done, total)` follows each file, and once
        `should_stop()` is true the files not yet imported are left."""
        report = ImportReport()
        for i, f in enumerate(files):
            if should_stop is not None and should_stop():
                report.left = files[i:]
                break
            try:
                if f.label is None:
                    raise AoiError("AOI-TRN-016", path=f.path)
                if not self.import_samples(board_model, [f.path], f.label, f.defect_type, f.side):
                    raise AoiError("AOI-TRN-015", path=f.path, board_model=board_model)
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
        board_model: str,
        epochs: int | None = None,
        image_size: int | None = None,
        progress: anomaly.ProgressFn | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Train an AI model of `board_model` on its samples, then save, register, activate and audit it. The run reads
        the device once, before it loads anything, and keeps it to the end: a device saved on Settings while the run
        loads, aligns or trains applies from the next run (#201)."""
        device = self.device  # not self.device later: save_settings may change it while the samples load and align
        say = progress or (lambda *a: None)
        ok = [self.load_image(s["path"]) for s in self.db.samples(board_model, "OK")]
        ng = [self.load_image(s["path"]) for s in self.db.samples(board_model, "NG")]
        if len(ok) < 2:
            raise AoiError("AOI-TRN-002", found=len(ok))
        # Register every sample onto one board, then learn a golden template as the
        # per-pixel median of good boards: less noise than any single photo.
        ref_path = self.db.reference(board_model)
        anchor = self.load_image(ref_path) if ref_path and Path(ref_path).exists() else ok[0]
        say(0, 1, 0.0, ALIGNING.fill(count=len(ok) + len(ng)))
        ok = [align_to_reference(im, anchor)[0] for im in ok]
        ng = [align_to_reference(im, anchor)[0] for im in ng]
        golden = np.median(np.stack(ok), axis=0).astype(np.uint8)
        cfg = anomaly.TrainConfig(
            image_size=image_size or self.settings.image_size,
            epochs=epochs or self.settings.default_epochs,
            device=device,
        )
        model = anomaly.train(ok, ng, cfg, progress, should_stop)
        if should_stop is not None and should_stop():  # Stop, or the window closing: the active model stays (TRN-008)
            raise JobCancelled(f"training {board_model}")  # nothing saved, registered, activated or audited (#171)
        previous = self.db.active_model(board_model)
        out = self.settings.models_dir / board_model
        out.mkdir(parents=True, exist_ok=True)

        def files(v: str) -> list[Path]:
            return [out / f"{board_model}_{v}.pt", out / f"{board_model}_{v}_golden.png"]

        # never a name whose file is on disk: a result may name a Golden board that a run left unregistered (#178)
        version = self.db.next_model_version(board_model, lambda v: any(f.exists() for f in files(v)))
        path, golden_path = files(version)
        model_uuid = new_uuid()  # in the file's metadata and in the registry row, so an exported .pt names its record
        model.meta.update(board_model=board_model, version=version, uuid=model_uuid, created_at=now_utc())
        try:
            model.save(path)
            save_image(golden_path, golden)
            model.meta["golden_image"] = to_stored(golden_path, self.settings.root)
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
        itself."""
        return load_image(path, self.settings.max_image_megapixels, self.settings.max_image_megabytes)

    def _load_image_sha256(self, path: str | Path) -> tuple[np.ndarray, str]:
        return load_image_sha256(path, self.settings.max_image_megapixels, self.settings.max_image_megabytes)

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
        """Training samples (id, label, defect_type, side, path, added_at), oldest first; `label` filters OK or NG."""
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
        self._refuse_case_variant(name)
        self.db.ensure_board_model(name)
        self.audit("board_model.create", "board_model", name, None, {"name": name})
        self._ensure_recipe(name)

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
        (AOI-TRN-006)."""
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
        """Relabel a sample OK or NG and set its defect type. The reference sample cannot be relabelled NG
        (AOI-TRN-007): inspections would compare against a defective board."""
        before = self.db.sample(sample_id)
        if label != "OK":
            self._refuse_reference_change(before, QT_TRANSLATE_NOOP("Errors", "relabelled NG"))
        self.db.update_sample(sample_id, label, defect_type)
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
