"""REQ-INSP-001: an image file is checked by its content and its size before it is decoded (stage S23)."""

from __future__ import annotations

import functools
import io
import json
import struct
import zlib
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import pytest
import tifffile
from PIL import Image
from pytestqt.qtbot import QtBot

from aoi.config import Settings, default_workspace
from aoi.core.imaging import image_header, load_image
from aoi.core.inspector import NG, Inspector, _grade
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.hal import FolderCamera
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.settings import SettingsPage
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
    default): the first directory holds ImageWidth and ImageLength and nothing else. In a classic file the 8 bytes of a
    LONG8 or SLONG8 value follow the directory, where its entry points."""
    fmt = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 16: "Q", 17: "q"}[kind]
    values_fmt, value_len = ("Q", 8) if big else ("I", 4)
    apart = not big and kind in (16, 17)

    def entry(tag: int, value: int, at: int) -> bytes:
        field = struct.pack(order + fmt, value).ljust(value_len, b"\x00")  # left-justified in the value field
        return struct.pack(order + "HH" + values_fmt, tag, kind, 1) + (struct.pack(order + "I", at) if apart else field)

    if big:
        magic = (b"II+\x00" if order == "<" else b"MM\x00+") + struct.pack(order + "HHQ", 8, 0, 16)
        return magic + struct.pack(order + "Q", 2) + entry(256, width, 0) + entry(257, height, 0) + bytes(8)
    magic = (b"II*\x00" if order == "<" else b"MM\x00*") + struct.pack(order + "I", 8)
    values = struct.pack(order + fmt * 2, width, height) if apart else b""  # at 38 and 46, after the directory
    return magic + struct.pack(order + "H", 2) + entry(256, width, 38) + entry(257, height, 46) + bytes(4) + values


@functools.cache
def _black_strip(width: int, height: int) -> bytes:
    """`width` × `height` black RGB pixels as one Deflate strip, compressed row by row: 8000 × 8000 takes 0.19 MB."""
    z = zlib.compressobj()
    return b"".join(z.compress(bytes(width * 3)) for _ in range(height)) + z.flush()


def deflate_tiff(
    sizes: list[tuple[int, int]],
    width: int,
    height: int,
    block: list[tuple[int, int]] | None = None,
    kind: int = 4,
    size_kind: int = 4,
) -> bytes:
    """A little-endian TIFF of `width` × `height` black RGB pixels in one Deflate strip, as the #169 verifier built it:
    its first directory lists the ImageWidth and ImageLength entries `sizes`, (tag, value) in that order, of integer
    type `size_kind`, then the tags a decoder needs, with the RowsPerStrip, TileWidth or TileLength entries `block`
    (RowsPerStrip the height by default) of integer type `kind`, both LONG by default; the 8 bytes of a LONG8 or SLONG8
    value follow BitsPerSample's, those of `block` first, where its entry points. With a tile tag the pixels are
    declared one tile, as the #242 verifiers built it; its bytes are the strip's, since nothing reads them once the
    header check has refused the file."""
    strip = _black_strip(width, height)
    bits_at = 8 + len(strip)  # BitsPerSample's three values follow the strip, then any 8-byte values, the directory
    block = [(278, height)] if block is None else block
    tags, wide = list[tuple[int, int, int, int]](), b""
    for t, k, v in [(t, kind, v) for t, v in block] + [(t, size_kind, v) for t, v in sizes]:
        tags.append((t, k, 1, bits_at + 6 + len(wide) if k in (16, 17) else v))
        wide += struct.pack("<Q", v) if k in (16, 17) else b""
    offsets, counts = (324, 325) if any(t in (322, 323) for t, _ in block) else (273, 279)
    tags += [(258, 3, 3, bits_at), (259, 3, 1, 8), (262, 3, 1, 2)]
    tags += [(offsets, 4, 1, 8), (277, 3, 1, 3), (counts, 4, 1, len(strip)), (284, 3, 1, 1)]
    tags.sort(key=lambda t: t[0])  # in tag order, as a directory is; entries of one tag keep theirs

    def entry(tag: int, kind: int, n: int, value: int) -> bytes:
        field = struct.pack("<HH", value, 0) if kind == 3 and n == 1 else struct.pack("<I", value)  # left-justified
        return struct.pack("<HHI", tag, kind, n) + field

    directory = struct.pack("<H", len(tags)) + b"".join(entry(*t) for t in tags) + bytes(4)
    head = b"II*\x00" + struct.pack("<I", bits_at + 6 + len(wide))
    return head + strip + struct.pack("<HHH", 8, 8, 8) + wide + directory


def scans_jpeg(width: int, height: int, repeats: int, pad: bytes = b"") -> bytes:
    """A progressive JPEG of flat grey saved by Pillow (10 scans), with its last scan, from its start-of-scan marker to
    the end-of-image marker, repeated `repeats` times before that marker, each after the bytes `pad`, as the #242
    verifiers built it: libjpeg warns "Inconsistent progression sequence" and decodes every scan. Each repeat of a flat
    image's last scan is 31 bytes."""
    buf = io.BytesIO()
    Image.fromarray(np.full((height, width, 3), 128, np.uint8)).save(buf, "JPEG", quality=30, progressive=True)
    data = buf.getvalue()
    return data[:-2] + (pad + data[data.rindex(b"\xff\xda") : -2]) * repeats + data[-2:]


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


