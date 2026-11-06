"""The app's Stage 1 path, driven with no screen but AI Model Test's, for tools/proxy_validation.py (#452).

Each run gets a workspace of its own and goes as an engineer would on the Training page and the first-run guide: the
customer's board model (`create_customer_board_model`), the images picked as an ok/ and ng/<type>/ folder with a Pascal
VOC file of boxes beside each NG image (`folder_files`, `import_files`: the boxes go through the annotation import and
its checks), a Validated freeze tried and its refusal kept, a Trial version frozen by one person (ADR 0020), its
validation set locked with --seed, training at the default settings, activation, AI Model Test on the locked set
(`test_dataset`), the shift check, then the held-out boards one by one through `InspectionCycle.run` with result files
on, and on AI Model Test's own page: Validation Report…, Export Report, Export CSV and Export Image Overlays, every
dialog kept with its text. Nothing here is under aoi/, and nothing it writes lies inside the repository.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # AI Model Test's page renders its PDF offscreen

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from aoi import config  # noqa: E402
from aoi.config import Settings  # noqa: E402
from aoi.core.cycle import FrameMeta  # noqa: E402
from aoi.core.imaging import registration  # noqa: E402
from aoi.core.sample_import import folder_files  # noqa: E402
from aoi.core.services import AppContext  # noqa: E402
from aoi.data import credentials  # noqa: E402
from aoi.errors import AoiError  # noqa: E402
from tools.dataset_check import peak_memory_mb  # noqa: E402
from tools.proxy_validation import (  # noqa: E402
    Board,
    change,
    check_result_files,
    found,
    manifest,
    mask_boxes,
    tally,
    timing,
)

CUSTOMER, VIEW, REVISION = "Proxy", "Top", "R1"


def reset_peak() -> None:
    """Start the peak resident memory again where Linux allows it (VmHWM), so a run's peak is its own."""
    try:
        Path("/proc/self/clear_refs").write_text("5")
    except OSError:
        pass


def peak_mb() -> float | None:
    """The peak resident memory since `reset_peak` (VmHWM); where Linux cannot say, the process's whole-life peak."""
    try:
        line = next(x for x in Path("/proc/self/status").read_text().splitlines() if x.startswith("VmHWM"))
        return round(int(line.split()[1]) / 1024, 1)
    except (OSError, StopIteration):
        return peak_memory_mb()


def board_mask(b: Board, shape: tuple[int, int]) -> np.ndarray | None:
    """The board's truth as a mask the size of its image: its mask file, else its boxes filled; None for OK."""
    if b.label == "OK":
        return None
    if b.mask is not None:
        m = (cv2.imread(str(b.mask), cv2.IMREAD_GRAYSCALE) > 0).astype(np.uint8) * 255  # VisA's masks hold 0 and 1
        return cv2.resize(m, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST) if m.shape != shape else m
    if not b.boxes:  # an NG board with no box (the demo's): judged by its verdict alone
        return None
    m = np.zeros(shape, np.uint8)
    for x, y, w, h in b.boxes:
        m[y : y + h, x : x + w] = 255
    return m


def stage(folder: Path, ok: list[Board], ng: list[Board]) -> dict[str, Board]:
    """An ok/ and ng/<type>/ folder of links to the sources, a VOC file of each NG board's boxes beside it, as a user
    lays one out for the guide's Images screen. Returns each link's path to its board."""
    shutil.rmtree(folder, ignore_errors=True)
    links: dict[str, Board] = {}
    for b in ok + ng:
        sub = folder / "ok" if b.label == "OK" else folder / "ng" / str(b.defect_type).replace(" ", "_")
        sub.mkdir(parents=True, exist_ok=True)
        link = sub / f"{b.path.parent.name[0].lower()}{b.path.stem}{b.path.suffix}"
        try:
            link.symlink_to(b.path.resolve())
        except OSError:  # Windows without Developer Mode makes no link: a copy, as the guide's Images screen makes
            shutil.copy2(b.path, link)
        links[str(link)] = b
        if b.label == "NG":
            img = cv2.imread(str(b.path), cv2.IMREAD_UNCHANGED)
            mask = board_mask(b, img.shape[:2])
            assert mask is not None
            objs = "".join(
                f"<object><name>{escape(str(b.defect_type))}</name><bndbox><xmin>{x}</xmin><ymin>{y}</ymin>"
                f"<xmax>{x + w}</xmax><ymax>{y + h}</ymax></bndbox></object>"
                for x, y, w, h in (mask_boxes(mask) or [(0, 0, img.shape[1], img.shape[0])])
            )
            size = f"<size><width>{img.shape[1]}</width><height>{img.shape[0]}</height></size>"
            link.with_suffix(".xml").write_text(f"<annotation>{size}{objs}</annotation>", encoding="utf-8")
    return links


