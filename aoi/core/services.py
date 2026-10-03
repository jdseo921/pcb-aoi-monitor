"""Application services: the only layer the UI calls.

Keeps the Qt pages thin and lets the same workflows run headless (tests, CLI,
and later a Stage 3 robot cycle or Stage 4 MES hook).
"""

from __future__ import annotations

import contextlib
import contextvars
import csv
import functools
import io
import json
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Concatenate, Literal, ParamSpec, TypeVar, cast

import numpy as np

from .. import logging_setup
from ..config import Settings, resolve_device
from ..data import atomic
from ..data.db import Database, DbError, new_uuid
from ..data.errors import WorkspaceError
from ..data.paths import to_stored
from ..errors import AoiError
from ..times import local_date, now_utc
from . import anomaly
from .imaging import align_to_reference, list_images, load_image, load_image_sha256, save_image
from .inspector import NG, OK, WARN, AiEvidence, InspectionResult, Inspector, draw_overlay, re_grade
from .jobs import JobCancelled, Jobs
from .maps import load_maps, save_maps
from .recipe import Recipe

ALARM_LIMIT = 1000  # REQ-INSP-006: the alarms a screen shows and that survive a restart


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
        if not isinstance(exc, AoiError):
            exc = AoiError("AOI-SET-007", error_type=type(exc).__name__, context=f" ({context})" if context else "")
        return cls(exc.code, exc.entry.title, exc.what, exc.action)


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
REQUIRED_ROLE: dict[str, str] = {}  # AppContext write, or Engineer-only call -> the lowest role allowed to call it
P = ParamSpec("P")
R = TypeVar("R")
# A stored result's golden board, as `judged_reference` finds it.
Judged = Literal["same", "none", "unrecorded", "missing", "unreadable", "changed"]