@pytest.mark.parametrize("kind", [1, 3, 4, 6, 8, 9, 16, 17])
def test_req_insp_001_tiff_size_tags_are_read_in_every_integer_type(kind: int) -> None:
    """libtiff reads ImageWidth and ImageLength from a BYTE, SHORT, LONG, SBYTE, SSHORT, SLONG, LONG8 or SLONG8 tag, so
    the reader does too (the S23a review retyped the tags of a 60 MP TIFF as SLONG to slip it past a reader that knew
    SHORT and LONG), in both byte orders, classic or BigTIFF; in a classic file the 8 bytes of a LONG8 or SLONG8 sit
    where its entry points, which the reader skipped until the #242 review."""
    for order in "<>":
        assert image_header(tiff(120, 100, order, kind)) == ("TIFF", 120, 100)  # within a SBYTE's 127
        big_kind = kind if kind in (3, 4, 8, 9, 16, 17) else 16  # 5472 fits no BYTE or SBYTE
        assert image_header(tiff(5472, 3648, order, big_kind, big=True)) == ("TIFF", 5472, 3648)


def test_req_insp_001_headers_are_read_as_the_decoders_read_them(tmp_path: Path) -> None:
    """Where a file can be read in two ways the reader follows the decoder, so the size measured here is the size of the
    image decoded (the S23a review's blocking finding): stray, stuffed and fill bytes between JPEG segments are skipped
    as libjpeg skips them, a bitmap is known by its header size and not by its reserved words, and a negative TIFF size
    is no size. The decoder's work is bounded by the scan and tile checks (#242), tested below."""
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


def test_req_insp_001_a_tiff_that_gives_its_size_twice_is_refused(tmp_path: Path) -> None:
    """libtiff reads the first of two ImageWidth or ImageLength entries and ignores the rest, and this reader took the
    last, so the #169 verifier's 0.19 MB TIFF, listing 8000 then 10 for each, measured 10 × 10 here and decoded to
    8000 × 8000 (192 MB) past the 50 MP limit. A size tag given twice, in either order, is now refused as damaged before
    anything is decoded; the same file listing each size once is measured, and refused by the limit."""
    twice = {
        "first_large": [(256, 8000), (256, 10), (257, 8000), (257, 10)],  # the verifier's file
        "first_small": [(256, 10), (256, 8000), (257, 10), (257, 8000)],
        "width_only": [(256, 8000), (256, 10), (257, 8000)],
    }
    for name, sizes in twice.items():
        p = tmp_path / f"{name}.tif"
        p.write_bytes(deflate_tiff(sizes, 8000, 8000))
        assert image_header(p.read_bytes()) == ("TIFF", 0, 0), name
        with pytest.raises(AoiError) as damaged:
            load_image(p)
        assert damaged.value.code == "AOI-INSP-006" and p.name in damaged.value.what, name
    once = tmp_path / "once.tif"
    once.write_bytes(deflate_tiff([(256, 8000), (257, 8000)], 8000, 8000))
    assert image_header(once.read_bytes()) == ("TIFF", 8000, 8000)
    with pytest.raises(AoiError) as over:
        load_image(once)
    assert over.value.code == "AOI-INSP-005" and "64.00 MP (8000 × 8000)" in over.value.what


