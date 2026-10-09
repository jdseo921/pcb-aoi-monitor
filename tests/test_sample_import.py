"""REQ-TRN-001 (stage S31): an import copies each sample into the workspace and never changes its source, checks it as
Inspection checks an image, skips one already imported, and gives every NG sample one of the 33 DCT types."""

from __future__ import annotations

import builtins
import errno
import hashlib
import io
import shutil
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from aoi.core.imaging import list_images
from aoi.core.sample_import import ImportFile, folder_files
from aoi.core.services import AppContext
from aoi.data import atomic
from aoi.defects import names
from aoi.errors import AoiError
from aoi.ui.main_window import MainWindow
from tests.conftest import distinct_copies
from tests.test_dataset_stores import as_admin
from tests.test_no_freeze import BUDGET_S, gap_meter
from tools.trainable import trainable

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


def test_req_trn_001_update_sample_relabels_ng_only_with_one_of_the_33_types(
    ctx: AppContext, synthetic_dataset: Path
) -> None:
    """AppContext.update_sample holds to the import's rule: it refuses NG without one of the 33 types (none, "Unknown /
    mixed", "Anomaly") with AOI-TRN-013, and a label other than OK or NG with AOI-TRN-018, which says the sample was not
    given that label, leaving the sample as it was; a relabel to OK clears the type. Training's marks do not call it:
    they write through set_label (S33, test_req_trn_003_editor_mark)."""
    ctx.import_samples(BOARD, [str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:2]], "OK")
    sample = ctx.samples(BOARD)[1]["id"]  # not the reference, which is never relabelled NG (AOI-TRN-007)

    def kept() -> tuple[str, str | None]:
        return [(r["label"], r["defect_type"]) for r in ctx.samples(BOARD)][1]

    for label, kind, code in [("NG", None, "AOI-TRN-013"), ("NG", "Unknown / mixed", "AOI-TRN-013"),
                              ("NG", "Anomaly", "AOI-TRN-013"), ("ng", "Scratch", "AOI-TRN-018")]:  # fmt: skip
        with pytest.raises(AoiError) as refused:
            ctx.update_sample(sample, label, kind)
        assert refused.value.code == code, refused.value
    name = Path(ctx.samples(BOARD)[1]["path"]).name
    assert refused.value.what == f'{name} was not given the label "ng": it is not one of OK, NG.', refused.value.what
    assert kept() == ("OK", None)
    ctx.update_sample(sample, "NG", "Scratch")
    assert kept() == ("NG", "Scratch")
    ctx.update_sample(sample, "OK", "Scratch")
    assert kept() == ("OK", None)


@pytest.mark.parametrize("side", ["Front", "", "top", "../../outside", "Top/../.."])
def test_req_trn_001_an_import_refuses_a_view_other_than_top_side_or_bottom(
    ctx: AppContext, synthetic_dataset: Path, side: str
) -> None:
    """A view names a dataset version and its folders (S35), so whoever calls AppContext, an import takes only Top,
    Side or Bottom as aoi.hal.VIEWS writes them: any other is refused with AOI-TRN-017 before anything is copied, and
    import_files lists that file with the code while the others go in."""
    a, b = (str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:2])
    with pytest.raises(AoiError) as refused:
        ctx.import_samples(BOARD, [a], "OK", None, side)
    assert (refused.value.code, refused.value.params["view"]) == ("AOI-TRN-017", side), refused.value
    assert ctx.samples(BOARD) == [] and not ctx.settings.images_dir.joinpath(BOARD).exists()
    report = ctx.import_files(BOARD, [ImportFile(a, "OK", None, side), ImportFile(b, "OK", None, "Bottom")])
    assert [(f.path, e.code) for f, e in report.refused] == [(a, "AOI-TRN-017")] and report.stopped is None
    assert [(r["side"], r["sha256"] is not None) for r in ctx.samples(BOARD)] == [("Bottom", True)]