def code_of(e: BaseException) -> dict[str, str]:
    return {"code": getattr(e, "code", type(e).__name__), "text": str(e)[:500]}


class Frames:
    """A FrameSource over boards: each read from its file by the cycle, as the Inspection page reads one, or changed by
    `alter` in memory (set B) and handed over as a frame. `truth` keeps each board's image and mask as given until the
    cycle has judged it, so the tool holds no more than the board in hand."""

    def __init__(self, boards: list[Board], alter: str | None = None) -> None:
        self.todo, self.alter = list(boards), alter
        self.truth: list[tuple[Board, np.ndarray, np.ndarray | None, float]] = []

    def grab(self) -> tuple[np.ndarray | None, FrameMeta] | None:
        if not self.todo:
            return None
        b = self.todo.pop(0)
        img = cv2.imread(str(b.path), cv2.IMREAD_COLOR)
        mask = board_mask(b, img.shape[:2])
        if self.alter:
            img, mask = change(self.alter, img, mask)
        self.truth.append((b, img, mask, time.perf_counter()))
        if not self.alter:
            return None, FrameMeta(b.path, VIEW)
        return img, FrameMeta(b.path.with_name(f"{b.path.stem}_{self.alter}{b.path.suffix}"), VIEW)


def evidence_bytes(ctx: AppContext, record_id: int) -> int:
    """The bytes the evidence policy keeps of a board in the workspace: its overlay, preview and maps (the result files
    in the output folder are counted apart, as a line system takes them away)."""
    rec = ctx.inspection(record_id) or {}
    return sum(p.stat().st_size for p in ctx.settings.results_dir.rglob(f"*{rec.get('uuid', '-')}*") if p.is_file())


def inspect_all(ctx: AppContext, bm: str, boards: list[Board], alter: str | None = None) -> dict[str, Any]:
    """The boards one by one through InspectionCycle.run, each judged against its truth: verdict, found (a defect box
    on its mask, mapped onto the Golden board as the engine aligned it), time and evidence bytes."""
    src, rows, cycle = Frames(boards, alter), list[dict[str, Any]](), ctx.inspection_cycle()
    errors: list[dict[str, str]] = []
    try:
        for out in cycle.run(bm, src):
            wall = time.perf_counter()  # the board's file read, judged and saved, before any of the proxy's own work
            b, img, mask, t0 = src.truth.pop(0)
            res, ref = out.result, out.engine.reference
            hit, moved = True, None
            if mask is not None and ref is not None:  # the mask moved onto the Golden board as the engine moved it
                h, _ = registration(img, ref, fine=out.engine.recipe.fine_alignment is True)
                size = (ref.shape[1], ref.shape[0])
                moved = (  # nearest neighbour and a zero border: no truth pixel is made where the image had none
                    cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
                    if h is None
                    else cv2.warpPerspective(mask, h, size, flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)
                ) > 127
                hit = found([(d.x, d.y, d.w, d.h) for d in res.defects], moved)
            elif mask is not None:
                hit = found([(d.x, d.y, d.w, d.h) for d in res.defects], mask)
            rows.append(
                {
                    "board": b.path.name,
                    "label": b.label,
                    "kind": "+".join(b.kinds) or None,
                    "verdict": res.verdict,
                    "found": hit,
                    "defects": len(res.defects),
                    "ms": round(res.elapsed_ms, 1),
                    "wall_ms": round((wall - t0) * 1000, 1),
                    "bytes": evidence_bytes(ctx, out.record_id) if out.record_id else None,
                    "saved": out.record_id is not None,
                    "save_error": str(out.save_error) if out.save_error else None,
                    "size": list(img.shape[1::-1]),
                    "checks": {f"{c.source}: {c.name}": c.verdict for c in res.checks},
                    "ai_found": found([(d.x, d.y, d.w, d.h) for d in res.defects if d.source == "ai"], moved)
                    if mask is not None and ref is not None
                    else None,
                }
            )
    except AoiError as e:  # the run stopped: AOI-INSP-016 when the shift check stops it, as on the page
        errors.append(code_of(e))
    by = {v: [r["bytes"] for r in rows if r["verdict"] == v and r["bytes"]] for v in ("OK", "WARN", "NG")}
    return {
        **tally(rows),
        "errors": errors,
        "not_judged": len(boards) - len(rows),
        "ms": timing([r["ms"] for r in rows]),
        "wall_ms": timing([r["wall_ms"] for r in rows]),
        "bytes_per_board": {v: int(np.median(x)) if x else None for v, x in by.items()},
        "image_size": rows[0]["size"] if rows else None,
        "rows": rows,
    }


