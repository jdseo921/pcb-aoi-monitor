"""Labels and defect boxes (REQ-TRN-002, REQ-TRN-003; stage S32): what a label may hold, checked before AppContext
stores it. No Qt, so the same rules hold headless."""

from __future__ import annotations

import numbers
from dataclasses import dataclass
from typing import Any

from ..defects import BY_NAME, names
from ..errors import QT_TRANSLATE_NOOP, AoiError
from .imaging import file_header

LABELS = ("OK", "NG", "UNSURE")  # UNSURE images stay out of training and validation and go to the quality engineer
Size = tuple[int, int] | None  # an image's (width, height), or None where no box needs it


@dataclass(frozen=True)
class DefectBox:
    """One defect on an NG image: its box in pixels of the image as decoded and shown, turned by its EXIF Orientation
    (x, y of the top left corner, w by h), and one of the 33 defect types; the severity is always the one
    aoi/defects.py gives the type (REQ-TRN-003)."""

    x: int
    y: int
    w: int
    h: int
    dct_type: str

    def row(self) -> dict[str, Any]:
        """The box as stored and audited, with its type's severity; a NumPy integer as an int."""
        whole = {k: int(getattr(self, k)) for k in ("x", "y", "w", "h")}
        return whole | {"dct_type": self.dct_type, "severity": BY_NAME[self.dct_type].severity}


def check(sample: str, size: Size, label: str, defect_type: str | None, boxes: list[DefectBox]) -> None:
    """Refuse a label `sample` cannot take: AOI-TRN-030 for a label other than OK, NG or UNSURE, a box or defect type on
    an image that is not NG, a type that is not one of the 33 (no Anomaly: a person names the defect) or a box not in
    whole pixels, and AOI-TRN-031 for a box that does not lie inside the image of `size` (width, height); None skips
    that, for boxes kept from the label before, which were checked when drawn."""
    why, known = None, names()
    unknown = [b.dct_type for b in boxes if b.dct_type not in known]
    if label not in LABELS:
        why = QT_TRANSLATE_NOOP("Errors", "{label} is not OK, NG or UNSURE").fill(label=label)
    elif label != "NG" and (boxes or defect_type):
        why = QT_TRANSLATE_NOOP("Errors", "only an NG image takes a defect box or type, not one labelled {label}")
        why = why.fill(label=label)
    elif defect_type and defect_type not in known:  # an older label's type, Anomaly for one
        why = QT_TRANSLATE_NOOP(
            "Errors",
            "the image's defect type, {type}, is not one of the 33 defect types: give the image one of the 33 with"
            " Mark NG, then draw its boxes again",
        ).fill(type=defect_type)
    elif unknown:
        why = QT_TRANSLATE_NOOP("Errors", "{type} is not one of the 33 defect types").fill(type=unknown[0])
    elif not all(_whole(v) for b in boxes for v in (b.x, b.y, b.w, b.h)):
        why = QT_TRANSLATE_NOOP("Errors", "a defect box's position and size are not whole pixels")
    if why is not None:
        raise AoiError("AOI-TRN-030", sample=sample, reason=why)
    if size is None:
        return
    width, height = size
    for n, b in enumerate(boxes, 1):
        if min(b.x, b.y) < 0 or min(b.w, b.h) < 1 or b.x + b.w > width or b.y + b.h > height:
            where = {"x": b.x, "y": b.y, "w": b.w, "h": b.h, "width": width, "height": height}
            raise AoiError("AOI-TRN-031", None, sample=sample, number=n, **where)


def _whole(value: object) -> bool:
    """A whole number of pixels: a Python or NumPy integer, not a bool, a float or a string."""
    return isinstance(value, numbers.Integral) and not isinstance(value, bool)


def image_size(path: str) -> tuple[int, int]:
    """(width, height) of the image at `path` as the decoder returns it, turned by its Orientation, read without
    decoding it (`imaging.file_header`: the first MiB of most files, the whole of a TIFF or of a JPEG whose frame header
    lies past that, and a PNG's chunk headers across the file, up to PNG_MAX_CHUNKS of them): AOI-INSP-001 for a file
    that cannot be read, AOI-INSP-004 for one that holds no image with a size."""
    try:
        header = file_header(path)
    except OSError as e:
        raise AoiError("AOI-INSP-001", detail=str(e), path=path) from e
    if header is None or min(header[1], header[2]) <= 0:
        raise AoiError("AOI-INSP-004", path=path)
    return header[1], header[2]