def outside(ctx: AppContext, tmp_path: Path) -> set[Path]:
    """Every file and folder of the test's own folder outside the workspace: what an import must never add to."""
    return {p for p in tmp_path.rglob("*") if not p.is_relative_to(ctx.settings.root)}


@pytest.mark.parametrize("label", ["ok", "UNSURE", "", "../../../escaped"])
def test_req_trn_001_an_import_refuses_a_label_other_than_ok_or_ng(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, label: str
) -> None:
    """A label names the copy's folder (images/<board model>/<label>/) and the samples table holds OK or NG alone, so
    whoever calls AppContext, an import refuses any other label with AOI-TRN-018 before anything is copied, never with
    a database error after the copy, and writes nothing outside the workspace; import_files lists that file with the
    code, a lowercase "ok" too, while the others go in."""
    a, b = (str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:2])
    before = outside(ctx, tmp_path)
    with pytest.raises(AoiError) as refused:
        ctx.import_samples(BOARD, [a], label)
    assert (refused.value.code, refused.value.params["label"]) == ("AOI-TRN-018", label), refused.value
    report = ctx.import_files(BOARD, [ImportFile(a, label), ImportFile(b, "OK")])
    assert [(f.path, e.code) for f, e in report.refused] == [(a, "AOI-TRN-018")] and report.stopped is None
    assert [r["label"] for r in ctx.samples(BOARD)] == ["OK"] and len(list(ctx.settings.images_dir.rglob("*.*"))) == 1
    assert outside(ctx, tmp_path) == before


@pytest.mark.parametrize(
    "name",
    ["", "../../bm_escape", "a/b", "a\\b", ".", "..", "TBOX.", "TBOX ", "CON", "nul", "COM1", "Lpt9.txt", "A:B", "A*B",
     'A"B', "A?B", "A<B", "A>B", "A|B", "A\tB", "COM0", "lpt0.txt", "COM¹", "LPT³.png", "conin$", "CONOUT$.log"],
)  # fmt: skip
def test_req_trn_001_a_new_board_model_name_is_one_safe_folder_name(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, name: str
) -> None:
    """A board model's name is the name of its folders under images/ and models/, so a new one, made by + New board
    model (ensure_board_model) or by its first import, is one folder name on Windows as on Linux: not empty, . or ..,
    no / \\ : * ? " < > | or control character, no dot or space at its end, and not a name Windows keeps for a device
    (CON, NUL, COM0 to COM9 and COM¹ to COM³, LPT the same, CONIN$, CONOUT$, in any case and with an extension, as
    LPT9.txt). Any other is refused with AOI-TRN-019 before anything is written."""
    a = str(list_images(synthetic_dataset / "train" / "ok")[0])
    before = outside(ctx, tmp_path)
    for create in (ctx.ensure_board_model, lambda n: ctx.import_samples(n, [a], "OK")):
        with pytest.raises(AoiError) as refused:
            create(name)
        assert (refused.value.code, refused.value.params["name"]) == ("AOI-TRN-019", name), refused.value
    assert ctx.db.board_models() == [] and not any(ctx.settings.images_dir.rglob("*.*"))
    assert outside(ctx, tmp_path) == before


