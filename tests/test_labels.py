"""REQ-TRN-002 and the data half of REQ-TRN-003 (stage S32): every image is labelled OK, NG or UNSURE with its defect
boxes, a relabel adds rows and keeps the old ones in history, and UNSURE images stay out of training and validation."""

from __future__ import annotations

import io
import re
import sqlite3
import struct
import zlib
from contextlib import closing
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from aoi import defects
from aoi.core import anomaly, imaging, labels
from aoi.core.labels import DefectBox
from aoi.core.services import AppContext
from aoi.data import migrate as mg
from aoi.data.db import Database
from aoi.errors import AoiError
from tests.test_req_done_in_v01 import BOARD, _window

TAIL = "-0000-4000-8000-000000000000"  # the end of a well-formed UUID4
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def exif(order: bytes, *entries: tuple[int, int, int, bytes], magic: int = 42) -> bytes:
    """An EXIF block whose first directory holds these entries, each a tag, a type, a number of values and the 4-byte
    value field: little endian after II, big endian after any other `order`."""
    end = "<" if order == b"II" else ">"
    body = b"".join(struct.pack(end + "HHI", tag, kind, count) + value for tag, kind, count, value in entries)
    return order + struct.pack(end + "HIH", magic, 8, len(entries)) + body + bytes(4)


def orientation(turn: int) -> tuple[int, int, int, bytes]:
    """A big-endian Orientation entry: one SHORT of that value."""
    return 0x0112, 3, 1, struct.pack(">HH", turn, 0)


def app1(data: bytes, name: bytes = b"Exif\0\0") -> bytes:
    """A JPEG APP1 segment holding `data` after its `name`."""
    return b"\xff\xe1" + struct.pack(">H", len(data) + len(name) + 2) + name + data


