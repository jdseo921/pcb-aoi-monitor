"""REQ-INSP-001: an image file is checked by its content and its size before it is decoded (stage S23)."""

from __future__ import annotations

import struct
from pathlib import Path

import cv2
import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from aoi.core.imaging import image_header, load_image
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.test_req_done_in_v01 import _window

FORMATS = (".png", ".jpg", ".bmp", ".tif")


def board(width: int, height: int) -> np.ndarray:
    """A board-like image, a gradient with grid lines, that every format writes and reads quickly."""
    img = np.zeros((height, width, 3), np.uint8)
    img[:, :, 1] = np.linspace(40, 200, width, dtype=np.uint8)[None, :]
    img[:, :, 2] = np.linspace(200, 40, height, dtype=np.uint8)[:, None]
    img[::40, :, :] = 255
    return img


def forged(ext: str, width: int, height: int, order: str = "<") -> bytes:
    """A valid header of each format that claims `width` × `height`, with no pixel data behind it."""
    if ext == ".png":
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr
    if ext == ".bmp":
        return b"BM" + struct.pack("<IHHI", 54, 0, 0, 54) + struct.pack("<Iii", 40, width, -height)
    if ext == ".jpg":
        app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + bytes(9)
        sof2 = b"\xff\xc2" + struct.pack(">HBHHB", 17, 8, height, width, 3) + bytes(9)  # progressive frame
        return b"\xff\xd8" + app0 + sof2
    return tiff(width, height, order)


def tiff(width: int, height: int, order: str = "<", kind: int = 4, big: bool = False) -> bytes:
    """A TIFF header, classic or BigTIFF, in either byte order, whose size tags are of integer type `kind` (LONG by
    default): the first directory holds ImageWidth and ImageLength and nothing else."""
    fmt = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 16: "Q", 17: "q"}[kind]
    values_fmt, value_len = ("Q", 8) if big else ("I", 4)

    def entry(tag: int, value: int) -> bytes:
        field = struct.pack(order + fmt, value).ljust(value_len, b"\x00")  # left-justified in the value field
        return struct.pack(order + "HH" + values_fmt, tag, kind, 1) + field

    if big:
        magic = (b"II+\x00" if order == "<" else b"MM\x00+") + struct.pack(order + "HHQ", 8, 0, 16)
        return magic + struct.pack(order + "Q", 2) + entry(256, width) + entry(257, height) + bytes(8)
    magic = (b"II*\x00" if order == "<" else b"MM\x00*") + struct.pack(order + "I", 8)
    return magic + struct.pack(order + "H", 2) + entry(256, width) + entry(257, height) + bytes(4)