def test_req_trn_001_an_import_copies_only_into_images(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    """Names such as TBOX-A1 Rev2, v1.2, CONSOLE or COM10 are taken. A board model made before its name was checked
    keeps it, but its import copies only into a folder inside the workspace's images/: a name that leads elsewhere
    (../../escape, as a row from before could hold) is refused with AOI-TRN-019 and nothing is written outside."""
    a = str(list_images(synthetic_dataset / "train" / "ok")[0])
    for name in ("TBOX-A1 Rev2", "v1.2", "기판 A", "CONSOLE", "COM10"):
        ctx.ensure_board_model(name)
    ctx.db.ensure_board_model("../../escape")
    before = outside(ctx, tmp_path)
    with pytest.raises(AoiError) as refused:
        ctx.import_samples("../../escape", [a], "OK")
    assert (refused.value.code, refused.value.params["name"]) == ("AOI-TRN-019", "../../escape"), refused.value
    assert outside(ctx, tmp_path) == before and ctx.samples("../../escape") == []
    assert ctx.import_samples("COM10", [a], "OK") == 1


def test_req_trn_001_a_name_the_workspace_already_holds_is_kept(ctx: AppContext, synthetic_dataset: Path) -> None:
    """AOI-TRN-019 refuses a new name alone: a board model a workspace already holds under a name the rule refuses
    (TBOX., made before names were checked) can still be created, which changes nothing, and imported into, while a
    new TBOX2. is refused both ways."""
    a = str(list_images(synthetic_dataset / "train" / "ok")[0])
    ctx.db.ensure_board_model("TBOX.")
    ctx.ensure_board_model("TBOX.")
    assert ctx.import_samples("TBOX.", [a], "OK") == 1 and len(ctx.samples("TBOX.")) == 1
    for create in (ctx.ensure_board_model, lambda n: ctx.import_samples(n, [a], "OK")):
        with pytest.raises(AoiError) as refused:
            create("TBOX2.")
        assert (refused.value.code, refused.value.params["name"]) == ("AOI-TRN-019", "TBOX2."), refused.value
    assert ctx.db.board_models() == ["TBOX."]


def test_req_trn_001_set_reference_and_training_meet_the_name_rule(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    """Set Reference and a training run, which write a board model's row and its models/ folder, meet the rule a new
    board model meets, with the same exception for a name the workspace already holds: TBOX., made before names were
    checked, gets its reference, and its training passes the rule and stops at the dataset store, which training
    reads from (AOI-TRN-046) and which never holds TBOX. (AOI-TRN-019: Windows names its folder images/TBOX), while a
    new name the rule refuses is refused before anything is written (CON and TBOX2. with AOI-TRN-019, tbox-a1 beside
    TBOX-A1 with AOI-TRN-005), and a held name that leads outside models/ never trains (AOI-TRN-019)."""
    ctx.db.ensure_board_model("TBOX.")
    ctx.db.ensure_board_model("../../escape")
    ctx.ensure_board_model("TBOX-A1")
    oks = [str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:20]]  # the 20 OK training needs
    assert ctx.import_samples("TBOX.", oks, "OK") == 20
    held = ctx.samples("TBOX.", "OK")[1]["id"]
    ctx.set_reference("TBOX.", held)
    store = as_admin(ctx, ctx.create_store, "Acme Electronics")
    with pytest.raises(AoiError) as refused:
        as_admin(ctx, ctx.move_in, "TBOX.", store["uuid"])
    assert refused.value.code == "AOI-TRN-019" and ctx.store_of("TBOX.") is None
    with pytest.raises(AoiError) as refused:
        ctx.train(trainable(ctx, "TBOX.", stored=False), epochs=1, image_size=32)
    assert refused.value.code == "AOI-TRN-046" and "in no customer's dataset store" in refused.value.what
    before = outside(ctx, tmp_path)
    writes = (lambda n: ctx.set_reference(n, held), lambda n: ctx.train(trainable(ctx, n), epochs=1, image_size=32))
    for name, code in (("CON", "AOI-TRN-019"), ("TBOX2.", "AOI-TRN-019"), ("tbox-a1", "AOI-TRN-005")):
        for write in writes:
            with pytest.raises(AoiError) as refused:
                write(name)
            assert refused.value.code == code, (name, refused.value)
    with pytest.raises(AoiError) as refused:
        ctx.train(trainable(ctx, "../../escape"), epochs=1, image_size=32)
    assert (refused.value.code, refused.value.params["name"]) == ("AOI-TRN-019", "../../escape"), refused.value
    assert sorted(ctx.db.board_models()) == ["../../escape", "TBOX-A1", "TBOX."] and outside(ctx, tmp_path) == before


@pytest.mark.parametrize("how", ["gone", "unreadable"])
def test_req_trn_001_a_source_lost_before_its_copy_is_listed_and_the_others_go_in(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """A file removed or made unreadable between its check and its copy is that file's to fix, not the workspace's: it
    is refused with AOI-INSP-001, as Inspection refuses a file it cannot read, and listed while the others go in, with
    no copy of it left. A copy the workspace refuses still stops the import (AOI-TRN-008, the test above)."""
    picked = distinct_copies(list_images(synthetic_dataset / "train" / "ok")[0], tmp_path / "picked", 3)
    files = [ImportFile(str(p), "OK") for p in picked]
    copy = atomic.copy_file

    def lose_then_copy(src: str | Path, dst: str | Path) -> None:
        if Path(src) == picked[1] and how == "gone":
            picked[1].unlink()
        elif Path(src) == picked[1]:
            raise PermissionError(errno.EACCES, "Permission denied", str(src))
        copy(src, dst)

    monkeypatch.setattr(atomic, "copy_file", lose_then_copy)
    report = ctx.import_files(BOARD, files)
    assert [(f, e.code) for f, e in report.refused] == [(files[1], "AOI-INSP-001")], report
    assert report.added == [files[0], files[2]] and report.stopped is None and report.left == []
    assert len(list(ctx.settings.images_dir.rglob("*"))) == len(ctx.samples(BOARD)) + 2  # the two folders, two copies


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
    label, an NG with no type, an image already imported (with the sample that has it and its label) and a file that is
    not an image are each listed with their code (AOI-TRN-016, -013, -015, AOI-INSP-004) while the others go in."""
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
    has = {"sample": Path(ctx.samples(BOARD)[1]["path"]).name, "label": "OK"}  # a.png's: b.png names the sample
    assert report.refused[2][1].params | has == report.refused[2][1].params, report.refused[2][1].params


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


def test_req_trn_001_200_files_20mp_no_freeze(qtbot: QtBot, ctx: AppContext, tmp_path: Path) -> None:
    """The stage's acceptance: Import Folder… on 100 OK and 100 NG files of 20 MP (5472 x 3648), the NG ones in
    ng/solder_bridge/, with Side picked for all on the sheet. Import runs on the pool and every file goes in with its
    view and, for NG, its type, while the window's event loop never stalls for 2 s: a 50 ms timer on the window thread
    measures each gap (`gap_meter`), so a slower runner takes longer but is held to the same budget. The files are one
    plain JPEG, each with bytes of its own after the image's end: cheap to write, each its own SHA-256."""
    board = np.full((3648, 5472, 3), 96, np.uint8)
    cv2.rectangle(board, (500, 400), (4900, 3200), (40, 150, 40), -1)  # a board on a plain ground: a small JPEG
    encoded, jpeg = cv2.imencode(".jpg", board)
    assert encoded
    folder = tmp_path / "src"
    for i in range(200):
        sub = folder / ("ok" if i < 100 else "ng/solder_bridge")
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"board_{i:03d}.jpg").write_bytes(jpeg.tobytes() + i.to_bytes(2, "big"))
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1600, 900)
    win.show()
    qtbot.waitExposed(win)
    win.set_user("engineer")
    win._on_board_model(BOARD)
    win.navigate("Training")
    page = win.pages["Training"]
    with gap_meter(qtbot) as g:
        page.import_from(str(folder))
        qtbot.mouseClick(page.sheet.views.button(1), Qt.MouseButton.LeftButton)  # Side, for all
        qtbot.mouseClick(page.sheet.btn_import, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: page._bg is None and not page.sheet.running, timeout=900000)
    assert g["longest_s"] < BUDGET_S, g
    rows = ctx.samples(BOARD)
    assert len(rows) == 200 == page.samples.rowCount()
    assert ctx.load_image(ctx.sample_path(rows[-1]["id"])).shape == board.shape, "a 20 MP copy, read back"
    kinds = Counter((r["label"], r["defect_type"], r["side"]) for r in rows)
    assert kinds == {("OK", None, "Side"): 100, ("NG", "Solder Bridge", "Side"): 100}, kinds