def chunk(kind: bytes, data: bytes) -> bytes:
    """A PNG chunk of that type with its CRC."""
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def count_reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The size of each read `imaging` makes from a file it opens from now on."""
    read: list[int] = []

    class Counted(io.FileIO):
        def read(self, size: int = -1) -> bytes:
            data = super().read(size)
            read.append(len(data))
            return data

    monkeypatch.setattr(imaging, "open", lambda path, *_, **__: Counted(path), raising=False)
    return read


EXIF6 = exif(b"MM", orientation(6))  # Orientation 6: turned 90°


class Stop(Exception):
    """Raised in place of the training itself, once the test has seen what it was given."""


def _rows(ctx: AppContext) -> tuple[int, int]:
    """How many label rows and box rows the workspace holds, superseded ones included."""
    count = [int(ctx.db.query(f"SELECT COUNT(*) n FROM {t}")[0]["n"]) for t in ("labels", "defect_boxes")]
    return count[0], count[1]


def test_req_trn_002_unsure_excluded(qtbot: QtBot, trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """An image labelled UNSURE is in no list training or validation reads, nor in the Home and Training counts; it is
    listed for the customer's quality engineer with who labelled it and when. Training loads only OK and NG images, and
    the OK images it holds back to calibrate (its validation part) come from those."""
    ctx = trained_ctx
    ok, ng = ctx.samples(BOARD, "OK"), ctx.samples(BOARD, "NG")
    unsure = [ok[-1], ng[-1]]  # not the reference, which is the first OK sample
    for s in unsure:
        assert UUID4.match(ctx.set_label(s["uuid"], "UNSURE"))
    assert [s["uuid"] for s in ctx.samples(BOARD, "OK")] == [s["uuid"] for s in ok[:-1]]
    assert [s["uuid"] for s in ctx.samples(BOARD, "NG")] == [s["uuid"] for s in ng[:-1]]
    status = ctx.board_status(BOARD)
    assert (status.ok_samples, status.ng_samples) == (len(ok) - 1, len(ng) - 1)
    listed = ctx.unsure_samples(BOARD)
    assert [s["uuid"] for s in listed] == [s["uuid"] for s in unsure] and all(s["label"] == "UNSURE" for s in listed)
    assert {(s["labelled_by"], s["labelled_by_name"]) for s in listed} == {(ctx.db.user_uuid("engineer"), "engineer")}
    assert all(s["labelled_at"].endswith("+00:00") and Path(s["path"]).is_absolute() for s in listed)
    loaded: list[str] = []
    seen: dict[str, int] = {}
    real_load = ctx.load_image

    def load(path: str | Path) -> np.ndarray:
        loaded.append(str(path))
        return real_load(path)

    def train(ok_images: list[np.ndarray], ng_images: list[np.ndarray], *a: Any, **k: Any) -> None:
        seen.update(ok=len(ok_images), ng=len(ng_images))
        raise Stop

    monkeypatch.setattr(ctx, "load_image", load)
    monkeypatch.setattr(anomaly, "train", train)
    with pytest.raises(Stop):
        ctx.train(BOARD, epochs=1, image_size=32)
    assert seen == {"ok": len(ok) - 1, "ng": len(ng) - 1}
    assert not {s["path"] for s in unsure} & set(loaded)
    win = _window(qtbot, ctx)
    win.navigate("Training")
    page = win.pages["Training"]
    assert page.counts.text().startswith(f"{len(ok) - 1} OK · {len(ng) - 1} NG · ")  # UNSURE counted as neither


def test_req_trn_003_relabel_keeps_history(trained_ctx: AppContext) -> None:
    """A relabel, a box change and the Training page's Mark OK each add a label row and mark the one before superseded
    by it; the boxes of a label stay with it in history; nothing is deleted or changed in place, and each write is
    audited with the label before and after."""
    ctx = trained_ctx
    sample = ctx.samples(BOARD, "OK")[-1]
    first = ctx.label_history(sample["uuid"])
    assert [(r["label"], r["superseded_by"]) for r in first] == [("OK", None)]  # the import's own row
    assert first[0]["labelled_by"] == ctx.db.user_uuid("engineer")
    a = DefectBox(10, 12, 20, 8, "Solder Bridge")
    b = DefectBox(30, 5, 6, 6, "Scratch")
    rows = _rows(ctx)
    ng = ctx.set_label(sample["uuid"], "NG", "Solder Bridge", [a])
    ctx.set_user("admin")
    moved = ctx.set_boxes(sample["uuid"], [DefectBox(11, 12, 20, 8, "Solder Bridge"), b])
    ctx.set_user("engineer")
    ctx.update_sample(sample["id"], "OK", None)
    history = ctx.label_history(sample["uuid"])  # newest first
    assert [r["label"] for r in history] == ["OK", "NG", "NG", "OK"]
    assert [r["superseded_by"] for r in history] == [None, history[0]["uuid"], moved, ng]
    assert [r["uuid"] for r in history[1:3]] == [moved, ng] and history[3]["uuid"] == first[0]["uuid"]
    assert [r["labelled_by_name"] for r in history[:3]] == ["engineer", "admin", "engineer"]
    assert [[(x["x"], x["dct_type"]) for x in r["boxes"]] for r in history] == [
        [],
        [(11, "Solder Bridge"), (30, "Scratch")],
        [(10, "Solder Bridge")],
        [],
    ]
    assert all(x["superseded_by"] == r["superseded_by"] for r in history for x in r["boxes"])
    assert ctx.boxes(sample["uuid"]) == [] and len(ctx.box_history(sample["uuid"])) == 3
    assert _rows(ctx) == (rows[0] + 3, rows[1] + 3)  # rows added, none removed
    current = next(s for s in ctx.samples(BOARD) if s["uuid"] == sample["uuid"])
    assert (current["label"], current["label_uuid"]) == ("OK", history[0]["uuid"])
    sets = ctx.audit_entries(object_type="sample", object_uuid=sample["uuid"])
    assert [e["action"] for e in sets] == ["sample.update", "label.set", "label.set"]
    assert sets[1]["before"]["label_uuid"] == ng and sets[1]["after"]["label_uuid"] == moved
    assert sets[1]["after"]["boxes"][1] == {"x": 30, "y": 5, "w": 6, "h": 6, "dct_type": "Scratch", "severity": "Minor"}
    with pytest.raises(sqlite3.DatabaseError, match="never changed"):
        ctx.db.execute("UPDATE labels SET label='NG' WHERE uuid=?", (history[0]["uuid"],))
    with pytest.raises(sqlite3.DatabaseError, match="never changed"):
        ctx.db.execute("UPDATE defect_boxes SET superseded_by=NULL WHERE label_uuid=?", (ng,))
    for table in ("labels", "defect_boxes"):
        with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
            ctx.db.execute(f"DELETE FROM {table} WHERE sample_uuid=?", (sample["uuid"],))
    assert _rows(ctx) == (rows[0] + 3, rows[1] + 3)


def test_req_trn_003_severity_matches_dct(trained_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each box stores its position and size, one of the 33 defect types and the severity aoi/defects.py gives that
    type; a box outside the image or not in whole pixels, a type that is not one of the 33 (Anomaly included), and a box
    or defect type on an OK or UNSURE image are refused with a code and nothing is written. An NG image whose own type
    is not one of the 33 (an older label's Anomaly) is refused boxes with a message naming that type and what to do.
    The image's size is read for the boxes before the database is locked, so no file is read while other writes wait."""
    ctx = trained_ctx
    sample = ctx.samples(BOARD, "NG")[-1]
    size = ctx.load_image(sample["path"]).shape  # the image is 640 x 480
    boxes = [DefectBox(i, i, 4, 4, t.name) for i, t in enumerate(defects.DEFECT_TYPES)]
    depth, real = [], labels.image_size
    monkeypatch.setattr(labels, "image_size", lambda path: depth.append(ctx.db._tx_depth) or real(path))
    ctx.set_boxes(sample["uuid"], boxes)
    assert depth == [0]
    stored = ctx.boxes(sample["uuid"])
    assert len(stored) == 33 == len(defects.names())
    assert [(r["x"], r["y"], r["w"], r["h"], r["dct_type"]) for r in stored] == [
        (b.x, b.y, b.w, b.h, b.dct_type) for b in boxes
    ]
    assert [r["severity"] for r in stored] == [defects.BY_NAME[b.dct_type].severity for b in boxes]
    assert {r["severity"] for r in stored} == {"Critical", "Major", "Minor"}
    edge = DefectBox(size[1] - 5, size[0] - 5, 5, 5, "Scratch")
    ctx.set_boxes(sample["uuid"], [edge])  # touching the bottom right corner is inside
    rows, entries = _rows(ctx), ctx.audit_entries()
    refusals: list[tuple[str, list[DefectBox], str]] = [
        ("NG", [DefectBox(size[1] - 5, 0, 6, 5, "Scratch")], "AOI-TRN-031"),
        ("NG", [DefectBox(0, size[0] - 4, 4, 5, "Scratch")], "AOI-TRN-031"),
        ("NG", [DefectBox(-1, 0, 4, 4, "Scratch")], "AOI-TRN-031"),
        ("NG", [DefectBox(0, 0, 0, 4, "Scratch")], "AOI-TRN-031"),
        ("NG", [DefectBox(0, 0, 4, 4, "Anomaly")], "AOI-TRN-030"),
        ("NG", [DefectBox(0, 0, 4, 4, "Smudge")], "AOI-TRN-030"),
        ("NG", [DefectBox(0.5, 0, 4, 4, "Scratch")], "AOI-TRN-030"),
        ("NG", [DefectBox(0, True, 4, 4, "Scratch")], "AOI-TRN-030"),
        ("NG", [DefectBox(0, 0, "4", 4, "Scratch")], "AOI-TRN-030"),
        ("OK", [edge], "AOI-TRN-030"),
        ("UNSURE", [edge], "AOI-TRN-030"),
        ("Maybe", [], "AOI-TRN-030"),
    ]
    for label, given, code in refusals:
        with pytest.raises(AoiError) as refused:
            ctx.set_label(sample["uuid"], label, None, given)
        assert refused.value.code == code, (label, given)
    with pytest.raises(AoiError) as typed:
        ctx.set_label(sample["uuid"], "OK", "Scratch")
    assert typed.value.code == "AOI-TRN-030" and "only an NG image takes" in typed.value.what
    with pytest.raises(AoiError) as outside:
        ctx.set_boxes(sample["uuid"], [edge, DefectBox(size[1] - 5, 0, 6, 5, "Scratch")])
    assert outside.value.code == "AOI-TRN-031" and f"{size[1]} × {size[0]} px" in outside.value.what
    with pytest.raises(AoiError) as gone:
        ctx.set_label("00000000-0000-4000-8000-000000000000", "OK")
    assert gone.value.code == "AOI-TRN-032"
    assert (_rows(ctx), ctx.audit_entries()) == (rows, entries)
    ctx.db.add_label(sample["uuid"], "NG", "Anomaly", [], None)  # as a folder named anomaly once imported it
    with pytest.raises(AoiError) as old:
        ctx.set_boxes(sample["uuid"], [edge])
    assert old.value.code == "AOI-TRN-030" and re.search("defect type, Anomaly, is not .* Mark NG", old.value.what)