@pytest.fixture(scope="module")
def big(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """One 20 MP (5000 × 4000) file per format, written once for the module."""
    out = tmp_path_factory.mktemp("big")
    img = board(5000, 4000)
    files = {ext: out / f"board_20mp{ext}" for ext in FORMATS}
    for p in files.values():
        assert cv2.imwrite(str(p), img)
    return files


@pytest.mark.parametrize("ext", FORMATS)
def test_req_insp_001_formats_open(tmp_path: Path, big: dict[str, Path], ext: str) -> None:
    """0.3 MP and 20 MP files in each format open at their size, and a lossless format gives every pixel back."""
    small = board(640, 480)
    p = tmp_path / f"board{ext}"
    assert cv2.imwrite(str(p), small)
    got = load_image(p)
    assert got.shape == (480, 640, 3)
    if ext != ".jpg":
        assert np.array_equal(got, small)
    assert load_image(big[ext]).shape == (4000, 5000, 3)


def test_req_insp_001_type_comes_from_the_content_not_the_name(tmp_path: Path) -> None:
    real = tmp_path / "real.png"
    assert cv2.imwrite(str(real), board(64, 48))
    renamed = tmp_path / "board.jpg"  # a PNG under a JPG name opens as the PNG it is
    renamed.write_bytes(real.read_bytes())
    assert image_header(renamed.read_bytes()) == ("PNG", 64, 48)
    assert load_image(renamed).shape == (48, 64, 3)


def test_req_insp_001_non_image_refused(tmp_path: Path) -> None:
    text = tmp_path / "notes.png"
    text.write_text("hello, this is not an image\n" * 100, encoding="utf-8")
    empty = tmp_path / "empty.bmp"
    empty.write_bytes(b"")
    for p in (text, empty):
        with pytest.raises(AoiError) as e:
            load_image(p)
        assert e.value.code == "AOI-INSP-004" and p.name in e.value.what, p.name
    assert image_header(b"BMx\x00\x00\x00\x01\x00\x00\x00" + bytes(40)) is None  # "BM" text, not a bitmap


@pytest.mark.parametrize("ext", FORMATS)
def test_req_insp_001_oversize_refused(tmp_path: Path, ext: str) -> None:
    """A header that claims 64 MP is refused before a pixel is decoded: the file holds nothing but that header, so with
    a higher limit the decoder reports the damage instead. A file over the byte limit is refused by its size on disk."""
    p = tmp_path / f"forged{ext}"
    p.write_bytes(forged(ext, 8000, 8000))
    with pytest.raises(AoiError) as too_big:
        load_image(p)
    assert too_big.value.code == "AOI-INSP-005"
    assert "64.00 MP (8000 × 8000)" in too_big.value.what and "limit of 50 MP" in too_big.value.what
    with pytest.raises(AoiError) as damaged:
        load_image(p, max_megapixels=100)
    assert damaged.value.code == "AOI-INSP-006"
    real = tmp_path / f"real{ext}"
    assert cv2.imwrite(str(real), board(640, 480))
    with pytest.raises(AoiError) as too_many_bytes:
        load_image(real, max_megabytes=0.001)
    assert too_many_bytes.value.code == "AOI-INSP-005" and "limit of 0.001 MB" in too_many_bytes.value.what


def test_req_insp_001_headers_are_read_in_both_tiff_byte_orders() -> None:
    assert image_header(forged(".tif", 5472, 3648, "<")) == ("TIFF", 5472, 3648)
    assert image_header(forged(".tif", 5472, 3648, ">")) == ("TIFF", 5472, 3648)
    assert image_header(forged(".jpg", 5472, 3648)) == ("JPEG", 5472, 3648)
    assert image_header(forged(".bmp", 5472, 3648)) == ("BMP", 5472, 3648)  # stored top-down, height negative
    assert image_header(b"\x89PNG\r\n\x1a\n" + bytes(10)) == ("PNG", 0, 0)  # a cut header: no size, so refused


@pytest.mark.parametrize("kind", [1, 3, 4, 6, 8, 9])
def test_req_insp_001_tiff_size_tags_are_read_in_every_integer_type(kind: int) -> None:
    """libtiff reads ImageWidth and ImageLength from a BYTE, SHORT, LONG, SBYTE, SSHORT or SLONG tag, so the reader does
    too (the S23a review retyped the tags of a 60 MP TIFF as SLONG to slip it past a reader that knew SHORT and LONG),
    in both byte orders, and in a BigTIFF file, whose tags may also be LONG8."""
    for order in "<>":
        assert image_header(tiff(120, 100, order, kind)) == ("TIFF", 120, 100)  # within a SBYTE's 127
        big_kind = kind if kind in (3, 4, 8, 9) else 16  # 5472 fits no BYTE or SBYTE; LONG8 is BigTIFF's own type
        assert image_header(tiff(5472, 3648, order, big_kind, big=True)) == ("TIFF", 5472, 3648)


def test_req_insp_001_headers_are_read_as_the_decoders_read_them(tmp_path: Path) -> None:
    """Where a file can be read in two ways the reader follows the decoder, so no file measures small here and decodes
    large (the S23a review's blocking finding): stray, stuffed and fill bytes between JPEG segments are skipped as
    libjpeg skips them, a bitmap is known by its header size and not by its reserved words, and a negative TIFF size is
    no size."""
    jpg = forged(".jpg", 10000, 6000)
    for junk in (b"\x00", b"\xff\x00", b"\xff\xff", b"junk!"):
        assert image_header(jpg[:20] + junk + jpg[20:]) == ("JPEG", 10000, 6000), junk
    bmp = bytearray(forged(".bmp", 64, 48))
    bmp[6:10] = b"\x01\x00\x02\x00"  # reserved words in use, which OpenCV accepts
    assert image_header(bytes(bmp)) == ("BMP", 64, 48)
    assert image_header(b"BM" + bytes(16)) is None  # "BM" with no bitmap header behind it
    assert image_header(tiff(64, -1, "<", 9)) == ("TIFF", 64, 0)
    real = tmp_path / "stray.jpg"  # the decoder reads such a file, so the reader must measure it
    assert cv2.imwrite(str(real), board(640, 480))
    data = real.read_bytes()
    end = 4 + struct.unpack(">H", data[4:6])[0]  # the end of the first segment
    real.write_bytes(data[:end] + b"\x00" + data[end:])
    assert image_header(real.read_bytes()) == ("JPEG", 640, 480)
    assert load_image(real).shape == (480, 640, 3)
    with pytest.raises(AoiError) as e:
        load_image(real, max_megapixels=0.1)
    assert e.value.code == "AOI-INSP-005"


def test_req_insp_001_a_file_the_reader_cannot_measure_is_refused_not_decoded(tmp_path: Path) -> None:
    """A recognised format whose header gives no size never reaches the decoder, where it would meet no pixel cap."""
    cut = tmp_path / "cut.png"
    cut.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(10))
    with pytest.raises(AoiError) as unmeasured:
        load_image(cut)
    assert unmeasured.value.code == "AOI-INSP-006" and "header holds no image size" in unmeasured.value.what


@pytest.mark.parametrize("ext", FORMATS)
def test_req_insp_001_truncated_file_refused(tmp_path: Path, ext: str) -> None:
    full = tmp_path / f"full{ext}"
    assert cv2.imwrite(str(full), board(640, 480))
    data = full.read_bytes()
    assert image_header(data) == (("JPEG" if ext == ".jpg" else ext[1:4].upper()).replace("TIF", "TIFF"), 640, 480)
    cut = tmp_path / f"cut{ext}"
    cut.write_bytes(data[: len(data) * 3 // 5])
    with pytest.raises(AoiError) as e:
        load_image(cut)
    assert e.value.code == "AOI-INSP-006" and cut.name in e.value.what


def test_req_insp_001_a_bad_file_in_the_queue_shows_its_code_and_the_run_goes_on(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, tmp_path: Path, dialogs: list[tuple[str, str]]
) -> None:
    """The operator reads the code, what happened and what to do; the run stops at the bad board and Next Board carries
    on with the queue, so nothing crashes (REQ-INSP-001, REQ-SET-019)."""
    bad = tmp_path / "board_07.png"
    bad.write_text("a text file under an image name", encoding="utf-8")
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    page._set_queue([bad, ng_board])
    page.start_run()
    qtbot.waitUntil(lambda: len(dialogs) == 1, timeout=10000)
    title, text = dialogs[0]
    assert title.startswith("AOI-INSP-004") and bad.name in text
    assert "read from the file's content, not its name" in text
    assert not page.running and page.last is None
    qtbot.waitUntil(lambda: page.btn_next.isEnabled(), timeout=5000)
    page.next_board()
    qtbot.waitUntil(lambda: page.last is not None, timeout=30000)
    assert page.last_path == ng_board
