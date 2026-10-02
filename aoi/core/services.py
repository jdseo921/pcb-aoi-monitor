"""Application services: the only layer the UI calls.

Keeps the Qt pages thin and lets the same workflows run headless (tests, CLI,
and later a Stage 3 robot cycle or Stage 4 MES hook).
"""

from __future__ import annotations

import csv
import functools
import io
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, TypeVar, cast

import numpy as np

from .. import logging_setup
from ..config import Settings, resolve_device
from ..data import atomic
from ..data.db import Database
from ..data.paths import to_stored
from ..errors import AoiError
from ..times import local_date, now_utc
from . import anomaly
from .imaging import align_to_reference, list_images, load_image, save_image
from .inspector import NG, OK, WARN, InspectionResult, Inspector, draw_overlay
from .jobs import Jobs
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
    recipe_revision: int  # 0 while the defaults are in use
    last_test: dict[str, Any] | None  # metrics of the latest AI model test run
    inspected: int
    ng: int


ROLES = ("Operator", "Engineer", "Admin")  # lowest to highest (GUI §8, docs/ARCHITECTURE.md §5)
REQUIRED_ROLE: dict[str, str] = {}  # AppContext write -> the lowest role allowed to call it
P = ParamSpec("P")
R = TypeVar("R")


def requires(
    role: str, what: str
) -> Callable[[Callable[Concatenate[AppContext, P], R]], Callable[Concatenate[AppContext, P], R]]:
    """The one role check for every write (ADR 0002, decision 5): refuse with AOI-USR-001 when the current role is
    below `role`. `what` names the action in the message: "Saving a recipe needs the Engineer or Admin role."."""

    def wrap(fn: Callable[Concatenate[AppContext, P], R]) -> Callable[Concatenate[AppContext, P], R]:
        REQUIRED_ROLE[fn.__name__] = role

        @functools.wraps(fn)
        def checked(self: AppContext, *args: P.args, **kwargs: P.kwargs) -> R:
            if self.role not in ROLES or ROLES.index(self.role) < ROLES.index(role):
                raise AoiError("AOI-USR-001", what=what, roles=" or ".join(ROLES[ROLES.index(role) :]))
            return fn(self, *args, **kwargs)

        return cast("Callable[Concatenate[AppContext, P], R]", checked)

    return wrap