def requires(
    role: str, what: str
) -> Callable[[Callable[Concatenate[AppContext, P], R]], Callable[Concatenate[AppContext, P], R]]:
    """The one role check for every write, and for what only an Engineer does without writing (re-evaluating a result
    with other thresholds, REQ-CMP-005) (ADR 0002, decision 5): refuse with AOI-USR-001 when the current role is below
    `role`. `what` names the action in the message: "Saving a recipe needs the Engineer or Admin role.".
    The user checked is the one acting (`AppContext.actor`), and the call, with every audit entry and record it writes,
    acts as that user to its end, whoever signs in meanwhile (#177)."""

    def wrap(fn: Callable[Concatenate[AppContext, P], R]) -> Callable[Concatenate[AppContext, P], R]:
        REQUIRED_ROLE[fn.__name__] = role

        @functools.wraps(fn)
        def checked(self: AppContext, *args: P.args, **kwargs: P.kwargs) -> R:
            actor = self.actor
            if actor.role not in ROLES or ROLES.index(actor.role) < ROLES.index(role):
                raise AoiError("AOI-USR-001", what=what, roles=" or ".join(ROLES[ROLES.index(role) :]))
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
        self.log = logging_setup.setup(self.settings.root)
        try:
            self.db = Database(self.settings.db_path, self.settings.root)
        except BaseException:
            logging_setup.close(self.log)  # nor is the refused workspace's log file (REQ-SET-016)
            raise
        swept = atomic.sweep_temp_files(self.settings.root)  # a crash mid-write leaves only a temp file; drop it
        self.device = resolve_device(self.settings.device)
        self.log.info("app.start", extra={"workspace": str(self.settings.root), "device": self.device, "swept": swept})
        try:  # the first writes: another program may hold the database, or the drive refuse them (#171)
            self._actor = Actor("operator", "Operator", self.db.user_uuid("operator"))
            archived = self.db.archive_old(self.settings.log_retention_days)  # retention is a system action
            self.log.info("retention.archived", extra={"days": self.settings.log_retention_days, "archived": archived})
            self._sweep_ok_maps()  # the map files of OK results past their retention go too (REQ-INSP-012, S25c)
            for board_model in self.db.board_models():
                self._ensure_recipe(board_model)  # a workspace from before S25: its results name a stored revision too
        except BaseException as e:
            self.db.close()  # a refused workspace holds no file open while another folder is chosen (REQ-SET-016)
            logging_setup.close(self.log)
            if isinstance(e, DbError):  # a coded refusal the folder picker follows, not AOI-SET-007
                raise self.db.refusal(e) from e
            raise
        self._model_cache: dict[str, tuple[str, anomaly.AnomalyModel, str]] = {}
        # background work (REQ-SET-021): screens submit through aoi/ui/workers, tests directly; a job acts as the user
        # who submitted it (#177)
        self.jobs = Jobs(context=self._acting_context)
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

    def set_user(self, name: str, role: str) -> None:
        """Make `name` with `role` the current user; the UUID comes from the users table. G1 keeps v0.1's user picker
        (ADR 0002), so this records who was picked, not who proved it. A job already submitted, and a role-checked call
        already running, go on as the user who started them (#177)."""
        self._actor = Actor(name, role, self.db.user_uuid(name))

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

    @requires("Engineer", "Importing samples")
    def import_samples(
        self, board_model: str, paths: list[str], label: str, defect_type: str | None = None, side: str = "Top"
    ) -> int:
        """Copy uploads into the workspace so training data survives the source folder moving. All or nothing (#178):
        a file that cannot be copied stops the import with AOI-TRN-008 and removes the copies made; then the samples, a
        new board model's default recipe and reference, and the audit entry commit together."""
        self._refuse_case_variant(board_model)  # a new board model is created by its first import
        dest = self.settings.images_dir / board_model / label
        copies: list[Path] = []
        try:
            for p in paths:
                src = Path(p)
                target = dest / f"{src.stem}_{uuid.uuid4().hex[:6]}{src.suffix.lower()}"
                try:
                    atomic.copy_file(src, target)
                except OSError as e:  # gone, unreadable, or the workspace drive full
                    why = e.strerror or str(e)
                    raise AoiError("AOI-TRN-008", str(e), path=str(src), reason=why, count=len(paths)) from e
                copies.append(target)
            with self.db.transaction():
                for target in copies:
                    self.db.add_sample(board_model, str(target), label, defect_type, side)  # creates a new board model
                if copies:
                    self._ensure_recipe(board_model)
                if not self.db.reference(board_model):
                    oks = self.db.samples(board_model, "OK")
                    if oks:
                        self.db.set_reference(board_model, oks[0]["path"])
                after = {"label": label, "defect_type": defect_type, "side": side, "added": len(copies)}
                self.audit("sample.import", "board_model", board_model, None, after)
        except BaseException:
            _remove(copies)
            raise
        return len(copies)

    # --- training ------------------------------------------------------------
    @requires("Engineer", "Training a model")
    def train(
        self,
        board_model: str,
        epochs: int | None = None,
        image_size: int | None = None,
        progress: anomaly.ProgressFn | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        say = progress or (lambda *a: None)
        ok = [self.load_image(s["path"]) for s in self.db.samples(board_model, "OK")]
        ng = [self.load_image(s["path"]) for s in self.db.samples(board_model, "NG")]
        if len(ok) < 2:
            raise AoiError("AOI-TRN-002", found=len(ok))
        # Register every sample onto one board, then learn a golden template as the
        # per-pixel median of good boards: less noise than any single photo.
        ref_path = self.db.reference(board_model)
        anchor = self.load_image(ref_path) if ref_path and Path(ref_path).exists() else ok[0]
        say(0, 1, 0.0, f"Aligning {len(ok) + len(ng)} images to the reference board")
        ok = [align_to_reference(im, anchor)[0] for im in ok]
        ng = [align_to_reference(im, anchor)[0] for im in ng]
        golden = np.median(np.stack(ok), axis=0).astype(np.uint8)
        cfg = anomaly.TrainConfig(
            image_size=image_size or self.settings.image_size,
            epochs=epochs or self.settings.default_epochs,
            device=self.device,
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
        one version's UUID with another's weights; the weights are cached by version."""
        rec = self.db.active_model(board_model)
        if not rec:
            return None
        cached = self._model_cache.get(board_model)
        if cached and cached[0] == rec["version"]:
            return cached
        m = anomaly.AnomalyModel.load(rec["path"], self.device)
        if m.meta.get("uuid") != rec["uuid"]:  # another AI model's file in its place, such as one written over it
            why = f"its UUID {m.meta.get('uuid') or '(none)'} is not {rec['uuid']}, the one the model registry names"
            raise anomaly.ModelFileError("AOI-TRN-001", path=rec["path"], reason=why)
        self._model_cache[board_model] = (rec["version"], m, str(rec["uuid"]))
        return self._model_cache[board_model]

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

    @requires("Engineer", "Saving a recipe")
    @transactional
    def save_recipe(self, recipe: Recipe, reason: str | None = None) -> int:
        """Store the next recipe revision and audit it with the revision before (a recipe decides verdicts)."""
        latest = self.db.latest_recipe(recipe.board_model)
        rev, uid = self.db.save_recipe(recipe.board_model, recipe.to_dict(), self.user)
        self.audit("recipe.save", "recipe", uid, latest[1] if latest else None, recipe.to_dict(), reason)
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
        """Read audit entries, newest first, filtered by object type, object UUID, action and a UTC time floor."""
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
        The engine names the model version and recipe revision it applies, with their UUIDs, for the records it
        produces (REQ-INSP-012); a `recipe` that differs from the stored revision names none. Likewise the golden board
        file it read, with the SHA-256 of its bytes (REQ-CMP-003); a `reference` passed in names none. AOI-INSP-009 when
        the database names a golden board whose file is gone or cannot be read: a board is never judged as if none
        were set (#169)."""
        latest = self.db.latest_recipe(board_model)
        rev: int | None
        rev, rcp, recipe_uuid = (latest[0], Recipe.from_dict(latest[1]), latest[2]) if latest else (0, None, None)
        rcp = rcp or Recipe(board_model=board_model)
        if recipe is not None and recipe.to_dict() != rcp.to_dict():
            rev, recipe_uuid = None, None  # an unsaved recipe (the Compare page's what-if thresholds) has no revision
        mv = self.load_model(board_model)
        golden = self.db.reference(board_model) if reference is None else None
        sha: str | None = None
        if golden:
            try:
                reference, sha = self._load_image_sha256(golden)  # one read: the bytes hashed are the bytes judged
            except AoiError as e:  # the comparison and the alignment the AI model was trained on would silently go
                why = f"it cannot be read ({e.code} {e.entry.title})" if Path(golden).exists() else "the file is gone"
                raise AoiError("AOI-INSP-009", detail=str(e), board=board_model, file=golden, reason=why) from e
        model, version, model_uuid = (mv[1], mv[0], mv[2]) if mv else (None, None, None)
        return Inspector(recipe or rcp, model, reference, side, version, rev, model_uuid, recipe_uuid, golden, sha)

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
        (REQ-INSP-006), naming the AI model version and recipe revision that decided it (REQ-INSP-012) and the golden
        board it was judged against (REQ-CMP-003). Called on the pool thread by the Inspection page."""
        day = local_date()  # the folder is named for the operator's shift date; the stored time is UTC
        overlay = self.settings.results_dir / day / f"{Path(path).stem}_{uuid.uuid4().hex[:6]}_{res.verdict}.png"
        save_image(overlay, draw_overlay(res))
        pixel_threshold = insp.model.pixel_threshold if insp.model is not None else None  # the AI map's, kept (S28a)
        diff_map_path, ai_map_path = save_maps(res, overlay.with_suffix(""), pixel_threshold=pixel_threshold)
        doc = res.to_dict()
        ng = res.verdict == NG
        alarm = ("NG", f"{Path(path).name}: {len(res.defects)} defect(s)", "AOI-INSP-003") if ng else None
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
        )
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
    def alarm(self, level: str, message: str, code: str | None = None) -> None:
        """Store an alarm (NG, WARN or ERROR) with its code; it survives a restart and reaches the log."""
        self.db.alarm(level, message, code)
        self.log.info("alarm", extra={"alarm_level": level, "code": code, "text": message})

    def alarms(self, limit: int = ALARM_LIMIT) -> list[dict[str, Any]]:
        """The newest alarms first: time (UTC), level, code and message."""
        return self.db.alarms(limit)

    def report_error(self, exc: BaseException, context: str = "") -> ErrorReport:
        """The one handler for an error a user will see: log it with the build version and the stack trace,
        store an alarm with its code, and return the plain report the dialog shows. A plain exception becomes
        AOI-SET-007 (unexpected error); its text stays in the log. It never raises (an alarm refused is logged)."""
        report = ErrorReport.of(exc, context)
        self.log.error(
            "error.shown",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"code": report.code, "context": context, "detail": getattr(exc, "detail", None) or str(exc)},
        )
        try:
            self.alarm("ERROR", report.what, report.code)
        except Exception:  # #171: the report, and so the coded dialog, must not depend on the database
            self.log.warning("alarm.not_stored", exc_info=True, extra={"code": report.code})
        return report

    # --- batch test (AI Model Test screen) -----------------------------------
    @requires("Engineer", "Running an AI model test")
    def batch_test(
        self, board_model: str, folder: str, progress: Callable[[int, int], None] | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Validate the active AI model on a folder and store the run: (metrics, rows), one row per image. Ground truth
        comes from sub-folder names: anything under an `ng`/`defect` folder is NG, under `ok`/`good` is OK. Each row
        ends with the run's UUID, the AI model version and its UUID (run_uuid, model_version, model_uuid; None without
        an AI model), as the CSV export writes them (REQ-SET-017)."""
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
                    "pass_fail": "PASS" if gt is None or gt == pred else "FAIL",
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
        return metrics, [{**r, **ids} for r in rows]

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
        (REQ-INSP-012), and AOI-CMP-003 for one there that cannot be read. None for a record from before migration
        0006."""
        doc = self.db.inspection_result(inspection_id)
        res = InspectionResult.from_dict(doc) if doc is not None else None
        return load_maps(res, *self.db.map_paths(inspection_id)) if res is not None and with_maps else res

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

    @requires("Engineer", "Re-evaluating a result")
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
        uses was judged on is gone; and AOI-INSP-010 when `thresholds` leave no check that ran on the board."""
        iid = self.db.inspection_id(result_uuid)
        rec = self.db.inspection(iid) if iid is not None else None
        res = self.inspection_result(iid) if iid is not None else None
        file = Path(rec["image_path"]).name if rec and rec["image_path"] else "file unknown"
        if rec is None or res is None or iid is None:
            raise AoiError("AOI-CMP-002", id=result_uuid, file=file)
        if thresholds.board_model != rec["board_model"]:
            raise AoiError("AOI-CMP-005", tried=thresholds.board_model, file=file, judged=rec["board_model"])
        diff_path, ai_path = self.db.map_paths(iid)
        load_maps(res, diff_path if thresholds.use_compare else None, ai_path if thresholds.use_ai else None)
        missing: list[str] = []  # only what the thresholds use, as re_grade asks for it
        if thresholds.use_compare and res.compare is not None and res.compare.diff_map is None:
            missing.append("difference map")
        ai, check = None, next((c for c in res.checks if c.source == "AI"), None)
        if thresholds.use_ai and check is not None:
            model = next((m for m in self.db.models(rec["board_model"]) if m["uuid"] == rec["model_uuid"]), None)
            try:  # a registry row this app wrote holds both thresholds, finite and above 0
                cal = json.loads(model["metrics"]) if model else {}
                image_thr, pixel_thr = float(cal["image_threshold"]), float(cal["pixel_threshold"])
            except (ValueError, TypeError, KeyError, OverflowError):
                image_thr = pixel_thr = math.nan
            if min(image_thr, pixel_thr) > 0 and math.isfinite(image_thr + pixel_thr):
                ai = AiEvidence(check.value, image_thr, pixel_thr, check.explain)
            else:
                version = rec["model_version"] or rec["model_uuid"]
                missing.append(f"the calibration of AI model {version}" if version else "the AI model's calibration")
            if res.anomaly_map is None:
                missing.append("AI score map")
        if missing:
            days = self.settings.map_retention_days_ok
            raise AoiError("AOI-CMP-004", file=file, missing=", ".join(missing), days=days)
        return re_grade(res, thresholds, ai)

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
    @requires("Engineer", "Creating a board model")
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

    @requires("Engineer", "Changing the reference image")
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

    @requires("Engineer", "Relabelling a sample")
    @transactional
    def update_sample(self, sample_id: int, label: str, defect_type: str | None) -> None:
        """Relabel a sample OK or NG and set its defect type. The reference sample cannot be relabelled NG
        (AOI-TRN-007): inspections would compare against a defective board."""
        before = self.db.sample(sample_id)
        if label != "OK":
            self._refuse_reference_change(before, "relabelled NG")
        self.db.update_sample(sample_id, label, defect_type)
        old = {"label": before["label"], "defect_type": before["defect_type"]}
        self.audit("sample.update", "sample", before["uuid"], old, {"label": label, "defect_type": defect_type})

    @requires("Engineer", "Removing a sample")
    @transactional
    def delete_sample(self, sample_id: int) -> None:
        """Remove a sample's record; its image file stays in the workspace. The reference sample cannot be removed
        (AOI-TRN-007)."""
        before = self.db.sample(sample_id)
        self._refuse_reference_change(before, "removed")
        self.db.delete_sample(sample_id)
        old = {"label": before["label"], "path": to_stored(Path(before["path"]), self.settings.root)}
        self.audit("sample.delete", "sample", before["uuid"], old, None)

    def _refuse_reference_change(self, sample: dict[str, Any], change: str) -> None:
        """Refuse a change that would leave inspections comparing against a board that is not a good sample (#168):
        the reference an import picked, or one an Engineer set, stays an OK sample until another is set."""
        reference = self.db.reference(sample["board_model"])
        if reference is not None and Path(reference) == Path(sample["path"]):
            raise AoiError("AOI-TRN-007", sample=Path(sample["path"]).name, change=change)

    @requires("Engineer", "Activating a model version")
    @transactional
    def activate_model(self, model_id: int) -> None:
        """Make a model version the one inspections use (an older version: a rollback)."""
        target = self.db.model(model_id)
        previous = self.db.active_model(target["board_model"])
        self.db.activate_model(model_id)
        old = {"active_version": previous["version"] if previous else None}
        self.audit("model.activate", "model", target["uuid"], old, {"active_version": target["version"]})

    @requires("Admin", "Changing users")
    @transactional
    def add_user(self, name: str, role: str) -> None:
        """Add a user, or change the role of an existing one. Taking the Admin role from the last Admin is refused with
        AOI-USR-002 before anything is written or audited: no one could manage users or settings after it (#170)."""
        users = self.db.users()
        if role != "Admin" and [u["name"] for u in users if u["role"] == "Admin"] == [name]:
            raise AoiError("AOI-USR-002", name=name, role=role)
        before = next((u for u in users if u["name"] == name), None)
        self.db.add_user(name, role)
        old = {"role": before["role"]} if before else None
        self.audit("user.change", "user", self.db.user_uuid(name), old, {"name": name, "role": role})

    @requires("Engineer", "Archiving records")
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

    @requires("Engineer", "Exporting a model")
    def export_model(self, model_id: int, dest: str | Path) -> Path:
        """Copy a model version's file to `dest`, whole or not at all."""
        model = self.model(model_id)
        atomic.copy_file(model["path"], dest)
        after = {"version": model["version"], "dest": str(dest)}
        self._audit_files([Path(dest)], "export.model", "model", model["uuid"], after, [Path(model["path"])])
        return Path(dest)

    @requires("Engineer", "Exporting overlay images")
    def export_overlays(self, inspections: list[dict[str, Any]], folder: str | Path) -> int:
        """Copy the overlay images of `inspections` (records from `inspections()`) into `folder`; returns how many. A
        copy that fails stops the export with AOI-LOG-001; the entry names the files that left before it, which stay
        (#178)."""
        sources = [Path(r["overlay_path"]) for r in inspections if r.get("overlay_path")]
        sources = [p for p in sources if p.exists()]
        copied: list[Path] = []
        failed: tuple[Path, OSError] | None = None
        for src in sources:
            try:
                atomic.copy_file(src, Path(folder) / src.name)
            except OSError as e:  # the drive full or pulled out, a name the folder cannot take
                failed = (Path(folder) / src.name, e)
                break
            copied.append(Path(folder) / src.name)
        after: dict[str, Any] = {"folder": str(folder), "records": len(inspections), "copied": len(copied)}
        if failed:
            after["error"] = f"{failed[0].name}: {failed[1].strerror or failed[1]}"
        self._audit_files(copied, "export.overlays", "inspections", None, after, sources)
        if failed:
            params = {"copied": len(copied), "total": len(sources), "folder": str(folder), "file": failed[0].name}
            why = failed[1].strerror or str(failed[1])
            raise AoiError("AOI-LOG-001", str(failed[1]), reason=why, **params) from failed[1]
        return len(copied)

    @requires("Engineer", "Exporting CSV")
    def export_csv(
        self,
        path: str | Path,
        rows: list[dict[str, Any]],
        what: str = "inspections",
        fieldnames: list[str] | None = None,
    ) -> int:
        """Write `rows` as CSV to `path`, whole or not at all, and audit the export; returns the row count. `fieldnames`
        gives the header when `rows` may be empty."""
        export_csv(path, rows, fieldnames)
        self._audit_files([Path(path)], "export.csv", what, None, {"path": str(path), "rows": len(rows)})
        return len(rows)

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
    """`rows` as CSV, UTF-8 with a BOM so Excel opens Korean; the header comes from `fieldnames` or the first row, so a
    file with no rows still names its columns when `fieldnames` is given."""
    buf = io.StringIO(newline="")
    names = fieldnames or (list(rows[0].keys()) if rows else None)
    if names:
        w = csv.DictWriter(buf, fieldnames=names)
        w.writeheader()
        w.writerows(rows)
    atomic.write_text(path, buf.getvalue(), encoding="utf-8-sig" if names else "utf-8")