SIZE_64 = [(256, 64), (257, 64)]
TWICE = "it gives the size of its tiles or strips twice"
TILE = "its tiles are 16000 × 16000 px, more than its 64 × 64 px image needs"
ROWS = "its strips are 64 × 100000 px, more than its 64 × 64 px image needs"
COSTLY = {  # file: (what builds it, what AOI-INSP-006 says of it); the 4000 × 4000 JPEG is built when its case runs
    "scans.jpg": (lambda: scans_jpeg(4000, 4000, 2000), "it holds 2,010 scans, more than the 100 this app decodes"),
    "tile16000.tif": (lambda: deflate_tiff(SIZE_64, 64, 64, [(322, 16000), (323, 16000)]), TILE),
    "rows100000.tif": (lambda: deflate_tiff(SIZE_64, 64, 64, [(278, 100_000)]), ROWS),
    # the #242 review's files: LONG8 and SLONG8 in a classic file, which the reader skipped and libtiff reads
    "tile16000_long8.tif": (lambda: deflate_tiff(SIZE_64, 64, 64, [(322, 16000), (323, 16000)], kind=16), TILE),
    "tile16000_slong8.tif": (lambda: deflate_tiff(SIZE_64, 64, 64, [(322, 16000), (323, 16000)], kind=17), TILE),
    "rows100000_long8.tif": (lambda: deflate_tiff(SIZE_64, 64, 64, [(278, 100_000)], kind=16), ROWS),
    "tile_twice.tif": (lambda: deflate_tiff(SIZE_64, 64, 64, [(322, 256), (322, 256), (323, 256)]), TWICE),
    "rows_twice.tif": (lambda: deflate_tiff(SIZE_64, 64, 64, [(278, 64), (278, 64)]), TWICE),
}


@pytest.mark.parametrize("name", COSTLY)
def test_req_insp_001_a_file_that_costs_the_decoder_far_more_than_its_image_is_refused_before_decoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """#242: a progressive 4000 × 4000 JPEG with its last scan repeated 2,000 times (0.16 MB) passed every check and
    held the decoder about 20 s, and a 64 × 64 TIFF declaring one 16000 × 16000 tile took about 1 GB to decode, since
    the checks bounded the image's size and not the decoder's work; a strip far taller than its image, and a tile or
    strip tag given twice (libtiff reads the first), passed too. So did the tile and the strip given as LONG8 or SLONG8
    in a classic file (the #242 review), which the reader skipped and libtiff reads where the entry points. Each is now
    refused with AOI-INSP-006 by its scans, its tile or its strip before cv2.imdecode is called. The decoder is patched
    to fail the test, so the code before fails at once rather than decoding for 20 s or taking 1 GB."""

    def no_decode(buf: np.ndarray, flags: int) -> np.ndarray:
        pytest.fail(f"cv2.imdecode was called for {name} ({len(buf):,} bytes)")

    monkeypatch.setattr(cv2, "imdecode", no_decode)
    build, reason = COSTLY[name]
    p = tmp_path / name
    p.write_bytes(build())
    with pytest.raises(AoiError) as refused:
        load_image(p)
    print(name, f"{p.stat().st_size:,} bytes:", refused.value.what)
    assert refused.value.code == "AOI-INSP-006" and p.name in refused.value.what and reason in refused.value.what