def test_req_trn_002_migration_carries_every_label_over(tmp_path: Path) -> None:
    """A workspace from before the labels table keeps every sample's label: the migration writes one current label row
    per sample, with its label and defect type, at the time the sample was added and with no labeller recorded (none
    was); samples.label stays as the import wrote it, and a relabel afterwards adds a row as for any other label."""
    path = tmp_path / "aoi.sqlite"
    files = mg.load_migrations()
    before = next(i for i, m in enumerate(files) if m.name == "labels_and_boxes")
    with closing(sqlite3.connect(path)) as old:
        mg.migrate(old, files[:before])
        for uid, label, dtype in ((f"{'a' * 8}{TAIL}", "OK", None), (f"{'b' * 8}{TAIL}", "NG", "Tombstone")):
            old.execute(
                "INSERT INTO samples(uuid, board_model, path, label, defect_type, side, added_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (uid, "OLD", f"images/OLD/{label}/{uid}.png", label, dtype, "Top", "2026-09-30T01:02:03+00:00"),
            )
        old.commit()
    db = Database(path)
    carried = db.query("SELECT * FROM labels ORDER BY id")
    assert [(r["label"], r["defect_type"], r["labelled_by"], r["at_utc"], r["superseded_by"]) for r in carried] == [
        ("OK", None, None, "2026-09-30T01:02:03+00:00", None),
        ("NG", "Tombstone", None, "2026-09-30T01:02:03+00:00", None),
    ]
    assert all(UUID4.match(r["uuid"]) for r in carried) and db.query("SELECT * FROM defect_boxes") == []
    assert [(s["label"], s["defect_type"], s["label_uuid"]) for s in db.samples("OLD")] == [
        (r["label"], r["defect_type"], r["uuid"]) for r in carried
    ]
    db.add_label(carried[1]["sample_uuid"], "UNSURE", None, [], None)
    assert [s["label"] for s in db.samples("OLD")] == ["OK", "UNSURE"]
    assert db.query("SELECT label FROM samples ORDER BY id") == [{"label": "OK"}, {"label": "NG"}]
    db.close()