class AppContext:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.load()
        self.settings.ensure_dirs()
        self.log = logging_setup.setup(self.settings.root)
        self.db = Database(self.settings.db_path, self.settings.root)
        swept = atomic.sweep_temp_files(self.settings.root)  # a crash mid-write leaves only a temp file; drop it
        self.device = resolve_device(self.settings.device)
        self.log.info("app.start", extra={"workspace": str(self.settings.root), "device": self.device, "swept": swept})
        self.user, self.role, self.user_uuid = "operator", "Operator", self.db.user_uuid("operator")
        archived = self.db.archive_old(self.settings.log_retention_days)  # retention is a system action, not a user's
        self.log.info("retention.archived", extra={"days": self.settings.log_retention_days, "archived": archived})
        self._model_cache: dict[str, tuple[str, anomaly.AnomalyModel]] = {}
        self.jobs = Jobs()  # background work (REQ-SET-021): screens submit through aoi/ui/workers, tests directly

    # --- dataset -------------------------------------------------------------

    def close(self) -> None:
        """Release the database and the log file, as a restart or a change of workspace does; a workspace folder
        can be moved only once nothing holds a file in it open."""
        self.jobs.shutdown()  # a running job may still read the database or write a file
        self.db.close()
        logging_setup.close(self.log)

    def set_user(self, name: str, role: str) -> None:
        """Make `name` with `role` the current user; the UUID comes from the users table. G1 keeps v0.1's user picker
        (ADR 0002), so this records who was picked, not who proved it."""
        self.user, self.role, self.user_uuid = name, role, self.db.user_uuid(name)

    @requires("Engineer", "Importing samples")
    def import_samples(
        self, board_model: str, paths: list[str], label: str, defect_type: str | None = None, side: str = "Top"
    ) -> int:
        """Copy uploads into the workspace so training data survives the source folder moving."""
        dest = self.settings.images_dir / board_model / label
        dest.mkdir(parents=True, exist_ok=True)
        n = 0
        for p in paths:
            src = Path(p)
            target = dest / f"{src.stem}_{uuid.uuid4().hex[:6]}{src.suffix.lower()}"
            atomic.copy_file(src, target)
            self.db.add_sample(board_model, str(target), label, defect_type, side)
            n += 1
        if not self.db.reference(board_model):
            oks = self.db.samples(board_model, "OK")
            if oks:
                self.db.set_reference(board_model, oks[0]["path"])
        after = {"label": label, "defect_type": defect_type, "side": side, "added": n}
        self.audit("sample.import", "board_model", board_model, None, after)
        return n

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
        previous = self.db.active_model(board_model)
        version = self.db.next_model_version(board_model)
        model.meta.update(board_model=board_model, version=version, created_at=now_utc())
        out = self.settings.models_dir / board_model
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{board_model}_{version}.pt"
        model.save(path)
        golden_path = out / f"{board_model}_{version}_golden.png"
        save_image(golden_path, golden)
        self.db.set_reference(board_model, str(golden_path))
        model.meta["golden_image"] = to_stored(golden_path, self.settings.root)
        summary = {k: v for k, v in model.meta.items() if k not in ("loss_history", "err_mean", "err_std")}
        model_id = self.db.register_model(board_model, version, str(path), summary, activate=True)
        self._model_cache.pop(board_model, None)
        self.audit(
            "model.train",
            "model",
            self.db.model(model_id)["uuid"],
            {"active_version": previous["version"] if previous else None},
            {"version": version, "metrics": summary},
        )
        self.log.info("training.finished", extra={"board_model": board_model, "model_version": version})
        return model.meta

    def load_model(self, board_model: str) -> tuple[str, anomaly.AnomalyModel] | None:
        rec = self.db.active_model(board_model)
        if not rec:
            return None
        cached = self._model_cache.get(board_model)
        if cached and cached[0] == rec["version"]:
            return cached
        m = anomaly.AnomalyModel.load(rec["path"], self.device)
        self._model_cache[board_model] = (rec["version"], m)
        return self._model_cache[board_model]

    # --- recipe --------------------------------------------------------------
    def recipe(self, board_model: str) -> tuple[int, Recipe]:
        latest = self.db.latest_recipe(board_model)
        if latest:
            return latest[0], Recipe.from_dict(latest[1])
        return 0, Recipe(board_model=board_model)

    @requires("Engineer", "Saving a recipe")
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
        """Append an audit entry as the current user: who did `action` to which object, with the object before and
        after, and why. Returns the entry's UUID. Entries can never be changed or removed (migration 0003)."""
        return self.db.add_audit(self.user_uuid, self.role, action, object_type, object_uuid, before, after, reason)

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

    def inspector(
        self, board_model: str, recipe: Recipe | None = None, side: str = "Top", reference: np.ndarray | None = None
    ) -> Inspector:
        """The engine for a board model: its latest recipe (or `recipe`), its active AI model and its reference image
        (or `reference`, such as another stored OK board on the Compare page). Screens never build an Inspector."""
        rev, rcp = self.recipe(board_model)
        mv = self.load_model(board_model)
        if reference is None:
            ref_path = self.db.reference(board_model)
            reference = self.load_image(ref_path) if ref_path and Path(ref_path).exists() else None
        return Inspector(recipe or rcp, mv[1] if mv else None, reference, side, mv[0] if mv else None, rev)

    def inspect(
        self,
        board_model: str,
        image: np.ndarray,
        recipe: Recipe | None = None,
        side: str = "Top",
        reference: np.ndarray | None = None,
    ) -> InspectionResult:
        """Inspect one image in memory without saving a record (the Compare page; re-evaluation without re-running the
        AI model arrives in S28)."""
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
        """Auto-save after each board (spec 4.1): overlay PNG + DB row."""
        day = local_date()  # the folder is named for the operator's shift date; the stored time is UTC
        overlay = self.settings.results_dir / day / f"{Path(path).stem}_{uuid.uuid4().hex[:6]}_{res.verdict}.png"
        save_image(overlay, draw_overlay(res))
        iid = self.db.add_inspection(
            {
                "board_model": board_model,
                "model_version": insp.model_version,
                "recipe_rev": insp.recipe_rev,
                "image_path": path,
                "overlay_path": str(overlay),
                "view": res.view,
                "result": res.verdict,
                "score": res.score,
                "metrics": res.metrics_dict(),
                "operator": self.user,
            },
            [d.as_row() for d in res.defects],
        )
        if res.verdict == NG:
            self.alarm("NG", f"{Path(path).name}: {len(res.defects)} defect(s)", "AOI-INSP-003")
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
        AOI-SET-007 (unexpected error); its text stays in the log."""
        report = ErrorReport.of(exc, context)
        self.log.error(
            "error.shown",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"code": report.code, "context": context, "detail": getattr(exc, "detail", None) or str(exc)},
        )
        self.alarm("ERROR", report.what, report.code)
        return report

    # --- batch test (AI Model Test screen) -----------------------------------
    @requires("Engineer", "Running an AI model test")
    def batch_test(
        self, board_model: str, folder: str, progress: Callable[[int, int], None] | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Ground truth comes from sub-folder names: anything under an `ng`/`defect`
        folder is NG, under `ok`/`good` is OK."""
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
        self.db.add_test_run(board_model, model_version, folder, metrics, rows)
        after = {"folder": folder, "model_version": model_version, **metrics}
        self.audit("test.run", "board_model", board_model, None, after)
        return metrics, rows

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
        """Recipe revisions (revision, user, created_at), newest first."""
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

    def users(self) -> list[dict[str, Any]]:
        """Users (uuid, name, role), oldest first."""
        return self.db.users()

    def board_status(self, board_model: str) -> BoardStatus:
        """Sample counts, active model, recipe revision, last test metrics and inspection counts of a board model."""
        model = self.db.active_model(board_model)
        latest = self.db.latest_recipe(board_model)
        run = self.db.latest_test_run(board_model)
        inspected, ng = self.db.inspection_counts(board_model)
        return BoardStatus(
            ok_samples=len(self.db.samples(board_model, "OK")),
            ng_samples=len(self.db.samples(board_model, "NG")),
            model_version=model["version"] if model else None,
            recipe_revision=latest[0] if latest else 0,
            last_test=json.loads(run["metrics"]) if run else None,
            inspected=inspected,
            ng=ng,
        )

    # --- what the screens change: each checks the role and appends an audit entry (REQ-USR-001, REQ-LOG-004) ---
    @requires("Engineer", "Creating a board model")
    def ensure_board_model(self, name: str) -> None:
        """Create a board model unless it exists."""
        if name in self.db.board_models():
            return
        self.db.ensure_board_model(name)
        self.audit("board_model.create", "board_model", name, None, {"name": name})

    @requires("Engineer", "Changing the reference image")
    def set_reference(self, board_model: str, sample_id: int) -> None:
        """Make a stored sample the reference image; the next training run learns the golden template from it."""
        before, path = self.db.reference(board_model), self.sample_path(sample_id)
        self.db.set_reference(board_model, path)
        root = self.settings.root
        old = {"reference": to_stored(Path(before), root) if before else None}
        self.audit("board_model.reference", "board_model", board_model, old, {"reference": to_stored(Path(path), root)})

    @requires("Engineer", "Relabelling a sample")
    def update_sample(self, sample_id: int, label: str, defect_type: str | None) -> None:
        """Relabel a sample OK or NG and set its defect type."""
        before = self.db.sample(sample_id)
        self.db.update_sample(sample_id, label, defect_type)
        old = {"label": before["label"], "defect_type": before["defect_type"]}
        self.audit("sample.update", "sample", before["uuid"], old, {"label": label, "defect_type": defect_type})

    @requires("Engineer", "Removing a sample")
    def delete_sample(self, sample_id: int) -> None:
        """Remove a sample's record; its image file stays in the workspace."""
        before = self.db.sample(sample_id)
        self.db.delete_sample(sample_id)
        old = {"label": before["label"], "path": to_stored(Path(before["path"]), self.settings.root)}
        self.audit("sample.delete", "sample", before["uuid"], old, None)

    @requires("Engineer", "Activating a model version")
    def activate_model(self, model_id: int) -> None:
        """Make a model version the one inspections use (an older version: a rollback)."""
        target = self.db.model(model_id)
        previous = self.db.active_model(target["board_model"])
        self.db.activate_model(model_id)
        old = {"active_version": previous["version"] if previous else None}
        self.audit("model.activate", "model", target["uuid"], old, {"active_version": target["version"]})

    @requires("Admin", "Changing users")
    def add_user(self, name: str, role: str) -> None:
        """Add a user, or change the role of an existing one."""
        before = next((u for u in self.db.users() if u["name"] == name), None)
        self.db.add_user(name, role)
        old = {"role": before["role"]} if before else None
        self.audit("user.change", "user", self.db.user_uuid(name), old, {"name": name, "role": role})

    @requires("Engineer", "Archiving records")
    def archive_old(self, days: int | None = None) -> int:
        """Archive inspections older than `days` (default: the retention setting); returns how many were archived."""
        days = self.settings.log_retention_days if days is None else days
        n = self.db.archive_old(days)
        self.audit("inspection.archive", "inspections", None, None, {"days": days, "archived": n})
        return n

    @requires("Engineer", "Exporting a model")
    def export_model(self, model_id: int, dest: str | Path) -> Path:
        """Copy a model version's file to `dest`, whole or not at all."""
        model = self.model(model_id)
        atomic.copy_file(model["path"], dest)
        self.audit("export.model", "model", model["uuid"], None, {"version": model["version"], "dest": str(dest)})
        return Path(dest)

    @requires("Engineer", "Exporting overlay images")
    def export_overlays(self, inspections: list[dict[str, Any]], folder: str | Path) -> int:
        """Copy the overlay images of `inspections` (records from `inspections()`) into `folder`; returns how many."""
        n = 0
        for r in inspections:
            if r.get("overlay_path") and Path(r["overlay_path"]).exists():
                atomic.copy_file(r["overlay_path"], Path(folder) / Path(r["overlay_path"]).name)
                n += 1
        after = {"folder": str(folder), "records": len(inspections), "copied": n}
        self.audit("export.overlays", "inspections", None, None, after)
        return n

    @requires("Engineer", "Exporting CSV")
    def export_csv(self, path: str | Path, rows: list[dict[str, Any]], what: str = "inspections") -> int:
        """Write `rows` as CSV to `path`, whole or not at all, and audit the export; returns the row count."""
        export_csv(path, rows)
        self.audit("export.csv", what, None, None, {"path": str(path), "rows": len(rows)})
        return len(rows)


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


def export_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    buf = io.StringIO(newline="")
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    atomic.write_text(path, buf.getvalue(), encoding="utf-8-sig" if rows else "utf-8")  # BOM: Excel opens Korean