def test_req_insp_001_scans_are_counted_as_libjpeg_reaches_them(tmp_path: Path) -> None:
    """libjpeg reads a JPEG from marker to marker up to its first end-of-image marker, and the scan count follows it
    (the #242 review): start-of-scan bytes after that marker (where a phone's motion photo keeps its video) or inside
    another segment (an EXIF thumbnail's scans) are no scans of the image, while stray, stuffed, restart and fill bytes
    or segments between the scans hide none, past JPEG_MAX_MARKERS markers too. Counting every FF DA in the file
    refused the first two files as holding 201 scans."""
    data = cv2.imencode(".jpg", board(640, 480))[1].tobytes()  # baseline: one scan
    files = {
        "after.jpg": data + b"\xff\xda" * 200,
        "inside.jpg": data[:2] + b"\xff\xfe" + struct.pack(">H", 402) + b"\xff\xda" * 200 + data[2:],  # in a comment
    }
    for name, crafted in files.items():
        (tmp_path / name).write_bytes(crafted)
        assert load_image(tmp_path / name).shape == (480, 640, 3), name
    for n, pad in enumerate((b"junk\xff\x00\xff\xd0\xff\xfe\x00\x04ab\xff\xff", b"\xff\xfe\x00\x02" * 800)):
        (tmp_path / f"between{n}.jpg").write_bytes(scans_jpeg(640, 480, 91, pad))
        with pytest.raises(AoiError) as e:
            load_image(tmp_path / f"between{n}.jpg")
        assert "it holds 101 scans, more than the 100" in e.value.what, n


def test_req_insp_001_progressive_jpegs_and_tiled_or_one_strip_tiffs_still_open(tmp_path: Path) -> None:
    """The scan, tile and strip checks of #242 leave ordinary files alone: a progressive JPEG saved by Pillow (10
    scans), a 64 × 64 TIFF written by tifffile with 256 × 256 tiles (TIFF 6.0 makes tile sides multiples of 16, so a
    small image has a tile larger than itself) and a strip TIFF whose RowsPerStrip is the TIFF default 4,294,967,295,
    one strip for the whole image, open at their size; the TIFFs give every pixel back. This passed before the fix
    too: it guards against a bound that refuses too much."""
    img = board(640, 480)
    Image.fromarray(np.ascontiguousarray(img[:, :, ::-1])).save(tmp_path / "progressive.jpg", progressive=True)
    tile = tmp_path / "tiled.tif"
    tifffile.imwrite(tile, np.ascontiguousarray(img[:64, :64, ::-1]), tile=(256, 256))
    one_strip = tmp_path / "one_strip.tif"
    one_strip.write_bytes(deflate_tiff([(256, 640), (257, 480)], 640, 480, [(278, 0xFFFFFFFF)]))
    assert (tmp_path / "progressive.jpg").read_bytes().count(b"\xff\xda") == 10
    assert load_image(tmp_path / "progressive.jpg").shape == (480, 640, 3)
    assert np.array_equal(load_image(tile), img[:64, :64])
    assert np.array_equal(load_image(one_strip), np.zeros((480, 640, 3), np.uint8))


