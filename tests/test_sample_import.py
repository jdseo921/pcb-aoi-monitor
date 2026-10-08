"""REQ-TRN-001 (stage S31): an import copies each sample into the workspace and never changes its source, checks it as
Inspection checks an image, and gives every NG sample one of the 33 DCT types."""

from __future__ import annotations

import builtins
import hashlib
import io
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from aoi.core.imaging import list_images
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
