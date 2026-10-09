"""Image I/O and registration helpers (OpenCV)."""

from __future__ import annotations

import hashlib
import io
import re
import struct
import zlib
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np

from ..data import atomic
from ..errors import QT_TRANSLATE_NOOP, AoiError, Phrase

Reader = Callable[[Path], bytes]  # a file's bytes as the image checks see them

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
# Limits an image must stay within to be decoded (REQ-INSP-001), at the register's proposed values; a station's own
# values live in Settings and reach here through AppContext.load_image.
MAX_MEGAPIXELS = 50
MAX_MEGABYTES = 200
HEADER_BYTES = 1 << 20  # what `file_header` reads first: a PNG, BMP or JPEG header lies well inside it
MAX_SIDE = 1 << 20  # a side longer than this is beyond the decoder (OpenCV's CV_IO_MAX_IMAGE_WIDTH and _HEIGHT)
BMP_HEADER_SIZES = {12, 16, 40, 52, 56, 64, 108, 124}  # BITMAPCOREHEADER to BITMAPV5HEADER: how a bitmap is known
JPEG_FRAME_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
JPEG_BARE_MARKERS = {0x00, 0x01, 0xD8, *range(0xD0, 0xD8)}  # no length field follows: a stuffed byte, TEM, SOI, RSTn
JPEG_MAX_MARKERS = 65536  # more markers than any camera writes: past it a walk gives up
JPEG_FILL = re.compile(rb"\xff+")
PNG_MAX_CHUNKS = 65536  # more chunks than a writer makes (about 7,330 in a 20 MP PNG): past it a walk gives up
PNG_CRITICAL = (b"IHDR", b"PLTE", b"IDAT")  # the critical chunks libpng knows before IEND
# The entries of an EXIF block's first directory that OpenCV 5.0's ExifReader reads before its Orientation, giving up on
# the block at the first whose value lies past the block's end: text (ImageDescription, Make, Model, Software, DateTime,
# Copyright), a 16-bit value (ResolutionUnit, YCbCrPositioning) and rationals by how many it reads (XResolution,
# YResolution, WhitePoint, PrimaryChromaticities, YCbCrCoefficients, ReferenceBlackWhite)
EXIF_TEXT = (0x010E, 0x010F, 0x0110, 0x0131, 0x0132, 0x8298)
EXIF_SHORT = (0x0128, 0x0213)
EXIF_RATIONALS = {0x011A: 1, 0x011B: 1, 0x013E: 2, 0x013F: 6, 0x0211: 3, 0x0214: 6}
# libjpeg's progression writes 10 scans for a colour image, and its decoder reads every scan a file holds; libtiff stops
# a JPEG inside a TIFF at the same 100 scans by default (LIBTIFF_JPEG_MAX_ALLOWED_SCAN_NUMBER)
JPEG_MAX_SCANS = 100
# The markers libjpeg acts on in `_jpeg_scans`: EOI (D9) and SOS (DA), and the segments it reads by their length and
# goes on from (SOF0-3 and 9-11, DHT, DAC, DQT, DNL, DRI, APPn, COM). Any other pair is stuffing, fill, a restart or a
# marker libjpeg fails at or searches past, so the walk searches past it too and skips no byte libjpeg reads.
JPEG_WALK = re.compile(rb"\xff([\xc0-\xc4\xc9-\xcc\xd9-\xdd\xe0-\xef\xfe])")
TIFF_INT_TYPES = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 16: "Q", 17: "q"}  # BYTE to SLONG8: a size's types
TIFF_BLOCK_TAGS = (278, 322, 323)  # RowsPerStrip, TileWidth, TileLength: the size of a strip or tile
# with ImageWidth, ImageLength, Compression, SamplesPerPixel, PlanarConfiguration, ImageDepth, TileDepth and Orientation
TIFF_TAGS = (256, 257, *TIFF_BLOCK_TAGS, 259, 277, 284, 32997, 32998, 274)
TIFF_FIRST = (277, 32997, 32998, 274)  # SamplesPerPixel, ImageDepth, TileDepth, Orientation: libtiff reads the first
TIFF_TWICE = -1  # what `_tiff_tags` gives a tag listed twice, or a Compression given per sample: no single value
# StripOffsets and TileOffsets fill libtiff's one list of where the strips or tiles start (0), StripByteCounts and
# TileByteCounts its list of the bytes each holds (1); the values are read unsigned, as libtiff refuses a negative one
TIFF_LISTS = {273: 0, 324: 0, 279: 1, 325: 1}
TIFF_LIST_TYPES = {1: "u1", 3: "u2", 4: "u4", 6: "u1", 8: "u2", 9: "u4", 16: "u8", 17: "u8"}
TIFF_WHOLE_SIDE = (0, 0xFFFFFFFF)  # a RowsPerStrip of 0, or the TIFF default 4,294,967,295, reads as the image height
TIFF_BLOCK_PIXELS = 1024 * 1024  # a tile or strip may always hold this many pixels, however small the image
# The most strips or tiles a TIFF may have (`_tiff_count`), fixed, though libtiff takes up to 65,535 samples a pixel:
# one-row strips of the tallest image (MAX_SIDE rows) in four planes, RGB with alpha or CMYK stored plane by plane;
# tiles of 16 × 16 px, TIFF 6.0's smallest, number about 196,000 a plane in 50 MP and 782,000 in 200 MP
TIFF_MAX_BLOCKS = 4 * MAX_SIDE