def test_req_insp_001_a_classic_tiff_s_8_byte_tags_are_read_where_their_entries_point(tmp_path: Path) -> None:
    """The 8 bytes of a LONG8 or SLONG8 value fit no entry of a classic TIFF, and libtiff reads them at the offset the
    entry holds (TIFFReadDirEntryCheckedLong8), which the reader skipped until the #242 review. A file giving its size
    in either type, its entries holding the offsets of 640 and 480 and not the sizes, was refused as giving no size;
    it is now measured at 640 × 480 and opens pixel for pixel, so it is judged. A RowsPerStrip of 480 given as a LONG8
    opens; the same file with 0 at the entry's offset is refused by the decoder ("Bad value 0 for RowsPerStrip"), while
    one whose RowsPerStrip is that offset itself opens: so libtiff reads the bytes the entry points to, not the entry,
    as the reader now does."""

    def pointed(data: bytes, tag: int) -> tuple[int, int]:
        """The 4-byte field of `tag`'s entry in the first directory, and the 8 bytes at that offset as a number."""
        at = struct.unpack_from("<I", data, 4)[0]
        entries = (
            struct.unpack_from("<HHII", data, at + 2 + 12 * n) for n in range(struct.unpack_from("<H", data, at)[0])
        )
        field = next(f for t, _, _, f in entries if t == tag)
        return field, struct.unpack_from("<Q", data, field)[0]

    black = np.zeros((480, 640, 3), np.uint8)
    for size_kind in (16, 17):
        data = deflate_tiff([(256, 640), (257, 480)], 640, 480, size_kind=size_kind)
        (width_at, width), (height_at, height) = pointed(data, 256), pointed(data, 257)
        assert (width, height) == (640, 480) and {width_at, height_at}.isdisjoint({640, 480}), (width_at, height_at)
        assert image_header(data) == ("TIFF", 640, 480)
        (tmp_path / f"size{size_kind}.tif").write_bytes(data)
        assert np.array_equal(load_image(tmp_path / f"size{size_kind}.tif"), black), size_kind
    at = pointed(deflate_tiff([(256, 640), (257, 480)], 640, 480, [(278, 480)], kind=16), 278)[0]
    for rows in (480, 0, at):
        data = deflate_tiff([(256, 640), (257, 480)], 640, 480, [(278, rows)], kind=16)
        assert pointed(data, 278) == (at, rows)
        (tmp_path / f"rows{rows}.tif").write_bytes(data)
    assert np.array_equal(load_image(tmp_path / "rows480.tif"), black)
    assert np.array_equal(load_image(tmp_path / f"rows{at}.tif"), black)
    with pytest.raises(AoiError) as zero:
        load_image(tmp_path / "rows0.tif")
    assert zero.value.code == "AOI-INSP-006" and "it is cut short, damaged" in zero.value.what


def test_req_insp_001_the_scan_tile_and_strip_bounds_sit_at_their_values(tmp_path: Path) -> None:
    """The bounds of #242 where they lie: a JPEG of 100 scans opens and one of 101 is refused; a tile or strip may hold
    up to the larger of 1024 × 1024 px and the image with each side rounded up to a multiple of 16, and one more row or
    column is refused. Before the fix every one of these files was decoded, so the refusals fail on that code."""
    files = {
        "scans100.jpg": scans_jpeg(640, 480, 90),
        "scans101.jpg": scans_jpeg(640, 480, 91),
        "rows16384.tif": deflate_tiff(SIZE_64, 64, 64, [(278, 16384)]),  # 64 × 16384 = 1024 × 1024 px
        "rows16385.tif": deflate_tiff(SIZE_64, 64, 64, [(278, 16385)]),
        "rows1504.tif": deflate_tiff([(256, 2000), (257, 1500)], 2000, 1500, [(278, 1504)]),  # 1500 rounds up to 1504
        "rows1505.tif": deflate_tiff([(256, 2000), (257, 1500)], 2000, 1500, [(278, 1505)]),
    }
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    small = np.ascontiguousarray(board(64, 64)[:, :, ::-1])
    tifffile.imwrite(tmp_path / "tile1024.tif", small, tile=(1024, 1024))
    tifffile.imwrite(tmp_path / "tile1040.tif", small, tile=(1040, 1024))
    shapes = {"scans100.jpg": (480, 640, 3), "rows1504.tif": (1500, 2000, 3)}
    for name in ("scans100.jpg", "rows16384.tif", "rows1504.tif", "tile1024.tif"):
        assert load_image(tmp_path / name).shape == shapes.get(name, (64, 64, 3)), name
    refused = {
        "scans101.jpg": "it holds 101 scans, more than the 100 this app decodes",
        "rows16385.tif": "its strips are 64 × 16385 px",
        "rows1505.tif": "its strips are 2000 × 1505 px, more than its 2000 × 1500 px image needs",
        "tile1040.tif": "its tiles are 1024 × 1040 px",  # tifffile's tile is (length, width)
    }
    for name, reason in refused.items():
        with pytest.raises(AoiError) as e:
            load_image(tmp_path / name)
        assert e.value.code == "AOI-INSP-006" and reason in e.value.what, (name, e.value.what)


