"""REQ-TRN-019 (ADR 0016): a labelled dataset's own boxes come in with its images. Import Folder… and Add NG Images…
read each image's Pascal VOC or YOLO annotation file, label and type the image by its boxes, and the import stores the
boxes as a drawing is stored, audited; a box of a class that is no defect type, or an annotation file that cannot be
read, is left out and the sheet says why."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from aoi.core import annotation_files
from aoi.core.imaging import file_header, list_images
from aoi.core.sample_import import folder_files
from aoi.core.services import AppContext
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.base import cell_item
from aoi.ui.pages.training_import import STATUS, TYPE
from tests.test_import_sheet import _rows

BOARD = "PKU-01"


def _voc(width: int, height: int, *objects: tuple[str, int, int, int, int]) -> str:
    boxes = "".join(
        f"<object><name>{n}</name><bndbox><xmin>{a}</xmin><ymin>{b}</ymin><xmax>{c}</xmax><ymax>{d}</ymax></bndbox>"
        "</object>"
        for n, a, b, c, d in objects
    )
    return (
        f"<annotation><size><width>{width}</width><height>{height}</height><depth>3</depth></size>{boxes}</annotation>"
    )


@pytest.fixture
def pku_like(synthetic_dataset: Path, tmp_path: Path) -> tuple[Path, int, int]:
    """PKU-Market-PCB's layout: images/<Defect>/<name>.jpg with Annotations/<Defect>/<name>.xml, and PCB_USED/ with a
    good board that has no annotation."""
    oks, ngs = list_images(synthetic_dataset / "train" / "ok"), list_images(synthetic_dataset / "train" / "ng")
    _, w, h = file_header(ngs[0]) or ("", 0, 0)
    root = tmp_path / "PCB_DATASET"
    for defect, src, objects in (
        ("Mouse_bite", ngs[0], [("mouse_bite", 40, 50, 70, 80), ("mouse_bite", 100, 110, 120, 130)]),
        ("Missing_hole", ngs[1], [("missing_hole", 10, 20, 30, 40), ("label_on_silk", 5, 5, 9, 9)]),
    ):
        (root / "images" / defect).mkdir(parents=True)
        (root / "Annotations" / defect).mkdir(parents=True)
        shutil.copy(src, root / "images" / defect / f"01_{defect.lower()}_01.png")
        (root / "Annotations" / defect / f"01_{defect.lower()}_01.xml").write_text(_voc(w, h, *objects))
    (root / "PCB_USED").mkdir()
    shutil.copy(oks[0], root / "PCB_USED" / "01.png")
    return root, w, h


def test_req_trn_019_voc_boxes_label_type_and_come_in_audited(ctx: AppContext, pku_like: tuple[Path, int, int]) -> None:
    """A folder in PKU-Market-PCB's layout lists each annotated image NG, typed by its boxes' classes (mouse_bite is
    Mousebite, missing_hole Pin-hole / Missing Hole), and the good board with no annotation unlabelled. The import
    stores each box at its place, audited as label.set, and names the class that is no defect type."""
    root, _, _ = pku_like
    files = {Path(f.path).parent.name: f for f in folder_files(root)}
    assert (files["Mouse_bite"].label, files["Mouse_bite"].defect_type) == ("NG", "Mousebite")
    assert files["Mouse_bite"].box_types == ["Mousebite", "Mousebite"]
    assert (files["Missing_hole"].label, files["Missing_hole"].defect_type) == ("NG", "Pin-hole / Missing Hole")
    assert files["PCB_USED"].label is None and not files["PCB_USED"].box_types
    report = ctx.import_files(BOARD, [files["Mouse_bite"], files["Missing_hole"]])
    assert len(report.added) == 2 and not report.refused
    said = {Path(f.path).parent.name: (n, str(why)) for f, n, why in report.boxes}
    assert said["Mouse_bite"] == (2, "")
    assert said["Missing_hole"][0] == 1 and "label_on_silk" in said["Missing_hole"][1]
    by_type = {s["defect_type"]: s for s in ctx.samples(BOARD)}
    boxes = [(b["x"], b["y"], b["w"], b["h"], b["dct_type"]) for b in ctx.boxes(by_type["Mousebite"]["uuid"])]
    assert boxes == [(40, 50, 30, 30, "Mousebite"), (100, 110, 20, 20, "Mousebite")]
    entries = ctx.audit_entries(action="label.set")
    assert len(entries) == 2 and all(e["role"] == "Engineer" for e in entries)


def test_req_trn_019_yolo_boxes_with_data_yaml_and_an_empty_file_for_a_good_image(
    ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    """A YOLO export (images/train with labels/train and a data.yaml naming the classes) lists an image whose label
    file is empty as OK, and an image with boxes NG; the boxes, as shares of the image, come in in pixels."""
    oks, ngs = list_images(synthetic_dataset / "train" / "ok"), list_images(synthetic_dataset / "train" / "ng")
    _, w, h = file_header(ngs[0]) or ("", 0, 0)
    root = tmp_path / "export"
    for sub in ("images/train", "labels/train"):
        (root / sub).mkdir(parents=True)
    (root / "data.yaml").write_text("train: images/train\nnc: 2\nnames:\n  - spur\n  - Solder Bridge\n")
    shutil.copy(ngs[0], root / "images/train/a.png")
    shutil.copy(oks[0], root / "images/train/b.png")
    (root / "labels/train/a.txt").write_text("1 0.5 0.5 0.25 0.5\n0 0.1 0.1 0.1 0.1\n")
    (root / "labels/train/b.txt").write_text("")
    files = {Path(f.path).stem: f for f in folder_files(root)}
    assert (files["a"].label, files["a"].defect_type, files["a"].box_types) == (
        "NG",
        "Solder Bridge",
        ["Solder Bridge", "Spur"],
    )
    assert files["b"].label == "OK"
    report = ctx.import_files(BOARD, list(files.values()))
    assert len(report.added) == 2 and [(n, str(why)) for _, n, why in report.boxes] == [(2, "")]
    (ng,) = ctx.samples(BOARD, "NG")
    got = [(b["x"], b["y"], b["w"], b["h"], b["dct_type"]) for b in ctx.boxes(ng["uuid"])]
    assert got == [
        (
            round(w * 0.375),
            round(h * 0.25),
            round(w * 0.625) - round(w * 0.375),
            round(h * 0.75) - round(h * 0.25),
            "Solder Bridge",
        ),
        (
            round(w * 0.05),
            round(h * 0.05),
            round(w * 0.15) - round(w * 0.05),
            round(h * 0.15) - round(h * 0.05),
            "Spur",
        ),
    ]


def test_req_trn_019_an_annotation_file_that_is_not_read_stores_no_box_and_says_why(
    ctx: AppContext, pku_like: tuple[Path, int, int]
) -> None:
    """An annotation made for an image of another size, one with a document type (where XML entities hide) and one over
    1 MB give no box: the image still comes in, NG with the type the sheet gave it, and the report says why."""
    root, w, h = pku_like
    xml = next((root / "Annotations" / "Mouse_bite").glob("*.xml"))
    image = next((root / "images" / "Mouse_bite").glob("*.png"))
    for text, why in (
        (_voc(w + 1, h, ("mouse_bite", 1, 1, 9, 9)), f"made for a {w + 1} x {h} image"),
        (
            '<?xml version="1.0"?><!DOCTYPE a [<!ENTITY e "x">]>' + _voc(w, h, ("mouse_bite", 1, 1, 9, 9)),
            "document type",
        ),
        (_voc(w, h, ("mouse_bite", 1, 1, 9, 9)) + " " * annotation_files.MAX_BYTES, "over 1000 kB"),
    ):
        xml.write_text(text)
        found = annotation_files.read(image, (w, h), root)
        assert found is not None and not found.boxes and why in found.why, found.why
    assert annotation_files.peek(image, root) is not None
    xml.write_text(_voc(w + 1, h, ("mouse_bite", 1, 1, 9, 9)))
    (f,) = [f for f in folder_files(root) if "Mouse_bite" in f.path]
    report = ctx.import_files(BOARD, [f])
    assert len(report.added) == 1 and report.boxes[0][1] == 0 and "made for a" in str(report.boxes[0][2])
    (sample,) = ctx.samples(BOARD)
    assert (sample["label"], sample["defect_type"]) == ("NG", "Mousebite") and not ctx.boxes(sample["uuid"])


def test_req_trn_019_the_sheet_shows_each_file_s_boxes_and_how_many_came_in(
    qtbot: QtBot, ctx: AppContext, pku_like: tuple[Path, int, int]
) -> None:
    """On Training, Import Folder… on the dataset shows each annotated row's type with its count of boxes, and after
    Import each row says how many boxes came in; the row whose box of an unknown class was left out says so."""
    root, _, _ = pku_like
    shutil.rmtree(root / "PCB_USED")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    win.set_user("engineer")
    win._on_board_model(BOARD)
    win.navigate("Training")
    page = win.pages["Training"]
    page.import_from(str(root))
    rows = _rows(page.sheet.table)
    assert [r[TYPE] for r in rows] == ["Pin-hole / Missing Hole · 1 box(es)", "Mousebite · 2 box(es)"]
    page.sheet.start()
    qtbot.waitUntil(lambda: page._bg is None and not page.sheet.running, timeout=60000)
    assert [r[STATUS] for r in _rows(page.sheet.table)] == ["copied with 1 box(es)", "copied with 2 box(es)"]
    assert "label_on_silk" in cell_item(page.sheet.table, 0, STATUS).toolTip()