def image_header(data: bytes) -> tuple[str, int, int] | None:
    """(format, width, height) of a PNG, JPEG, BMP or TIFF file read from its bytes, never from its name; None for
    anything else. Only the header is read, so a file is measured before any pixel is decoded. Wherever a file can be
    read in two ways the readers follow the decoders (libjpeg, libtiff, OpenCV's bitmap reader), so the size measured
    here is the size of the image the decoder returns; it bounds the image, not the decoder's work, which `load_image`
    bounds by a JPEG's scans and a TIFF's tiles and strips and the bytes they take (#242). A recognised format whose
    size still cannot be read gives width and height 0, and `load_image` refuses it rather than hand it to the
    decoder."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        if len(data) < 24 or data[12:16] != b"IHDR":
            return "PNG", 0, 0
        w, h = struct.unpack(">II", data[16:24])
        return "PNG", int(w), int(h)
    if data[:2] == b"BM" and len(data) >= 18 and (dib := struct.unpack("<I", data[14:18])[0]) in BMP_HEADER_SIZES:
        if len(data) < 26:
            return "BMP", 0, 0
        if dib == 12:  # the 12-byte OS/2 header holds 16-bit sizes
            w, h = struct.unpack("<HH", data[18:22])
            return "BMP", int(w), int(h)
        w, h = struct.unpack("<ii", data[18:26])
        return "BMP", int(w), abs(int(h))  # a negative height means the rows run top-down
    if data[:3] == b"\xff\xd8\xff":
        return _jpeg_header(data)
    if data[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return _tiff_header(data)
    return None


def _jpeg_segments(data: bytes) -> Iterator[tuple[int, int]]:
    """Each marker after a JPEG's SOI, up to its scan or its end, as (marker, index of its 0xFF), found as libjpeg finds
    it: bytes between segments that belong to no marker are skipped ("extraneous bytes before marker"), and so are fill
    bytes, so a stray byte cannot hide a segment from these readers while the decoder still reads it."""
    i = 2
    for _ in range(JPEG_MAX_MARKERS):
        i = data.find(b"\xff", i)
        if i < 0:
            return
        fill = JPEG_FILL.match(data, i)
        i = fill.end() - 1 if fill else i  # fill bytes: the marker byte follows the last 0xFF
        if i + 2 > len(data):
            return
        marker = data[i + 1]
        yield marker, i
        if marker in (0xD9, 0xDA):  # end of image, or the scan data
            return
        if marker in JPEG_BARE_MARKERS:
            i += 2
        elif i + 4 <= len(data):
            i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
        else:
            return


def _jpeg_header(data: bytes) -> tuple[str, int, int]:
    """The size the first start-of-frame segment holds, walked to by `_jpeg_segments`; (JPEG, 0, 0) when none comes
    before the scan."""
    for marker, i in _jpeg_segments(data):
        if marker in JPEG_FRAME_MARKERS:
            if i + 9 > len(data):
                break
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return "JPEG", int(w), int(h)
    return "JPEG", 0, 0


def _tiff_header(data: bytes) -> tuple[str, int, int]:
    """ImageWidth (tag 256) and ImageLength (257) from the first directory, as `_tiff_tags` reads them; (TIFF, 0, 0)
    when either cannot be read. A value of 0 or less is no size, and so is a size tag given twice: libtiff reads the
    first entry and ignores the rest, so a file listing 8000 then 10 would measure small and decode large wherever the
    last counted (#169)."""
    tags = _tiff_tags(data)
    if TIFF_TWICE in (tags.get(256), tags.get(257)):
        return "TIFF", 0, 0
    return "TIFF", tags.get(256, 0), tags.get(257, 0)


def file_header(path: str | Path, read: Reader | None = None) -> tuple[str, int, int] | None:
    """`image_header` of the file at `path`, width and height swapped where its Orientation is 5 to 8 as the decoder
    turns the image: the size of the image `load_image` returns. The first HEADER_BYTES are read, and the rest only for
    a TIFF, whose directory may lie anywhere, or a file whose header lies past them; a PNG's chunk headers are read
    across the file besides, each chunk's data skipped by its length, up to PNG_MAX_CHUNKS of them. The Orientation is
    read as OpenCV 5.0 reads it: from each EXIF APP1 segment before a JPEG's scan and from the eXIf chunk libpng keeps
    (`_exif_orientation`), and from a TIFF's tag 274 as libtiff reads it (`_tiff_tags`). OSError when the file cannot be
    read. With `read`, the bytes it gives are walked in memory instead: a file of a customer's dataset store, decrypted
    whole (REQ-TRN-017)."""
    # unbuffered: a read or a skip touches only the bytes asked for
    with open(path, "rb", buffering=0) if read is None else io.BytesIO(read(Path(path))) as f:
        data = _read(f, HEADER_BYTES)
        header = image_header(data)
        if header is not None and len(data) == HEADER_BYTES and (header[0] == "TIFF" or min(header[1:]) <= 0):
            data += f.read()
            header = image_header(data)
        if header is None:
            return None
        blocks = _jpeg_exif(data) if header[0] == "JPEG" else _png_exif(f) if header[0] == "PNG" else []
    turns = (t for t in map(_exif_orientation, blocks) if t is not None)  # OpenCV keeps the first one it reads
    turn = _tiff_tags(data).get(274, 1) if header[0] == "TIFF" else next(turns, 1)
    return (header[0], header[2], header[1]) if turn in (5, 6, 7, 8) else header


def _read(f: Any, size: int) -> bytes:
    """Up to `size` bytes from `f`, fewer only at its end."""
    data = b""
    while len(data) < size and (more := f.read(size - len(data))):
        data += more
    return data


def _jpeg_exif(data: bytes) -> list[bytes]:
    """The TIFF blocks of the APP1 segments that hold EXIF before a JPEG's scan, in order, as OpenCV reads each one."""
    app1 = ((i, i + 2 + int.from_bytes(data[i + 2 : i + 4], "big")) for m, i in _jpeg_segments(data) if m == 0xE1)
    return [data[i + 10 : end] for i, end in app1 if end > i + 10 and data[i + 4 : i + 10] == b"Exif\0\0"]


def _png_exif(f: Any) -> list[bytes]:
    """The eXIf chunk of a PNG file that libpng 1.6.58 keeps, wherever it lies before IEND: the first whose data starts
    II*\\0 or MM\\0* and whose CRC is right, as libpng drops any other. None in an animated PNG, whose last acTL chunk
    before the image data names more than one frame: OpenCV decodes its first frame with no Orientation. The walk ends
    where libpng fails the file, at a chunk type that is not four letters with an upper case third or at a critical
    chunk it does not know, and after PNG_MAX_CHUNKS chunks, where libpng reads on."""
    f.seek(8)
    kept, frames, image = list[bytes](), 1, False
    for _ in range(PNG_MAX_CHUNKS):
        kind = (head := _read(f, 8))[4:]
        if len(head) < 8 or kind == b"IEND" or not (kind.isalpha() and kind[2:3].isupper()):
            break  # the end, or libpng's "bad header (invalid type)"
        if kind[:1].isupper() and kind not in PNG_CRITICAL:
            break  # libpng's "unhandled critical chunk"
        length, image = int.from_bytes(head[:4], "big"), image or kind == b"IDAT"
        if not (kind == b"eXIf" and not kept or kind == b"acTL" and not image):
            f.seek(length + 4, 1)  # the chunk's data and its CRC
            continue
        body = _read(f, length + 4)
        crc = struct.pack(">I", zlib.crc32(kind + body[:length]))
        if kind == b"acTL":
            frames = int.from_bytes(body[:4], "big")
        elif body[:4] in (b"II*\0", b"MM\0*") and body[length:] == crc:
            kept = [body[:length]]
    return [] if frames > 1 else kept


def _exif_orientation(block: bytes) -> int | None:
    """The Orientation OpenCV 5.0's ExifReader reads from an EXIF block, None for none. The block is little endian after
    II and big endian after anything else, and needs 42 next; the first directory's entries are read in turn, the
    Orientation being the first 16 bits of the first tag 274's value, whatever its type and number of values. The
    reader gives up on the block at an entry whose value it cannot read (EXIF_TEXT, EXIF_SHORT, EXIF_RATIONALS): an
    Orientation after it is not read."""
    order: Literal["little", "big"] = "little" if block[:2] == b"II" else "big"

    def value(at: int, size: int) -> int:  # ExifReader's getU16 and getU32, which give up past the block's end
        if at + size > len(block):
            raise IndexError(at)
        return int.from_bytes(block[at : at + size], order)

    try:
        if value(2, 2) != 42:
            return None
        start = value(4, 4) + 2  # the first entry, after the directory's count
        for at in range(start, start + 12 * value(start - 2, 2), 12):
            tag = value(at, 2)
            if tag == 274:
                return value(at + 8, 2)
            if tag in EXIF_TEXT:  # read from the offset given, or from byte 8 of the block when 4 bytes or fewer
                size = value(at + 4, 4)
                end = (value(at + 8, 4) if size > 4 else 8) + size
            elif tag in EXIF_RATIONALS:
                end = value(at + 8, 4) + 8 * EXIF_RATIONALS[tag]
            else:
                end = at + 10 if tag in EXIF_SHORT else 0
            if end > len(block):  # past the block: the reader gives up on it
                return None
    except IndexError:
        return None
    return None


def _tiff_entries(data: bytes) -> tuple[str, bool, list[tuple[int, int, int, bytes]]]:
    """The byte order of a classic or a BigTIFF file, whether it is a BigTIFF, and the entries of its first directory
    in the order listed, each as (tag, type, number of values, value field); the directory may sit anywhere in the
    file."""
    order = "<" if data[:2] == b"II" else ">"
    big = data[2:4] in (b"+\x00", b"\x00+")  # BigTIFF: 8-byte offsets and counts, 20-byte entries
    head, count_fmt, values_fmt, entry_len, value_at = (16, "Q", "Q", 20, 12) if big else (8, "H", "I", 12, 8)
    entries: list[tuple[int, int, int, bytes]] = []
    if len(data) < head:
        return order, big, entries
    (offset,) = struct.unpack(order + "Q", data[8:16]) if big else struct.unpack(order + "I", data[4:8])
    count_len = struct.calcsize(count_fmt)
    if offset + count_len > len(data):
        return order, big, entries
    (count,) = struct.unpack(order + count_fmt, data[offset : offset + count_len])
    for n in range(min(int(count), 65535)):  # a classic count's maximum; libtiff refuses a directory over 4,096 entries
        at = offset + count_len + entry_len * n
        entry = data[at : at + entry_len]
        if len(entry) < entry_len:
            break
        tag, kind = struct.unpack(order + "HH", entry[:4])
        (values,) = struct.unpack(order + values_fmt, entry[4:value_at])
        entries.append((tag, kind, int(values), entry[value_at:]))
    return order, big, entries


def _tiff_tags(data: bytes) -> dict[int, int]:
    """The TIFF_TAGS the first directory of a classic or a BigTIFF file holds, by tag. A tag counts when it holds one
    value of an integer type, BYTE to SLONG8, as libtiff's TIFFReadDirEntryLong reads it: in a classic file the 8 bytes
    of a LONG8 or SLONG8 sit at the offset its entry holds (#242 review), and a value below 0 reads as 0. A tag listed
    twice gives TIFF_TWICE whatever either entry holds, since libtiff reads the first, but TIFF_FIRST keep the first,
    as they only set how many strips are read or, for the Orientation, how the image is turned; so does a Compression
    given once per sample, as TIFF before 5.0 wrote it and libtiff still reads it (#242 stack review)."""
    order, big, entries = _tiff_entries(data)
    tags, seen = dict[int, int](), set[int]()
    for tag, kind, values, field in entries:
        if tag in TIFF_TAGS and tag in seen:  # whatever either entry holds: no single value, so the file is refused
            if tag not in TIFF_FIRST:
                tags[tag] = TIFF_TWICE
            continue
        seen.add(tag)
        fmt = TIFF_INT_TYPES.get(kind)
        if tag not in TIFF_TAGS or fmt is None:
            continue
        if kind in (16, 17) and not big:  # 8 bytes fit no classic entry: libtiff reads them where the entry points
            (where,) = struct.unpack(order + "I", field)
            field = data[where : where + 8]  # short past the end of the file, where libtiff refuses the directory
        if values == 1 and len(field) >= struct.calcsize(fmt):
            (value,) = struct.unpack(order + fmt, field[: struct.calcsize(fmt)])
            tags[tag] = max(int(value), 0)
        elif tag == 259:  # libtiff takes the first value when the values agree: no single value read here
            tags[tag] = TIFF_TWICE
    return tags


def _tiff_count(tags: dict[int, int], width: int, height: int) -> int:
    """The strips or tiles libtiff 4.7.1 counts in a TIFF (TIFFNumberOfStrips, TIFFNumberOfTiles), and so the values it
    reads of each offset and byte-count list (#242 stack review): with a TileWidth or TileLength, columns over TileWidth
    times rows over TileLength (a side of 4,294,967,295, which libtiff reads as the image's, gives one tile across here
    too; 0 or none gives no tile, which libtiff refuses) times ImageDepth over TileDepth (each 1 when 0 or none, which
    can only raise the count), else rows over RowsPerStrip (one strip for 4,294,967,295 or none); times SamplesPerPixel
    when the planes are apart (PlanarConfiguration 2, or listed twice, which can only raise the count)."""
    planes = tags.get(277, 1) if tags.get(284, 1) in (2, TIFF_TWICE) else 1
    if 322 in tags or 323 in tags:
        across, down = tags.get(322, 0), tags.get(323, 0)
        if not across or not down:
            return 0  # tif_dirread.c: "Cannot handle zero number of tiles"
        return -(-width // across) * -(-height // down) * -(-(tags.get(32997) or 1) // (tags.get(32998) or 1)) * planes
    rows = tags.get(278, 0)
    return (1 if rows in TIFF_WHOLE_SIDE else -(-height // rows)) * planes


def _tiff_blocks(data: bytes, most: int) -> tuple[np.ndarray, np.ndarray]:
    """Where the strips or tiles of a TIFF's first directory start in the file and how many bytes each holds, read as
    libtiff 4.7.1 reads them (tif_dirread.c; #242 review): only the first `most` values of each list, the strips
    `_tiff_count` gives, whatever an entry lists (TIFFFetchStripThing; #242 stack review); StripOffsets and TileOffsets
    fill one list, the one listed last counting, each by its first entry, and so do StripByteCounts and TileByteCounts;
    values of an integer type sit in the entry when all it lists fit its value field and at the offset it holds
    otherwise. Each array views the file's bytes in the list's own type, unsigned (libtiff refuses a negative value);
    past the end of the shorter one stands the 0 libtiff pads it with. A list libtiff cannot read (of another type, or
    running past the end of the file) is read as far as it goes, since libtiff then refuses the file before decoding a
    strip."""
    order, big, entries = _tiff_entries(data)
    found, seen = dict[int, tuple[int, int, bytes]](), set[int]()
    for tag, kind, values, field in entries:
        if tag in TIFF_LISTS and tag not in seen:  # libtiff ignores a tag listed again
            found[TIFF_LISTS[tag]] = (kind, values if kind in TIFF_LIST_TYPES else 0, field)
        seen.add(tag)
    lists = []
    for kind, values, field in (found.get(0, (1, 0, b"")), found.get(1, (1, 0, b""))):
        dtype = np.dtype(order + TIFF_LIST_TYPES.get(kind, "u1"))
        if values * dtype.itemsize <= len(field):  # by the number listed, as libtiff decides it
            lists.append(np.frombuffer(field, dtype, min(values, most)))
        else:  # the field holds where the values are
            where = min(int.from_bytes(field, "little" if order == "<" else "big"), len(data))
            lists.append(np.frombuffer(data, dtype, min(values, most, (len(data) - where) // dtype.itemsize), where))
    return lists[0], lists[1]


def _tiff_spans(starts: np.ndarray, counts: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Where the bytes each strip or tile holds of a file of `size` bytes begin and end (the byte after them), 4 bytes
    each (8 from 2 GiB): a strip past the end of the offsets starts at 0, as libtiff pads them; one without a byte
    count, of 0 bytes or starting past the end of the file holds none, and one running past the end the bytes up to
    it. No count is over `size`."""
    kind = np.uint32 if size < 1 << 31 else np.uint64
    begin, end = np.zeros(max(len(starts), len(counts)), kind), np.zeros(max(len(starts), len(counts)), kind)
    np.minimum(starts, np.uint64(size), out=begin[: len(starts)], casting="unsafe")
    end[: len(counts)] = counts
    np.add(end, begin, out=end)
    np.minimum(end, kind(size), out=end)
    return begin, end


def _tiff_shared(data: bytes, tags: dict[int, int], width: int, height: int) -> Phrase | None:
    """Why the TIFF's strips or tiles would cost the decoder more bytes than the file holds, or None (#242 review).
    libtiff reads each strip or tile from its own offset and byte count and decodes it, so strips that all point at the
    same bytes cost those bytes once per strip: one-row strips sharing one JPEG stream of 99 scans held load_image about
    69 s on a 49 MP file of 8 MB, and one-row strips sharing a 1 MB block about 70 s uncompressed, as long with Deflate
    and far longer with PackBits. A TIFF of more than TIFF_MAX_BLOCKS strips or tiles is refused before a list is read
    (#242 stack review: reading every value listed took 3.7 GB on a crafted 200 MB file). Once two strips or tiles hold
    bytes, a file is refused when their byte counts add up to more than the file, or when two of them share a byte (the
    lowest-numbered two holding the first byte shared are named), so that libtiff reads no byte of the file twice.
    libtiff ignores the byte counts of an uncompressed file of more than two strips whose first two differ, and reads
    each strip at its size, so such a file is not checked. The check holds two arrays of 4 bytes a strip, sorted in
    place, and arrays of 1 byte a strip: about 40 MB at TIFF_MAX_BLOCKS. A strip that holds no byte (`_tiff_spans`)
    shares none, and one starting past the end of the file is left to libtiff, which fails on reaching it."""
    tiles = 322 in tags or 323 in tags
    if (count := _tiff_count(tags, width, height)) > TIFF_MAX_BLOCKS:
        if tiles:
            many = QT_TRANSLATE_NOOP("Errors", "it has {count} tiles, more than the {most} this app decodes")
        else:
            many = QT_TRANSLATE_NOOP("Errors", "it has {count} strips, more than the {most} this app decodes")
        return many.fill(count=f"{count:,}", most=f"{TIFF_MAX_BLOCKS:,}")
    starts, counts = _tiff_blocks(data, count)
    one, two = (int(counts[n]) if n < len(counts) else 0 for n in (0, 1))  # the first two byte counts
    estimated = tags.get(259, 1) == 1 and tags.get(284, 1) == 1 and count > 2
    if estimated and one != two and one > 0 and two > 0:
        return None  # tif_dirread.c: "Wrong StripByteCounts field, ignoring and calculating from imagelength"
    held = int(np.count_nonzero(counts))  # libtiff refuses a strip of 0 bytes when it reaches it
    if held < 2:
        return None
    if int(counts.max()) > len(data) or int(counts.sum(dtype=np.uint64)) > len(data):
        if tiles:
            over = QT_TRANSLATE_NOOP("Errors", "its {count} tiles add up to more than the {size} bytes of the file")
        else:
            over = QT_TRANSLATE_NOOP("Errors", "its {count} strips add up to more than the {size} bytes of the file")
        return over.fill(count=f"{held:,}", size=f"{len(data):,}")
    begin, end = _tiff_spans(starts, counts, len(data))
    if bool(np.all(begin[1:] >= end[:-1])):  # each after the last in the file, as writers lay them out
        return None
    # Each sorted apart, a begin falls before the end one place lower exactly where two strips hold the same byte
    begin.sort()
    end.sort()
    clash = begin[1:] < end[:-1]
    if not clash.any():
        return None
    shared_at = int(begin[int(clash.argmax()) + 1])  # the first byte two strips hold
    del begin, end, clash
    begin, end = _tiff_spans(starts, counts, len(data))
    holding = (begin <= shared_at) & (end > shared_at)
    first = int(holding.argmax())
    holding[first] = False
    second = int(holding.argmax())
    if tiles:
        shared = QT_TRANSLATE_NOOP(
            "Errors",
            "its tiles {first} and {second} share bytes of the file, so the decoder would read them again",
        )
    else:
        shared = QT_TRANSLATE_NOOP(
            "Errors",
            "its strips {first} and {second} share bytes of the file, so the decoder would read them again",
        )
    return shared.fill(first=first + 1, second=second + 1)  # numbered from 1


def _jpeg_scans(data: bytes) -> int:
    """The scans libjpeg decodes in a JPEG, or more, never fewer (#242 review). libjpeg reads from marker to marker: it
    reads a segment by its length, starts a scan at each SOS, searches past a scan's coded data, stuffed and fill bytes,
    restarts and stray bytes for the next marker, and stops at the first EOI it meets. So the scans of an EXIF thumbnail
    (inside a segment) or the bytes after the image (a phone's video) are no scans of its. Past JPEG_MAX_MARKERS
    markers the walk stops and every FF DA pair left counts as a scan, so the count never exceeds the file's FF DA
    pairs either."""
    scans, i = 0, 2
    for _ in range(JPEG_MAX_MARKERS):
        found = JPEG_WALK.search(data, i)
        if found is None or found[1] == b"\xd9":
            return scans
        scans += found[1] == b"\xda"
        i = found.end() + int.from_bytes(data[found.end() : found.end() + 2], "big")  # the length counts its 2 bytes
    return scans + data.count(b"\xff\xda", i)


def _decoder_work(data: bytes, kind: str, width: int, height: int) -> Phrase | None:
    """Why decoding the file would cost far more than its `width` × `height` image, or None (#242). libjpeg decodes
    every scan of a progressive JPEG, each a pass over the image, and a file can repeat a scan thousands of times at 31
    bytes each: a JPEG with more than JPEG_MAX_SCANS is refused, counted by `_jpeg_scans` once the file holds more FF DA
    pairs than that (the walk can only lower the count, so a file with fewer is never walked). OpenCV allocates its
    TIFF buffer by one tile or strip, up to 1 GiB, whatever the image (libtiff fills a whole tile, but of a strip only
    the image's rows): a TIFF is refused when its tile or strip, TileWidth (or the width) by TileLength (or
    RowsPerStrip, or the height), holds more pixels than the larger of TIFF_BLOCK_PIXELS and the image with each side
    rounded up to a multiple of 16, as TIFF 6.0 makes tile sides. libtiff decodes each strip or tile from its own bytes:
    a TIFF of more than TIFF_MAX_BLOCKS strips or tiles, or whose strips or tiles share bytes or add up to more than the
    file, is refused by `_tiff_shared`, and so is one whose check runs out of memory (#242 stack review: a bare
    MemoryError reached the user as AOI-SET-007, not as a refused image)."""
    if kind == "JPEG" and data.count(b"\xff\xda") > JPEG_MAX_SCANS and (scans := _jpeg_scans(data)) > JPEG_MAX_SCANS:
        reason = QT_TRANSLATE_NOOP("Errors", "it holds {scans} scans, more than the {most} this app decodes")
        return reason.fill(scans=f"{scans:,}", most=JPEG_MAX_SCANS)
    if kind != "TIFF":
        return None
    tags = _tiff_tags(data)
    if TIFF_TWICE in (tags.get(t) for t in TIFF_BLOCK_TAGS):
        return QT_TRANSLATE_NOOP("Errors", "it gives the size of its tiles or strips twice")
    rows = tags.get(278, 0)
    rows = height if rows in TIFF_WHOLE_SIDE else rows
    cols, rows = tags.get(322) or width, tags.get(323) or rows
    if cols * rows <= max(TIFF_BLOCK_PIXELS, -(-width // 16) * 16 * (-(-height // 16) * 16)):
        try:
            return _tiff_shared(data, tags, width, height)
        except MemoryError:  # its arrays are bounded, yet a station short of memory can still refuse them
            return QT_TRANSLATE_NOOP("Errors", "there was not enough free memory to check its strips or tiles")
    if 322 in tags or 323 in tags:
        reason = QT_TRANSLATE_NOOP(
            "Errors", "its tiles are {cols} × {rows} px, more than its {width} × {height} px image needs"
        )
    else:
        reason = QT_TRANSLATE_NOOP(
            "Errors", "its strips are {cols} × {rows} px, more than its {width} × {height} px image needs"
        )
    return reason.fill(cols=cols, rows=rows, width=width, height=height)


def load_image(
    path: str | Path,
    max_megapixels: float = MAX_MEGAPIXELS,
    max_megabytes: float = MAX_MEGABYTES,
    read: Reader | None = None,
) -> np.ndarray:
    """Read as BGR uint8 after checking the file (REQ-INSP-001): it must hold a PNG, JPEG, BMP or TIFF image by its
    content, whatever its name, and stay within `max_megabytes` on disk, `max_megapixels` by its header and `MAX_SIDE`
    on either side; a JPEG within JPEG_MAX_SCANS scans, and a TIFF of at most TIFF_MAX_BLOCKS tiles or strips, each
    within its image's size and in bytes of its own, so the decoder's work is bounded by the image's pixels and the
    file's bytes (#242), though a
    crafted file within every bound can still hold it some seconds (docs/security/threat-model.md). All of these are
    checked before a pixel is decoded, and a recognised format whose header gives no size is refused, never decoded.
    Decoding the bytes with `imdecode` keeps non-ASCII (Korean) Windows paths working."""
    return _read_image(Path(path), max_megapixels, max_megabytes, read)[0]


def load_image_sha256(
    path: str | Path,
    max_megapixels: float = MAX_MEGAPIXELS,
    max_megabytes: float = MAX_MEGABYTES,
    read: Reader | None = None,
) -> tuple[np.ndarray, str]:
    """`load_image`, with the SHA-256 of the very bytes decoded, in hex: a record names the golden board it was judged
    against by its content, read once, so no second read of the file can race a writer (REQ-CMP-003)."""
    img, data = _read_image(Path(path), max_megapixels, max_megabytes, read)
    return img, hashlib.sha256(data).hexdigest()


def checked_bytes(
    path: str | Path,
    max_megapixels: float = MAX_MEGAPIXELS,
    max_megabytes: float = MAX_MEGABYTES,
    read: Reader | None = None,
) -> bytes:
    """The bytes of an image file once `load_image` has checked and decoded them, read once: a sample import copies
    only a file Inspection would open, and hashes the very bytes checked (REQ-TRN-001, REQ-INSP-001)."""
    return _read_image(Path(path), max_megapixels, max_megabytes, read)[1]


def _read_image(
    p: Path, max_megapixels: float, max_megabytes: float, read: Reader | None = None
) -> tuple[np.ndarray, bytes]:
    """The image and the bytes it was decoded from, after `load_image`'s checks; `read` gives the file's bytes, so
    a customer's dataset store hands over a file decrypted in memory (REQ-TRN-017, ADR 0010, decision 6)."""
    try:
        size = p.stat().st_size
        if size > max_megabytes * 1e6:
            in_bytes = QT_TRANSLATE_NOOP("Errors", "{megabytes} MB ({count} bytes)")
            found = in_bytes.fill(megabytes=f"{size / 1e6:.1f}", count=f"{size:,}")
            raise AoiError("AOI-INSP-005", path=str(p), size=found, limit=f"{max_megabytes:g} MB")
        data = p.read_bytes() if read is None else read(p)
    except OSError as e:  # missing file, folder, or no permission
        raise AoiError("AOI-INSP-001", detail=str(e), path=str(p)) from e
    header = image_header(data)
    if header is None:
        raise AoiError("AOI-INSP-004", path=str(p))
    kind, w, h = header
    if w <= 0 or h <= 0:
        raise AoiError(
            "AOI-INSP-006", path=str(p), kind=kind, reason=QT_TRANSLATE_NOOP("Errors", "its header holds no image size")
        )
    if w * h > max_megapixels * 1e6:
        pixels = f"{w * h / 1e6:.2f} MP ({w} × {h})"
        raise AoiError("AOI-INSP-005", path=str(p), size=pixels, limit=f"{max_megapixels:g} MP")
    if max(w, h) > MAX_SIDE:
        raise AoiError("AOI-INSP-007", path=str(p), width=w, height=h, limit=f"{MAX_SIDE:,}")
    if (costly := _decoder_work(data, kind, w, h)) is not None:
        raise AoiError("AOI-INSP-006", path=str(p), kind=kind, reason=costly)
    try:
        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as e:  # the decoder's own limits, which hold whatever the settings say
        raise AoiError(
            "AOI-INSP-006",
            detail=str(e),
            path=str(p),
            kind=kind,
            reason=QT_TRANSLATE_NOOP("Errors", "the decoder refused it"),
        ) from e
    if img is None:
        reason = QT_TRANSLATE_NOOP("Errors", "it is cut short, damaged, or a variant this app does not read")
        raise AoiError("AOI-INSP-006", path=str(p), kind=kind, reason=reason)
    return img, data


def encode_image(path: str | Path, img: np.ndarray, params: Sequence[int] = ()) -> bytes:
    """`img` in the image format `path`'s suffix names (PNG with none), before anything is written: AOI-INSP-002 for a
    suffix no format has. `params` are OpenCV encoder settings (`cv2.IMWRITE_*` flags and values), empty for its own."""
    ext = Path(path).suffix or ".png"
    try:
        ok, buf = cv2.imencode(ext, img, list(params))
    except cv2.error as e:  # OpenCV 5 raises for a suffix it cannot encode, such as "lot.txt" or "board_v1.2" (#195)
        raise AoiError("AOI-INSP-002", detail=str(e), path=str(path)) from e
    if not ok:
        raise AoiError("AOI-INSP-002", path=str(path))
    return buf.tobytes()


def save_image(path: str | Path, img: np.ndarray, params: Sequence[int] = ()) -> None:
    """Write `img` to `path` as `encode_image` encodes it, with the OpenCV encoder settings `params`."""
    atomic.write_bytes(path, encode_image(path, img, params))  # whole file or nothing, and non-ASCII Windows paths work


PREVIEW_PX = 1600  # the longest side of an overlay kept for a preview: sharp on a 1080 p pane, quick to load


def preview_size(img: np.ndarray, longest: int = PREVIEW_PX) -> np.ndarray:
    """`img` scaled down so its longest side is at most `longest` pixels; a smaller image as it is."""
    h, w = img.shape[:2]
    if max(h, w) <= longest:
        return img
    f = longest / max(h, w)
    small: np.ndarray = cv2.resize(img, (max(1, round(w * f)), max(1, round(h * f))), interpolation=cv2.INTER_AREA)
    return small


def list_images(folder: str | Path) -> list[Path]:
    return sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in IMAGE_EXTS)


def align_to_reference(img: np.ndarray, ref: np.ndarray, max_features: int = 4000) -> tuple[np.ndarray, dict[str, Any]]:
    """Register `img` onto `ref` with ORB features + RANSAC homography.

    Boards are never placed at exactly the same spot, so every pixel comparison
    (golden-sample diff, ROI checks) happens after this step. Falls back to a plain
    resize when not enough features match; `info["aligned"]` tells the UI which.
    """
    homography, info = registration(img, ref, max_features)
    return warp_to(img, homography, (ref.shape[1], ref.shape[0])), info


def registration(
    img: np.ndarray, ref: np.ndarray, max_features: int = 4000
) -> tuple[np.ndarray | None, dict[str, Any]]:
    """The homography `align_to_reference` warps `img` onto `ref` with, or None for its plain resize, and its info. A
    training run keeps it, so it can warp an image read again exactly as the first time (REQ-TRN-007)."""
    info: dict[str, Any] = {"aligned": False, "inliers": 0, "method": "resize"}
    g1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB.create(max_features)
    k1, d1 = orb.detectAndCompute(g1, None)
    k2, d2 = orb.detectAndCompute(g2, None)
    if d1 is not None and d2 is not None and len(k1) >= 10 and len(k2) >= 10:
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = sorted(matcher.match(d1, d2), key=lambda m: m.distance)[:500]
        if len(matches) >= 10:
            src = np.array([k1[m.queryIdx].pt for m in matches], dtype=np.float32).reshape(-1, 1, 2)
            dst = np.array([k2[m.trainIdx].pt for m in matches], dtype=np.float32).reshape(-1, 1, 2)
            H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
            if H is not None and mask is not None and int(mask.sum()) >= 12:
                info.update(aligned=True, inliers=int(mask.sum()), method="orb-homography")
                return H, info
    return None, info


def warp_to(img: np.ndarray, homography: np.ndarray | None, size: tuple[int, int]) -> np.ndarray:
    """`img` warped by `homography` to `size` (width, height), or resized to it when the homography is None."""
    if homography is None:
        resized: np.ndarray = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
        return resized
    warped: np.ndarray = cv2.warpPerspective(img, homography, size, borderMode=cv2.BORDER_REPLICATE)
    return warped


def blend(img: np.ndarray, overlay: np.ndarray, alpha: float = 0.45) -> np.ndarray:
    if overlay.shape[:2] != img.shape[:2]:
        overlay = cv2.resize(overlay, (img.shape[1], img.shape[0]))
    blended: np.ndarray = cv2.addWeighted(img, 1 - alpha, overlay, alpha, 0)
    return blended


def heat_overlay(img: np.ndarray, values: np.ndarray, vmax: float) -> np.ndarray:
    """Colour only where `values` is high, so the board stays readable underneath: the heat colour is blended in with
    a weight of 0.8 x value / vmax, at most 0.8, so `vmax` is the value shown in full colour (one at or below 0 counts
    as a tiny positive value: every positive value is in full colour); a map of another size is resized to the board's.
    OpenCV does the per-pixel blend, so a 5 MP view renders well inside the 300 ms of REQ-CMP-002."""
    if values.shape[:2] != img.shape[:2]:
        values = cv2.resize(values, (img.shape[1], img.shape[0]))
    weight = values.astype(np.float32) * np.float32(0.8 / max(vmax, 1e-6))
    np.clip(weight, 0.0, 0.8, out=weight)
    colours = cv2.applyColorMap(cv2.convertScaleAbs(weight, alpha=255 / 0.8), cv2.COLORMAP_JET)
    shaded: np.ndarray = cv2.blendLinear(img, colours, 1 - weight, weight)
    return shaded