def test_req_insp_001_an_image_too_small_to_inspect_is_refused_and_no_number_grades_ng() -> None:
    """Under 7 px a side SSIM is the mean of nothing, NaN, which every threshold comparison let pass as OK, and a 1 px
    side broke ORB with a bare cv2.error (#169). The engine now refuses a board image or a golden board with a side
    under 11 px (one 7 px SSIM window, and 3 px of difference map inside its 4 px border for the noise clean-up to
    keep a pixel) with AOI-INSP-011 before any work, and a check value that is no number, NaN or infinite, grades NG
    whichever way its threshold points."""
    rng = np.random.default_rng(0)
    big = rng.integers(0, 255, (400, 600, 3), dtype=np.uint8)
    for board, golden, refused in (
        (big, rng.integers(0, 255, (6, 400, 3), dtype=np.uint8), "The Golden board is 400 × 6 px"),  # SSIM was NaN
        (rng.integers(0, 255, (1, 50, 3), dtype=np.uint8), big, "The board image is 50 × 1 px"),  # ORB broke
        (rng.integers(0, 255, (400, 10, 3), dtype=np.uint8), big, "The board image is 10 × 400 px"),
    ):
        with pytest.raises(AoiError) as small:
            Inspector(Recipe(board_model="B", use_ai=False), reference=golden).inspect(board)
        assert small.value.code == "AOI-INSP-011" and small.value.what.startswith(refused), small.value.what
        assert "at least 11 px on each side" in small.value.what
    golden = rng.integers(0, 255, (11, 11, 3), dtype=np.uint8)  # the smallest board judged: every check sees pixels
    res = Inspector(Recipe(board_model="B", use_ai=False), reference=golden).inspect(np.zeros_like(golden))
    assert res.verdict == NG and all(np.isfinite(c.value) for c in res.checks)
    assert res.compare is not None and res.compare.metrics["changed_pct"] > 0
    for value in (float("nan"), float("inf"), float("-inf")):
        assert _grade(value, 0.8, 0.9) == _grade(value, 0.8, 0.9, higher_is_bad=False) == NG, value


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


def test_req_insp_001_limits_come_from_settings(ctx: AppContext, tmp_path: Path) -> None:
    assert (Settings().max_image_megapixels, Settings().max_image_megabytes) == (50, 200)
    small, mid = tmp_path / "small.png", tmp_path / "mid.png"
    assert cv2.imwrite(str(small), board(640, 480)) and cv2.imwrite(str(mid), board(1280, 1024))
    ctx.settings.max_image_megapixels = 1
    assert ctx.load_image(small).shape == (480, 640, 3)
    with pytest.raises(AoiError) as e:
        ctx.load_image(mid)
    assert e.value.code == "AOI-INSP-005" and "limit of 1 MP" in e.value.what
    assert "1.31 MP (1280 × 1024)" in e.value.what
    ctx.settings.max_image_megabytes = 0
    with pytest.raises(AoiError) as by_size:
        ctx.load_image(small)
    assert by_size.value.code == "AOI-INSP-005" and "limit of 0 MB" in by_size.value.what


