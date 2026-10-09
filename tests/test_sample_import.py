"""REQ-TRN-001 (stage S31): an import copies each sample into the workspace and never changes its source, checks it as
Inspection checks an image, skips one already imported, and gives every NG sample one of the 33 DCT types."""

from __future__ import annotations

import builtins
import errno
import hashlib
import io
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from aoi.core.imaging import list_images
from aoi.core.sample_import import ImportFile, folder_files
from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.defects import names
from aoi.errors import AoiError

BOARD = "TBOX-A1"


def sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def state(folder: Path) -> dict[str, tuple[str, int, int]]:
    """Every file under `folder` with its SHA-256, modification time and size: what an import must leave as it was."""
    files = [p for p in folder.rglob("*") if p.is_file()]
    return {p.relative_to(folder).as_posix(): (sha(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files}


def source_folder(synthetic_dataset: Path, tmp_path: Path) -> Path:
    """ok/ with three good boards and ng/solder_bridge/ with one NG board: the layout Import Folder… reads."""
    folder = tmp_path / "source"
    for sub, files in (
        ("ok", list_images(synthetic_dataset / "train" / "ok")[:3]),
        ("ng/solder_bridge", list(synthetic_dataset.glob("train/ng/*solder_bridge*.png"))[:1]),
    ):
        (folder / sub).mkdir(parents=True)
        for f in files:
            shutil.copy(f, folder / sub / f.name)
    return folder


def opened_modes(monkeypatch: pytest.MonkeyPatch, folder: Path) -> list[tuple[str, str]]:
    """Each (file, mode) under `folder` that anything opens from now on, through open() or pathlib."""
    seen: list[tuple[str, str]] = []
    real = builtins.open

    def recording(file: object, mode: str = "r", *args: object, **kwargs: object) -> object:
        if isinstance(file, (str, Path)) and Path(file).resolve().is_relative_to(folder.resolve()):
            seen.append((Path(file).name, mode))
        return real(file, mode, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(builtins, "open", recording)
    monkeypatch.setattr(io, "open", recording)
    return seen


def test_req_trn_001_source_unchanged(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An import opens its sources only to read them: every source keeps its bytes, SHA-256, modification time and
    size, and nothing is added beside it. Each sample holds its own copy in the workspace, stored relative to it, whose
    SHA-256 is the source's and is recorded with the sample, and the import's audit entry names each sample it added
    by its UUID and SHA-256. A source that changes while it is copied (a camera still writing it) is refused with
    AOI-TRN-014, and nothing of that import is kept."""
    folder = source_folder(synthetic_dataset, tmp_path)
    before = state(folder)
    modes = opened_modes(monkeypatch, folder)
    oks, ngs = list_images(folder / "ok"), list_images(folder / "ng")
    assert ctx.import_samples(BOARD, [str(p) for p in oks], "OK") == 3
    assert ctx.import_samples(BOARD, [str(p) for p in ngs], "NG", "Solder Bridge") == 1
    monkeypatch.undo()
    assert state(folder) == before
    assert modes and {m for _, m in modes} == {"rb"}, modes
    rows = ctx.samples(BOARD)
    stored = ctx.db.query("SELECT uuid, path, sha256 FROM samples ORDER BY id")  # the table, whatever a row shows
    assert [r["sha256"] for r in stored] == [sha(p) for p in oks + ngs]
    assert [sha(r["path"]) for r in rows] == [sha(p) for p in oks + ngs]
    assert all(Path(r["path"]).is_relative_to(ctx.settings.images_dir / BOARD) for r in rows)
    assert all(not Path(r["path"]).is_absolute() for r in stored), stored
    named = [s for e in reversed(ctx.audit_entries(action="sample.import")) for s in e["after"]["samples"]]
    assert named == [{"uuid": r["uuid"], "sha256": r["sha256"]} for r in stored], "each entry names its samples"

    late = tmp_path / "late.png"
    shutil.copy(list_images(synthetic_dataset / "train" / "ok")[5], late)
    copy = atomic.copy_file

    def copy_then_write(src: str | Path, dst: str | Path) -> None:
        copy(src, dst)
        if Path(src) == late:
            with open(late, "ab") as f:  # the source's own writer adds to it after the copy was taken
                f.write(b"\0")

    monkeypatch.setattr(atomic, "copy_file", copy_then_write)
    files_before = sorted(ctx.settings.images_dir.rglob("*"))
    with pytest.raises(AoiError) as refused:
        ctx.import_samples(BOARD, [str(list_images(synthetic_dataset / "train" / "ok")[4]), str(late)], "OK")
    assert refused.value.code == "AOI-TRN-014" and refused.value.params["path"] == str(late), refused.value
    assert len(ctx.samples(BOARD)) == 4 and sorted(ctx.settings.images_dir.rglob("*")) == files_before


@pytest.mark.parametrize("defect_type", [None, "", "Unknown / mixed", "Anomaly", "solder bridge", "Bridge"])
def test_req_trn_001_ng_has_dct_type(
    ctx: AppContext, synthetic_dataset: Path, ng_board: Path, defect_type: str | None
) -> None:
    """An NG sample is imported only with one of the 33 types of the defect classification table, named as the table
    names it: no type, "Unknown", the model's "Anomaly" or a name the table does not hold is refused with AOI-TRN-013
    before anything is copied. OK samples need none."""
    assert len(names()) == 33
    with pytest.raises(AoiError) as refused:
        ctx.import_samples(BOARD, [str(ng_board)], "NG", defect_type)
    assert refused.value.code == "AOI-TRN-013", refused.value
    assert ctx.samples(BOARD) == [] and not ctx.settings.images_dir.joinpath(BOARD).exists()
    ctx.import_samples(BOARD, [str(ng_board)], "NG", "Missing Component")
    ctx.import_samples(BOARD, [str(list_images(synthetic_dataset / "train" / "ok")[0])], "OK")
    assert [(r["label"], r["defect_type"]) for r in ctx.samples(BOARD)] == [("NG", "Missing Component"), ("OK", None)]


@pytest.mark.parametrize(
    ("write", "code"),
    [
        (lambda p, png: p.write_bytes(b"not an image at all"), "AOI-INSP-004"),
        (lambda p, png: p.write_bytes(png[: len(png) // 2]), "AOI-INSP-006"),
        (lambda p, png: None, "AOI-INSP-001"),
    ],
    ids=["text", "cut-short", "gone"],
)
def test_req_trn_001_an_import_checks_each_file_as_inspection_does(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, write: Callable[[Path, bytes], object], code: str
) -> None:
    """The headless import takes all the files or none (#178): a file that is not an image by its content, one cut
    short, or one gone since it was picked is refused with the code Inspection gives it, and nothing is imported; so is
    an image over the size set in Settings (AOI-INSP-005, decision Q30)."""
    good = list_images(synthetic_dataset / "train" / "ok")[0]
    bad = tmp_path / "bad.png"
    write(bad, good.read_bytes())
    with pytest.raises(AoiError) as refused:
        ctx.import_samples(BOARD, [str(good), str(bad)], "OK")
    assert refused.value.code == code, refused.value
    ctx.settings.max_image_megapixels = 0.01
    with pytest.raises(AoiError) as refused:
        ctx.import_samples(BOARD, [str(good)], "OK")
    assert refused.value.code == "AOI-INSP-005", refused.value
    assert ctx.samples(BOARD) == [] and not any(ctx.settings.images_dir.rglob("*.png"))


def test_req_trn_001_an_image_already_imported_is_skipped(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    """Decision Q31: an image the board model already has (the same SHA-256, under any file name or label), or one
    picked twice, is skipped, and the import goes on; progress counts it, and the audit entry counts it and names the
    sample that has it, by UUID and SHA-256. The board model is asked once a file, by SHA-256 through its index, not
    for every hash. Another board model takes the image. A sample imported before the sample SHA-256 migration has no
    SHA-256 and is never taken for the same image."""
    oks = list_images(synthetic_dataset / "train" / "ok")[:3]
    renamed = tmp_path / "renamed.png"
    shutil.copy(oks[0], renamed)
    assert ctx.import_samples(BOARD, [str(oks[0]), str(oks[1])], "OK") == 2
    done: list[tuple[int, int]] = []
    again = [str(renamed), str(oks[2]), str(oks[2])]
    assert ctx.import_samples(BOARD, again, "OK", progress=lambda n, total: done.append((n, total))) == 1
    assert done == [(1, 3), (2, 3), (3, 3)]
    entry = ctx.audit_entries(action="sample.import")[0]
    assert (entry["after"]["added"], entry["after"]["skipped"]) == (1, 2), entry
    uuids = [r["uuid"] for r in ctx.db.query("SELECT uuid FROM samples ORDER BY id")]
    has = [{"uuid": uuids[0], "sha256": sha(oks[0])}, {"uuid": uuids[2], "sha256": sha(oks[2])}]
    assert entry["after"]["already"] == has, entry
    said: list[str] = []
    ctx.db._conn.set_trace_callback(said.append)
    assert ctx.import_samples(BOARD, [str(oks[1])], "NG", "Scratch") == 0  # another label: still the same image
    ctx.db._conn.set_trace_callback(None)
    (looked,) = [q for q in said if q.startswith("SELECT") and "FROM samples" in q and "sha256" in q]
    plan = " ".join(str(r["detail"]) for r in ctx.db.query(f"EXPLAIN QUERY PLAN {looked}"))
    assert "samples_sha256 (board_model=? AND sha256=?)" in plan, (looked, plan)
    assert [sha(r["path"]) for r in ctx.samples(BOARD)] == [sha(p) for p in oks]
    assert len(list(ctx.settings.images_dir.joinpath(BOARD).rglob("*.png"))) == 3, "a skipped image leaves no copy"
    assert ctx.import_samples("OTHER", [str(oks[0])], "OK") == 1
    ctx.db.execute("UPDATE samples SET sha256=NULL WHERE board_model=?", (BOARD,))  # as rows from before it are
    assert ctx.import_samples(BOARD, [str(oks[0])], "OK") == 1


def test_req_trn_001_an_import_lists_each_file_it_refuses_with_its_code_and_goes_on(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    """The import sheet's import (`import_files`): a folder's files are labelled by their sub-folders, with the type of
    ng/<type>/ (any case, spaces or underscores); each goes in with its own label, type and view, and a file with no
    label, an NG with no type, an image already imported and a file that is not an image are each listed with their
    code (AOI-TRN-016, -013, -015, AOI-INSP-004) while the others go in."""
    folder = tmp_path / "src"
    ok, other = list_images(synthetic_dataset / "train" / "ok")[:2]
    ng = next(synthetic_dataset.glob("train/ng/*solder_bridge*.png"))
    # names listed in the same order where paths sort by case (Linux) and where they sort without it (Windows)
    for src, name in ((ok, "ok/a.png"), (ok, "ok/b.png"), (ng, "ng/Solder_Bridge/c.png"), (ng, "ng/untyped.png")):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, folder / name)
    (folder / "loose").mkdir()
    shutil.copy(other, folder / "loose" / "e.png")
    (folder / "ok" / "notes.png").write_text("not an image")
    files = folder_files(folder)
    named = [(Path(f.path).relative_to(folder).as_posix(), f.label, f.defect_type) for f in files]
    assert named == [
        ("loose/e.png", None, None),
        ("ng/Solder_Bridge/c.png", "NG", "Solder Bridge"),
        ("ng/untyped.png", "NG", None),
        ("ok/a.png", "OK", None),
        ("ok/b.png", "OK", None),
        ("ok/notes.png", "OK", None),
    ]
    files[1].side = "Side"
    report = ctx.import_files(BOARD, files)
    assert report.added == [files[1], files[3]] and report.stopped is None and report.left == []
    refused = [(Path(f.path).name, e.code) for f, e in report.refused]
    assert refused == [
        ("e.png", "AOI-TRN-016"),
        ("untyped.png", "AOI-TRN-013"),
        ("b.png", "AOI-TRN-015"),
        ("notes.png", "AOI-INSP-004"),
    ]
    rows = [(r["label"], r["defect_type"], r["side"]) for r in ctx.samples(BOARD)]
    assert rows == [("NG", "Solder Bridge", "Side"), ("OK", None, "Top")]


def test_req_trn_001_an_import_stopped_by_an_error_or_cancel_keeps_what_went_in(
    ctx: AppContext, synthetic_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A copy the workspace refuses (its drive full) stops the import at that file, which the report names with its
    error: the files before it stay imported and the rest are left. Cancel leaves the files not yet reached."""
    oks = list_images(synthetic_dataset / "train" / "ok")[:4]
    files = [ImportFile(str(p), "OK") for p in oks]
    copy = atomic.copy_file

    def full(src: str | Path, dst: str | Path) -> None:
        if Path(src) == oks[2]:
            raise OSError(errno.ENOSPC, "No space left on device", str(dst))
        copy(src, dst)

    monkeypatch.setattr(atomic, "copy_file", full)
    report = ctx.import_files(BOARD, files)
    assert report.added == files[:2] and report.refused == [] and report.left == files[3:]
    assert report.stopped is not None and report.stopped[0] == files[2], report.stopped
    assert isinstance(report.stopped[1], AoiError) and report.stopped[1].code == "AOI-TRN-008", report.stopped
    assert len(ctx.samples(BOARD)) == 2
    monkeypatch.undo()
    done: list[int] = []
    report = ctx.import_files(BOARD, files, lambda n, total: done.append(n), lambda: len(done) == 3)
    assert [f for f, _ in report.refused] == files[:2] and report.added == [files[2]] and report.left == files[3:]
    assert len(ctx.samples(BOARD)) == 3