def ui_exports(ctx: AppContext, bm: str, run_uuid: str, out: Path) -> dict[str, Any]:
    """On AI Model Test, with the run opened from History: Validation Report…, Export Report, Export CSV and Export
    Image Overlays, each answered Yes and saved into `out`; every dialog shown is kept with its title and text."""
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from aoi.ui.main_window import MainWindow
    from aoi.ui.pages.model_test import ModelTestPage

    app = QApplication.instance() or QApplication([])
    seen: list[dict[str, str]] = []
    paths = {"validation": out / "validation_report.pdf", "report": out / "model_test_report.pdf"}
    paths |= {"csv": out / "model_test.csv", "overlays": out / "overlays"}
    paths["overlays"].mkdir(parents=True, exist_ok=True)
    want: list[Path] = []

    def save(*a: Any, **k: Any) -> tuple[str, str]:
        return str(want[0]), ""

    def kept(self: QMessageBox) -> int:
        seen.append({"title": self.windowTitle(), "text": self.text(), "more": self.informativeText()})
        return int(QMessageBox.StandardButton.Ok)

    def asked(*a: Any, **k: Any) -> QMessageBox.StandardButton:
        seen.append({"title": str(a[1]), "text": str(a[2]), "more": "question, answered Yes"})
        return QMessageBox.StandardButton.Yes

    patches = [(QFileDialog, "getSaveFileName", staticmethod(save))]
    patches += [(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(paths["overlays"])))]
    patches += [(QMessageBox, "question", staticmethod(asked)), (QMessageBox, "exec", kept)]
    saved = [(o, n, o.__dict__.get(n)) for o, n, _ in patches]
    done: dict[str, Any] = {}
    user, win = ctx.user, None
    try:
        for o, n, v in patches:
            setattr(o, n, v)
        win = MainWindow(ctx)
        win.resize(1600, 900)
        win.show()
        win.set_user(user)  # the window signs in its start user; the run's user takes the header again
        win.select_board_model(bm)
        win.navigate("AI Model Test")
        page = win.pages["AI Model Test"]
        assert isinstance(page, ModelTestPage)
        page._fill_history()
        row = next(i for i, r in enumerate(page._runs) if r["uuid"] == run_uuid)
        page.history.selectRow(row)
        page.open_run()
        steps: list[tuple[str, Callable[[], None], Path]] = [
            ("validation", page.validation_report, paths["validation"]),
            ("report", page.export_report, paths["report"]),
            ("csv", page.export_csv, paths["csv"]),
            ("overlays", page.export_overlays, paths["overlays"]),
        ]
        for name, act, path in steps:
            want[:] = [path]
            before = len(seen)
            act()
            end = time.monotonic() + 300
            while time.monotonic() < end and getattr(page, "_bg", None) is not None:
                app.processEvents()
                time.sleep(0.05)
            for _ in range(20):
                app.processEvents()
            made = any(path.iterdir()) if path.is_dir() else path.is_file()
            done[name] = {"made": made, "dialogs": seen[before:]}
            if name == "overlays":
                done[name]["files"] = len(list(path.iterdir()))
    finally:
        if win is not None:
            win.close()
            win.deleteLater()
        app.processEvents()
        for o, n, v in saved:
            if v is None:
                delattr(o, n)
            else:
                setattr(o, n, v)
    return done