def test_req_insp_001_a_setting_of_the_wrong_type_is_refused_at_start_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo in settings.json used to fail every image load with AOI-SET-007 (the S23a review, finding 5); now
    `Settings.load` refuses the file with AOI-SET-008, naming the setting and what it must be, before the app starts,
    and an unknown key is still ignored."""
    monkeypatch.setenv("AOI_WORKSPACE", str(tmp_path))
    f = tmp_path / "settings.json"
    cases = (
        ("max_image_megapixels", '"50"', "a whole number above 0"),
        ("max_image_megabytes", "0", "a whole number above 0"),
        ("map_retention_days_ok", "-1", "a whole number of 0 or more"),
        ("image_size", "1.5", "a whole number"),
        ("default_epochs", "true", "a whole number"),
        ("language", "1", "text"),
    )
    for name, value, expected in cases:
        f.write_text("{" + f'"{name}": {value}' + "}", encoding="utf-8")
        with pytest.raises(AoiError) as e:
            Settings.load()
        assert e.value.code == "AOI-SET-008" and f"setting {name} is {value}" in e.value.what, name
        assert f"must be {expected}" in e.value.what, name
    f.write_text('{"max_image_megapixels": 80, "unknown_key": true}', encoding="utf-8")
    assert Settings.load().max_image_megapixels == 80


def test_req_set_019_an_empty_or_relative_workspace_and_a_count_below_1_are_refused(
    qtbot: QtBot, ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """settings.json with an empty, blank or relative workspace, or a log retention, input size or epoch count below 1,
    is refused at start-up with AOI-SET-008 (#170): "" opened a new, empty workspace in whatever folder the app was
    started from, and a retention of -1 days archived every record. The Settings page checks before it saves and shows
    the same code, writing nothing."""
    f = default_workspace() / "settings.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    cases = [("workspace", v) for v in ("", "   ", "relative/folder")]
    cases += [("log_retention_days", 0), ("log_retention_days", -1), ("image_size", 0), ("default_epochs", 0)]
    for name, value in cases:
        f.write_text(json.dumps({name: value}), encoding="utf-8")
        with pytest.raises(AoiError) as e:
            Settings.load()
        assert e.value.code == "AOI-SET-008" and f"setting {name} is {json.dumps(value)}" in e.value.what, name
    f.unlink()
    win = MainWindow(ctx)  # an empty workspace opens as Admin
    qtbot.addWidget(win)
    page, open_workspace = cast(SettingsPage, win.pages["Settings"]), ctx.settings.workspace
    page.ws.setText("")
    page.save()
    assert dialogs[-1][0] == "AOI-SET-008 Setting invalid" and "On the Settings page" in dialogs[-1][1]
    assert not f.exists() and ctx.settings.workspace == open_workspace


def test_req_set_019_a_relative_aoi_workspace_never_stops_the_next_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With a relative AOI_WORKSPACE and no settings.json yet, the first write (the page change's last_page) wrote the
    relative workspace into settings.json, so every later start stopped with AOI-SET-008 (#170 review): the default
    workspace is now made absolute where it is read."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AOI_WORKSPACE", "relative_ws")
    Settings().save_keys({"last_page": "Logs & Export"})
    saved = Settings.load()
    assert saved.workspace == str(tmp_path / "relative_ws") and saved.last_page == "Logs & Export"


@pytest.mark.parametrize("given", ["relative_ws", "~/ws", "C:AOI_Workspace", "..\\up"])
def test_req_set_019_every_form_of_aoi_workspace_gives_a_workspace_settings_json_accepts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, given: str
) -> None:
    """AOI_WORKSPACE relative, under ~, drive-relative ("C:AOI_Workspace", which Path.absolute() on Python 3.11 left
    relative on Windows) or with "..": the workspace the app uses is a full path that settings.json accepts (#170
    review). On Linux "C:AOI_Workspace" is a plain relative folder name."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AOI_WORKSPACE", given)
    Settings.check("workspace", str(default_workspace()))
    assert Settings().root == default_workspace()