def test_req_trn_002_every_sample_has_a_current_label(ctx: AppContext, synthetic_dataset: Path) -> None:
    """An import and Database.add_sample, which every import goes through, store each sample with its current label
    row; every sample read joins that row, so a sample stored without one would leave every list (S31 keeps this)."""
    ctx.import_samples("B", [str(synthetic_dataset / "golden.png")], "OK")
    ctx.db.add_sample("B", "images/B/board.png", "NG", "Scratch")
    orphans = "SELECT s.uuid FROM samples s LEFT JOIN labels l ON l.sample_uuid = s.uuid AND l.superseded_by IS NULL"
    assert ctx.db.query(f"{orphans} WHERE l.id IS NULL") == [] and len(ctx.samples("B")) == 2


def test_req_trn_002_mark_skips_rows_labelled_so(ctx: AppContext) -> None:
    """Mark OK on an OK image, or Mark NG with its own type on an NG image, adds no label row and no audit entry when
    the label has a labeller, so the labeller and any check of it stay; another type is a relabel. A label carried
    over with no labeller is labelled again, with the user acting as its labeller, so it can be checked."""
    me = ctx.user_uuid
    ok = ctx.db.add_sample("B", "images/B/1.png", "OK", labelled_by=me)
    ng = ctx.db.add_sample("B", "images/B/2.png", "NG", "Scratch", labelled_by=me)
    carried = ctx.db.add_sample("B", "images/B/3.png", "OK")  # as migration 0014 carries a label over: no labeller
    before, entries = ctx.samples("B"), ctx.audit_entries()
    ctx.update_sample(ok, "OK", None)
    ctx.update_sample(ng, "NG", "Scratch")
    assert (ctx.samples("B"), ctx.audit_entries()) == (before, entries)
    ctx.update_sample(ng, "NG", "Tombstone")
    ctx.update_sample(carried, "OK", None)
    assert len(ctx.db.label_history(before[1]["uuid"])) == 2
    assert [r["labelled_by"] for r in ctx.db.label_history(before[2]["uuid"])] == [me, None]


