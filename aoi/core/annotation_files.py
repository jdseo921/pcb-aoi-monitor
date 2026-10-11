"""Defect boxes read from the annotation file a labelled dataset keeps beside each image (REQ-TRN-019, ADR 0016).

Public and customer datasets of PCB defects come with their boxes already drawn, in one of two common formats:

- Pascal VOC: one XML file per image, `<stem>.xml` beside it or under an `Annotations` folder that mirrors the images'
  folders (PKU-Market-PCB: `images/Open_circuit/01_open_circuit_01.jpg` and `Annotations/Open_circuit/...xml`), each
  object a class name and a box in pixels;
- YOLO: one text file per image, `<stem>.txt` beside it or under a `labels` folder that mirrors `images`, each line a
  class number and a box as shares of the image's width and height, the class names in `classes.txt`, `obj.names` or
  the `names` of a `data.yaml` in the image's folder or one above it.

A class is named as the classification table names a type, in any case and with `_` or `-` for spaces, or by one of
the bare-board names in ALIASES; a box of any other class is left out, and named in `left_out`. A box is read in pixels
of the image as decoded (its EXIF Orientation applied), and an annotation for an image of another size is not read.
Annotation files come from outside, so each is read only up to MAX_BYTES, and an XML file with a document type (where
entities would be declared) is refused before it is parsed. No Qt here: the engine imports this module.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # nosec B405: a document type is refused before parsing (`_voc`)
from dataclasses import dataclass, field
from pathlib import Path

from ..defects import names
from .labels import DefectBox

MAX_BYTES = 1_000_000  # an annotation file larger than this is not read: a page of boxes is a few kB
ALIASES = {  # bare-board names public datasets use (DeepPCB, PKU-Market-PCB), as the classification table names them
    "open": "Open Circuit",
    "short": "Short Circuit",
    "mouse bite": "Mousebite",
    "spurious copper": "Spurious Copper",
    "copper": "Spurious Copper",
    "missing hole": "Pin-hole / Missing Hole",
    "pin hole": "Pin-hole / Missing Hole",
    "pinhole": "Pin-hole / Missing Hole",
}
NAME_FILES = ("classes.txt", "obj.names", "data.yaml")


@dataclass
class Annotation:
    """What an image's annotation file gave: the types of its boxes of known classes, those boxes in pixels once the
    image's size is known (`read`), the classes of the boxes left out, and the file read; `why` says why no box was
    read from it, when none was."""

    source: Path
    kinds: list[str] = field(default_factory=list)
    boxes: list[DefectBox] = field(default_factory=list)
    left_out: list[str] = field(default_factory=list)
    why: str = ""

    def main_type(self) -> str | None:
        """The type most of the boxes have (the first box's among equals): the image's defect type when none is
        picked."""
        return max(dict.fromkeys(self.kinds), key=self.kinds.count) if self.kinds else None

    @property
    def defect_free(self) -> bool:
        """Read whole and holding no box at all: what an annotation tool writes for a good image."""
        return not (self.why or self.kinds or self.left_out)


Entry = tuple[str, tuple[float, float, float, float]]  # a box's class name and x0, y0, x1, y1


def _key(name: str) -> str:
    return re.sub(r"[\s_\-/]+", " ", name).strip().casefold()


def type_named(name: str) -> str | None:
    """The classification table's type a class is named after, or None."""
    key = _key(name)
    return next((known for known in names() if _key(known) == key), None) or ALIASES.get(key)


def find(image: Path, root: Path | None = None) -> Path | None:
    """The annotation file of `image`: `<stem>.xml` or `<stem>.txt` beside it, else the same name under an
    `Annotations` or `labels` folder in place of the first folder below an ancestor, up to `root` (the folder picked)
    when given."""
    for suffix in (".xml", ".txt"):
        if (beside := image.with_suffix(suffix)).is_file():
            return beside
    for up in image.parents[1:]:
        rel = image.relative_to(up).parts
        for folder, suffix in (("Annotations", ".xml"), ("labels", ".txt")):
            candidate = up.joinpath(folder, *rel[1:]).with_suffix(suffix)
            if candidate.is_file():
                return candidate
        if root is not None and up == root:
            break
    return None


def peek(image: Path, root: Path | None = None) -> Annotation | None:
    """The types `image`'s annotation file names, without its boxes, which need the image's size; None when it has
    no annotation file. Cheap enough to label a folder's files as they are listed."""
    return _parse(image, None, root)


def read(image: Path, size: tuple[int, int], root: Path | None = None) -> Annotation | None:
    """The boxes of `image`, decoded at `size` (width, height), from its annotation file (`find`), or None when it has
    none. A file that cannot be read, or one made for an image of another size, gives no box and says why."""
    return _parse(image, size, root)


def _parse(image: Path, size: tuple[int, int] | None, root: Path | None) -> Annotation | None:
    source = find(image, root)
    if source is None:
        return None
    found = Annotation(source)
    try:
        if source.stat().st_size > MAX_BYTES:
            raise ValueError(f"the file is over {MAX_BYTES // 1000} kB")
        if source.suffix == ".xml":
            (declared, entries), scale = _voc(source.read_bytes()), (1.0, 1.0)
            if size is not None and declared not in (None, size):
                raise ValueError(f"it was made for a {declared[0]} x {declared[1]} image, not {size[0]} x {size[1]}")
        else:
            entries = _yolo(source.read_text(encoding="utf-8-sig"), _class_names(source, image, root))
            scale = (float(size[0]), float(size[1])) if size is not None else (1.0, 1.0)
    except (OSError, UnicodeDecodeError, ET.ParseError, ValueError) as e:
        found.why = str(e) or type(e).__name__
        return found
    for name, (x0, y0, x1, y1) in entries:
        if (kind := type_named(name)) is None:
            found.left_out.append(name)
            continue
        found.kinds.append(kind)
        if size is not None:
            sx, sy = scale
            left, top = max(0, round(x0 * sx)), max(0, round(y0 * sy))
            right, bottom = min(size[0], round(x1 * sx)), min(size[1], round(y1 * sy))
            if right > left and bottom > top:
                found.boxes.append(DefectBox(left, top, right - left, bottom - top, kind))
    return found


def _voc(data: bytes) -> tuple[tuple[int, int] | None, list[Entry]]:
    """The image size a Pascal VOC file declares (None when it declares none) and its boxes in pixels."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("an XML document type is not read")
    root = ET.fromstring(data)  # nosec B314: no document type, so no entity is declared, and at most MAX_BYTES
    if root.tag != "annotation":
        raise ValueError(f"<{root.tag}> is not a Pascal VOC annotation")
    width, height = (int(float(root.findtext(f"size/{k}") or 0)) for k in ("width", "height"))
    entries: list[Entry] = []
    for obj in root.iter("object"):
        if (box := obj.find("bndbox")) is not None:
            x0, y0, x1, y1 = (float(box.findtext(k) or 0) for k in ("xmin", "ymin", "xmax", "ymax"))
            entries.append((obj.findtext("name") or "", (x0, y0, x1, y1)))
    return ((width, height) if width and height else None), entries


def _yolo(text: str, classes: list[str]) -> list[Entry]:
    """A YOLO file's boxes as shares of the image's width and height."""
    entries: list[Entry] = []
    for line in text.splitlines():
        if not (cells := line.split()):
            continue
        number, cx, cy, bw, bh = int(cells[0]), *(float(c) for c in cells[1:5])
        name = classes[number] if 0 <= number < len(classes) else f"class {number}"
        entries.append((name, (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)))
    return entries


def _class_names(source: Path, image: Path, root: Path | None) -> list[str]:
    """The YOLO class names of the nearest names file in the annotation's or the image's folder or one above them."""
    for start in (source.parent, image.parent):
        for up in (start, *start.parents):
            for name in NAME_FILES:
                if (path := up / name).is_file() and path.stat().st_size <= MAX_BYTES:
                    text = path.read_text(encoding="utf-8-sig")
                    return _yaml_names(text) if name == "data.yaml" else [n.strip() for n in text.splitlines()]
            if root is not None and up == root:
                break
    return []


def _yaml_names(text: str) -> list[str]:
    """The `names` of a YOLO data.yaml, in its three common forms: a list on one line (`names: ['a', 'b']`), a list
    over lines (`- a`) or a map of numbers (`0: a`); only that key is read."""
    if match := re.search(r"^names:\s*\[(.*?)\]", text, re.M | re.S):
        return [n.strip().strip("'\"") for n in match.group(1).split(",") if n.strip()]
    lines = text.split("names:", 1)[1].splitlines()[1:] if re.search(r"^names:\s*$", text, re.M) else []
    out: list[str] = []
    for line in lines:
        if not line.startswith((" ", "\t", "-")):
            break
        item = re.match(r"\s*(?:-|\d+\s*:)\s*(.+)", line)
        if item:
            out.append(item.group(1).strip().strip("'\""))
    return out