def test_req_set_019_the_first_settings_json_write_refuses_settings_the_next_start_would_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no settings.json yet, the first key-only write wrote every setting the app holds; one the next start
    refuses, such as a relative workspace, is now refused with AOI-SET-008 and nothing is written (#170 review)."""
    monkeypatch.setenv("AOI_WORKSPACE", str(tmp_path))
    with pytest.raises(AoiError) as refused:
        Settings(workspace="relative_ws").save_keys({"last_page": "Logs & Export"})
    assert refused.value.code == "AOI-SET-008" and not (tmp_path / "settings.json").exists()
    Settings().save_keys({"last_page": "Logs & Export"})
    assert Settings.load().last_page == "Logs & Export"


def test_req_insp_001_the_decoder_limits_are_refused_with_a_code(tmp_path: Path) -> None:
    """A side over the decoder's 1,048,576 px is refused by the header (AOI-INSP-007), whatever the pixel limit says,
    and should the decoder refuse a file by its own limits the operator reads a coded message, not an unexpected
    error."""
    strip = tmp_path / "strip.bmp"
    strip.write_bytes(forged(".bmp", 1_100_000, 1))  # 1.1 MP, within the pixel limit
    with pytest.raises(AoiError) as side:
        load_image(strip)
    assert side.value.code == "AOI-INSP-007" and "1100000 × 1 px" in side.value.what and "1,048,576" in side.value.what
    huge = tmp_path / "huge.bmp"  # a complete 54-byte header for 1,600 MP, over the decoder's own 2^30 pixel limit
    dib = struct.pack("<IiiHHIIiiII", 40, 40000, -40000, 1, 24, *[0] * 6)
    huge.write_bytes(b"BM" + struct.pack("<IHHI", 54, 0, 0, 54) + dib)
    with pytest.raises(AoiError) as refused:
        load_image(huge, max_megapixels=2000)
    assert refused.value.code == "AOI-INSP-006" and "the decoder refused it" in refused.value.what


def test_req_insp_001_files_from_other_writers_are_measured(tmp_path: Path) -> None:
    """Files as cameras and image tools write them, not only as OpenCV does: a JPEG with an EXIF segment ahead of the
    frame, a bitmap from Pillow, a big-endian TIFF and a BigTIFF from tifffile all measure 640 × 480 and open (Pillow
    and tifffile are development dependencies only)."""
    rgb = np.ascontiguousarray(board(640, 480)[:, :, ::-1])
    exif = Image.Exif()
    exif[0x010F] = "AOI test camera"  # the Make tag: an APP1 segment before the frame, as cameras write
    Image.fromarray(rgb).save(tmp_path / "exif.jpg", exif=exif.tobytes(), quality=90)
    Image.fromarray(rgb).save(tmp_path / "pil.bmp")
    tifffile.imwrite(tmp_path / "be.tif", rgb, byteorder=">")
    tifffile.imwrite(tmp_path / "big.tif", rgb, bigtiff=True)
    for name, fmt in (("exif.jpg", "JPEG"), ("pil.bmp", "BMP"), ("be.tif", "TIFF"), ("big.tif", "TIFF")):
        p = tmp_path / name
        assert image_header(p.read_bytes()) == (fmt, 640, 480), name
        assert load_image(p).shape == (480, 640, 3), name


def test_req_insp_001_the_folder_camera_grabs_under_the_same_limits(tmp_path: Path) -> None:
    """The Stage 1 camera reads a file with the limits it is given, so a wired camera cannot skip the settings."""
    p = tmp_path / "board.png"
    assert cv2.imwrite(str(p), board(640, 480))
    cam = FolderCamera.from_folder(tmp_path, max_megapixels=0.1)
    cam.open()
    with pytest.raises(AoiError) as e:
        cam.grab()
    assert e.value.code == "AOI-INSP-005" and "limit of 0.1 MP" in e.value.what
    plain = FolderCamera([p])
    plain.open()
    frame = plain.grab()
    assert frame is not None and frame.shape == (480, 640, 3) and plain.grab() is None


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
