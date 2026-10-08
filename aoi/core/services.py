"""Application services: the only layer the UI calls.

Keeps the Qt pages thin and lets the same workflows run headless (tests, CLI,
and later a Stage 3 robot cycle or Stage 4 MES hook).
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from .. import logging_setup
from ..config import Settings, resolve_device
from ..data import atomic
from ..data.db import Database
from ..data.paths import to_stored
from ..data.times import local_date, now_utc
from ..errors import AoiError
from . import anomaly
from .imaging import align_to_reference, list_images, load_image, save_image
from .inspector import NG, OK, WARN, InspectionResult, Inspector, draw_overlay
from .recipe import Recipe


class AppContext:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.load()
        self.settings.ensure_dirs()
        self.log = logging_setup.setup(self.settings.root)
        self.db = Database(self.settings.db_path, self.settings.root)
        swept = atomic.sweep_temp_files(self.settings.root)  # a crash mid-write leaves only a temp file; drop it
        self.device = resolve_device(self.settings.device)
        self.log.info("app.start", extra={"workspace": str(self.settings.root), "device": self.device, "swept": swept})
        self.user = "operator"
        self.role = "Operator"
        self._model_cache: dict[str, tuple[str, anomaly.AnomalyModel]] = {}

    # --- dataset -------------------------------------------------------------

    def close(self) -> None:
        """Release the database and the log file, as a restart or a change of workspace does; a workspace folder
        can be moved only once nothing holds a file in it open."""
        self.db.close()
        logging_setup.close(self.log)

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
        return n

    # --- training ------------------------------------------------------------
    def train(
        self,
        board_model: str,
        epochs: int | None = None,
        image_size: int | None = None,
        progress: anomaly.ProgressFn | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        say = progress or (lambda *a: None)
        ok = [load_image(s["path"]) for s in self.db.samples(board_model, "OK")]
        ng = [load_image(s["path"]) for s in self.db.samples(board_model, "NG")]
        if len(ok) < 2:
            raise AoiError("AOI-TRN-002", found=len(ok))
        # Register every sample onto one board, then learn a golden template as the
        # per-pixel median of good boards: less noise than any single photo.
        ref_path = self.db.reference(board_model)
        anchor = load_image(ref_path) if ref_path and Path(ref_path).exists() else ok[0]
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
        self.db.register_model(board_model, version, str(path), summary, activate=True)
        self._model_cache.pop(board_model, None)
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
        return self.db.add_audit(
            self.db.user_uuid(self.user), self.role, action, object_type, object_uuid, before, after, reason
        )

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
    def inspector(self, board_model: str, recipe: Recipe | None = None, side: str = "Top") -> Inspector:
        rev, rcp = self.recipe(board_model)
        mv = self.load_model(board_model)
        ref_path = self.db.reference(board_model)
        ref = load_image(ref_path) if ref_path and Path(ref_path).exists() else None
        insp = Inspector(recipe or rcp, mv[1] if mv else None, ref, side)
        insp.model_version = mv[0] if mv else None  # type: ignore[attr-defined]
        insp.recipe_rev = rev  # type: ignore[attr-defined]
        return insp

    def inspect_file(
        self, board_model: str, path: str, inspector: Inspector | None = None, save: bool = True
    ) -> InspectionResult:
        insp = inspector or self.inspector(board_model)
        res = insp.inspect(load_image(path))
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
                "model_version": getattr(insp, "model_version", None),
                "recipe_rev": getattr(insp, "recipe_rev", None),
                "image_path": path,
                "overlay_path": str(overlay),
                "result": res.verdict,
                "score": res.score,
                "metrics": res.metrics_dict(),
                "operator": self.user,
            },
            [d.as_row() for d in res.defects],
        )
        if res.verdict == NG:
            self.db.alarm("NG", f"{Path(path).name}: {len(res.defects)} defect(s)")
        self.log.info(
            "inspection.saved",
            extra={
                "inspection_id": iid,
                "board_model": board_model,
                "verdict": res.verdict,
                "defects": len(res.defects),
                "model_version": getattr(insp, "model_version", None),
                "recipe_rev": getattr(insp, "recipe_rev", None),
                "elapsed_ms": round(res.elapsed_ms, 1),
            },
        )
        return iid

    # --- batch test (AI Model Test screen) -----------------------------------
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
            res = insp.inspect(load_image(f))
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
        self.db.add_test_run(board_model, getattr(insp, "model_version", None) or "-", folder, metrics, rows)
        return metrics, rows


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