def stage1(
    out: Path,
    bm: str,
    ok: list[Board],
    ng: list[Board],
    held_extra: list[Board],
    seed: int,
    image_size: int = 256,
    epochs: int | None = None,
    ui: bool = True,
) -> dict[str, Any]:
    """One board model through Stage 1 in its own workspace under `out`."""
    out = out.resolve()  # Settings refuses a relative workspace or output folder
    shutil.rmtree(out, ignore_errors=True)
    (out / "result_files").mkdir(parents=True)
    settings = Settings(workspace=str(out / "ws"), device="cpu", output_folder=str(out / "result_files"))
    settings.image_size = image_size
    keys = credentials.MemoryCredentials()  # a station keeps it in Credential Manager; this run, in store-keys.json
    r: dict[str, Any] = {"board_model": bm, "imported": {"ok": len(ok), "ng": len(ng)}, "image_size": image_size}
    r["seed"], ctx, before = seed, None, config.use_workspace(out / "ws")  # its settings.json in its own workspace
    try:
        ctx = AppContext(settings, keys)
        ctx.set_user("admin")  # one person does every step: the Trial path (ADR 0020)
        r["store"] = bool(ctx.create_customer_board_model(bm, CUSTOMER).get("sheet"))
        held = out / "store-keys.json"  # the test store's key, so set B opens the workspace again; owner-only
        with os.fdopen(
            os.open(held, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
        ) as f:  # no owner-only on Windows
            f.write(json.dumps({k: v.hex() for k, v in keys._secrets.items()}))
        links = stage(out / "picked", ok, ng)
        t0 = time.perf_counter()
        report = ctx.import_files(bm, folder_files(out / "picked"))
        r["import"] = {
            "added": len(report.added),
            "refused": [code_of(e) | {"file": f.path} for f, e in report.refused],
            "stopped": code_of(report.stopped[1]) if report.stopped else None,
            "boxes": sum(n for _, n, _ in report.boxes),
            "box_notes": sorted({w for _, _, w in report.boxes if w}),
            "s": round(time.perf_counter() - t0, 1),
        }
        try:
            ctx.freeze_dataset(bm, VIEW, REVISION, CUSTOMER)
            r["validated_freeze"] = "allowed"
        except AoiError as e:
            r["validated_freeze"] = code_of(e)
        version = ctx.freeze_dataset(bm, VIEW, REVISION, CUSTOMER, trial=True)
        assert version is not None
        split = ctx.lock_validation_set(version["uuid"], seed=seed)
        items = {i["uuid"]: i for i in ctx.dataset_items(version["uuid"])}
        by_sha = {s: links[p] for p, s in manifest(Path(p) for p in links).items()}
        locked = [by_sha[items[u]["sha256"]] for u in split["validation"]]
        r["locked"] = {"ok": sum(b.label == "OK" for b in locked), "ng": sum(b.label == "NG" for b in locked)}
        added = [links[f.path] for f in report.added]
        r["trained_on"] = {
            lbl.lower(): sum(b.label == lbl for b in added) - r["locked"][lbl.lower()] for lbl in ("OK", "NG")
        }
        ctx.set_user("engineer")
        reset_peak()
        t0 = time.perf_counter()
        meta = ctx.train(version["uuid"], epochs)
        r["training"] = {"s": round(time.perf_counter() - t0, 1), "peak_mb": peak_mb(), "version": meta["version"]}
        r["training"] |= {"activated_by_training": meta.get("activated"), "not_live": meta.get("not_live")}
        model = next(m for m in ctx.models(bm) if m["version"] == meta["version"])
        active = ctx.active_model(bm)
        if active is None or active["id"] != model["id"]:
            ctx.activate_model(int(model["id"]))
        metrics, rows, _ = ctx.test_dataset(version["uuid"])
        if not rows:
            raise RuntimeError("AI Model Test judged no image of the locked validation set")
        run_uuid = rows[0]["run_uuid"]
        r["model_test"] = {k: metrics[k] for k in ("samples", "TP", "FN", "FP", "TN")} | {"rates": metrics["rates"]}
        try:
            shift = ctx.run_shift_check(bm)
            r["shift_check"] = {
                "state": shift["state"],
                "passed": shift["check"]["passed"],
                "rows": [(x["expected"], x["verdict"]) for x in shift["check"]["rows"]],
            }
        except AoiError as e:  # AOI-INSP-017: no master sample to judge
            shift, r["shift_check"] = {"state": "not run"}, {"state": "not run", **code_of(e)}
        if shift["state"] not in (
            "passed",
            "off",
        ):  # the line stays stopped (AOI-INSP-016): an Admin turns the check off to go on
            ctx.set_user("admin")
            ctx.save_settings({"shift_check_hours": 0})
            r["shift_check"]["then"] = "turned off by an Admin on Settings (shift_check_hours 0) to inspect at all"
        ctx.set_user("operator")  # the line's role inspects
        reset_peak()
        r["held_out"] = inspect_all(ctx, bm, locked + held_extra)
        r["held_out"]["peak_mb"] = peak_mb()
        r["held_out"]["extra_ok"] = len(held_extra)
        r["result_files"] = check_result_files(out / "result_files")
        r["alarms"] = sorted({(a.get("code") or "", a.get("level") or "") for a in ctx.alarms()})
        if ui:
            ctx.set_user("admin")  # Export CSV, overlays and reports are an Admin's (Q58)
            r["exports"] = ui_exports(ctx, bm, run_uuid, out / "exports")
    except Exception as e:  # recorded as the run met it: a finding, never hidden
        r["error"] = code_of(e)
    finally:
        if ctx is not None:
            ctx.close()
        config.use_workspace(before)
    return r