def test_req_trn_003_box_coordinates_are_whole_numbers(ctx: AppContext, tmp_path: Path) -> None:
    """A box's position and size are whole numbers: a Python or NumPy integer is stored as an int, in the box rows and
    the audit entry; a bool, a float or a string is refused with AOI-TRN-030, never a raw error."""
    imaging.save_image(tmp_path / "board.png", np.zeros((40, 60, 3), np.uint8))
    ctx.import_samples("B", [str(tmp_path / "board.png")], "NG", "Scratch")
    uid = ctx.samples("B")[0]["uuid"]
    ctx.set_boxes(uid, [DefectBox(np.int64(4), np.int32(2), np.uint8(3), 3, "Scratch")])  # type: ignore[arg-type]
    stored, entry = ctx.boxes(uid)[0], ctx.audit_entries(action="label.set")[-1]["after"]["boxes"][0]
    assert [(type(r[k]), r[k]) for r in (stored, entry) for k in "xywh"] == [(int, 4), (int, 2), (int, 3), (int, 3)] * 2
    for wrong in (np.bool_(True), True, 0.5, np.float64(4.0), "4"):
        with pytest.raises(AoiError) as refused:
            ctx.set_boxes(uid, [DefectBox(wrong, 2, 3, 3, "Scratch")])  # type: ignore[arg-type]
        assert refused.value.code == "AOI-TRN-030", wrong


def test_req_trn_003_box_check_reads_the_header_turned_as_decoded(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A box is checked against the image as the decoder returns it, the one a screen shows: an 800 x 400 JPEG, PNG or
    TIFF whose Orientation (EXIF, a PNG's eXIf, a TIFF's tag 274) is 6 decodes 400 x 800, takes a box in its lower half
    and refuses one past x 400 (AOI-TRN-031) naming that size. OpenCV turns it too for an Orientation given as a LONG
    or with two values, and after stray bytes before the EXIF segment, but not for an eXIf chunk with a wrong CRC, which
    libpng drops, nor in an animated PNG. The size of a file such as this 3.6 MB bitmap is read from its first MiB, not
    the whole file."""
    img, six = np.zeros((400, 800, 3), np.uint8), struct.pack("<HH", 6, 0)
    jpeg, png, tif = cv2.imencode(".jpg", img)[1].tobytes(), cv2.imencode(".png", img)[1].tobytes(), io.BytesIO()
    anim = io.BytesIO()  # an animated PNG: two frames
    Image.fromarray(img).save(anim, "PNG", save_all=True, append_images=[Image.fromarray(255 - img)])
    blocks = (EXIF6, exif(b"II", (274, 4, 1, six)), exif(b"II", (274, 3, 2, six)))  # a SHORT, a LONG, two SHORTs
    app0 = 4 + struct.unpack(">H", jpeg[4:6])[0]  # the end of the JFIF segment after SOI
    exif6 = chunk(b"eXIf", EXIF6)
    Image.fromarray(img).save(tif, "TIFF", tiffinfo={274: 6})
    files = {f"{n}.jpg": jpeg[:2] + app1(e) + jpeg[2:] for n, e in zip(("jpeg", "long", "two"), blocks, strict=True)}
    files |= {"stray.jpg": jpeg[:app0] + b"\0\x13" + app1(EXIF6) + jpeg[app0:], "tiff.tif": tif.getvalue()}
    files |= {"png.png": png[:33] + exif6 + png[33:], "crc.png": png[:33] + exif6[:-4] + bytes(4) + png[33:]}
    files["anim.png"] = anim.getvalue()[:33] + exif6 + anim.getvalue()[33:]
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    ctx.import_samples("B", [str(tmp_path / n) for n in files], "NG", "Scratch")
    seen = {}
    for s in ctx.samples("B"):
        h, w = ctx.load_image(s["path"]).shape[:2]
        refused = []
        for box in (DefectBox(100, 600, 150, 120, "Scratch"), DefectBox(500, 100, 200, 80, "Scratch")):
            try:
                ctx.set_boxes(s["uuid"], [box])
            except AoiError as e:
                refused.append((box.y, e.code, f"{w} × {h} px" in e.what))
        seen[Path(s["path"]).name.split("_")[0]] = (w, h, refused)
    turned, kept = (400, 800, [(100, "AOI-TRN-031", True)]), (800, 400, [(600, "AOI-TRN-031", True)])
    assert seen == {n: turned for n in ("jpeg", "png", "tiff", "long", "two", "stray")} | {"crc": kept, "anim": kept}
    imaging.save_image(tmp_path / "big.bmp", np.zeros((1000, 1200, 3), np.uint8))  # 3.6 MB
    ctx.import_samples("B", [str(tmp_path / "big.bmp")], "NG", "Scratch")
    read = count_reads(monkeypatch)
    ctx.set_boxes(ctx.samples("B")[-1]["uuid"], [DefectBox(1190, 990, 10, 10, "Scratch")])
    assert 0 < sum(read) <= 1 << 20


def test_req_trn_003_orientation_is_read_as_the_decoder_reads_it(tmp_path: Path) -> None:
    """For one file per rule of the Orientation reader, the size `file_header` gives is the size OpenCV decodes, so a
    library upgrade that reads the Orientation otherwise fails here: a block given up at a Make whose value lies past
    it, before its Orientation and after it; magic 43; byte order IM, read big endian; the first APP1 segment with an
    Orientation, after one with Orientation 1, one with none and an XMP one; a segment between two scans of a
    progressive JPEG; a TIFF with tag 274 twice, 6 then 1; a PNG's eXIf after its image data; two eXIf, 1 then 6."""
    img = np.zeros((40, 80, 3), np.uint8)
    jpeg, png = cv2.imencode(".jpg", img)[1].tobytes(), cv2.imencode(".png", img)[1].tobytes()
    prog, tif = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_PROGRESSIVE, 1])[1].tobytes(), io.BytesIO()
    Image.fromarray(img).save(tif, "TIFF", tiffinfo={274: 6})
    tiff, make, six = tif.getvalue(), (0x010F, 2, 20, struct.pack(">I", 5000)), orientation(6)  # 20 bytes at 5000
    at = struct.unpack("<I", tiff[4:8])[0] + 2  # the first entry of the TIFF's directory
    entries = [tiff[i : i + 12] for i in range(at, at + 12 * struct.unpack("<H", tiff[at - 2 : at])[0], 12)]
    entries.insert(1 + [e[:2] for e in entries].index(b"\x12\x01"), struct.pack("<HHIHH", 274, 3, 1, 1, 0))
    tiff += bytes(len(tiff) % 2)  # the directory written again at the end, word aligned, with 274 twice: 6 then 1
    twice = tiff[:4] + struct.pack("<I", len(tiff)) + tiff[8:]
    twice += struct.pack("<H", len(entries)) + b"".join(entries) + bytes(4)
    sos = prog.index(b"\xff\xda", prog.index(b"\xff\xda") + 2)  # the second scan
    segments = {"given_up_before": [exif(b"MM", make, six)], "given_up_after": [exif(b"MM", six, make)]}
    segments |= {"magic_43": [exif(b"MM", six, magic=43)], "order_im": [exif(b"IM", six)]}
    segments |= {"one_then_six": [exif(b"MM", orientation(1)), EXIF6], "none_then_six": [exif(b"MM", make), EXIF6]}
    files = {f"{name}.jpg": jpeg[:2] + b"".join(map(app1, s)) + jpeg[2:] for name, s in segments.items()}
    files["xmp_then_six.jpg"] = jpeg[:2] + app1(b"<x/>", b"http://ns.adobe.com/xap/1.0/\0") + app1(EXIF6) + jpeg[2:]
    files |= {"between_scans.jpg": prog[:sos] + app1(EXIF6) + prog[sos:], "twice.tif": twice}
    end, one = png.rindex(b"IEND") - 4, chunk(b"eXIf", exif(b"MM", orientation(1)))
    files |= {"after_image.png": png[:end] + chunk(b"eXIf", EXIF6) + png[end:]}
    files |= {"one_then_six.png": png[:33] + one + chunk(b"eXIf", EXIF6) + png[33:]}
    wrong: dict[str, object] = {}
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
        decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        header = imaging.file_header(tmp_path / name)
        if decoded is None or header is None or header[1:] != decoded.shape[1::-1]:
            wrong[name] = (header, None if decoded is None else decoded.shape)
    assert wrong == {}


def test_req_trn_003_png_walk_stops_where_libpng_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A PNG's chunks are walked for its eXIf no further than PNG_MAX_CHUNKS, so a file of many empty chunks costs no
    more than that (an eXIf past them is not read, though the decoder reads it), and no further than a chunk libpng
    fails the file at: a type that is not four letters with an upper case third, or a critical chunk it does not know.
    Counted by the 8-byte chunk headers read rather than timed, which on a loaded machine says little."""
    png = cv2.imencode(".png", np.zeros((40, 80, 3), np.uint8))[1].tobytes()
    many = chunk(b"teSt", b"") * (imaging.PNG_MAX_CHUNKS + 1000) + chunk(b"eXIf", EXIF6)
    read, heads = count_reads(monkeypatch), []
    for stop in (b"", chunk(b"te1t", b""), chunk(b"tesT", b""), chunk(b"TEST", b"")):
        (tmp_path / "many.png").write_bytes(png[:33] + stop + many + png[33:])
        read.clear()
        heads.append((imaging.file_header(tmp_path / "many.png"), read.count(8)))
    assert heads == [(("PNG", 80, 40), imaging.PNG_MAX_CHUNKS)] + [(("PNG", 80, 40), 2)] * 3
