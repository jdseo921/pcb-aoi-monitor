"""Labels and defect boxes (REQ-TRN-002, REQ-TRN-003; stage S32): what a label may hold, checked before AppContext
stores it. No Qt, so the same rules hold headless."""

from __future__ import annotations

import numbers
import random
from dataclasses import dataclass
from typing import Any

from ..defects import BY_NAME, names
from ..errors import QT_TRANSLATE_NOOP, AoiError
from .imaging import Reader, file_header

LABELS = ("OK", "NG", "UNSURE")  # UNSURE images stay out of training and validation and go to the quality engineer
Size = tuple[int, int] | None  # an image's (width, height), or None where no box needs it
CALIBRATION_IMAGES = 100  # images in a calibration set (proposed, REQ-TRN-016)
OK_NG_TARGET, TYPE_TARGET = 98, 90  # percent agreement two labellers reach (proposed; the labels sketch's Q36)
CALIBRATION_NG = 30  # NG images a proposed calibration set holds at most (the labels sketch's 27 of 30)


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
            "the image's defect type, {type}, is not one of the 33 defect types (an earlier version stored it): press"
            " Mark NG, which labels the image NG again with no defect type, as its boxes give the types, then draw its"
            " boxes again",
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


def image_size(path: str, read: Reader | None = None) -> tuple[int, int]:
    """(width, height) of the image at `path` as the decoder returns it, turned by its Orientation, read without
    decoding it (`imaging.file_header`: the first MiB of most files, the whole of a TIFF or of a JPEG whose frame header
    lies past that, and a PNG's chunk headers across the file, up to PNG_MAX_CHUNKS of them): AOI-INSP-001 for a file
    that cannot be read, AOI-INSP-004 for one that holds no image with a size. `read` as `file_header` takes it."""
    try:
        header = file_header(path, read)
    except OSError as e:
        raise AoiError("AOI-INSP-001", detail=str(e), path=path) from e
    if header is None or min(header[1], header[2]) <= 0:
        raise AoiError("AOI-INSP-004", path=path)
    return header[1], header[2]


def blind_label_ok(label: str, defect_type: str | None) -> bool:
    """A blind label of a calibration image is OK with no defect type, or NG with one of the 33 (REQ-TRN-016)."""
    return label == "OK" and defect_type is None or label == "NG" and defect_type in names()


def draw_calibration(ok: list[str], ng: list[str], seed: int) -> list[str]:
    """A calibration set to propose from the images labelled OK and NG (REQ-TRN-016): CALIBRATION_IMAGES of them drawn
    at random with `seed`, CALIBRATION_NG NG images or as many as there are, the rest OK, more NG where the OK images
    run short, in a random order, so that a labeller meets the NG images among the OK ones. Fewer images than a set
    holds make none: an empty list."""
    if len(ok) + len(ng) < CALIBRATION_IMAGES:
        return []
    rng = random.Random(seed)  # noqa: S311 - no secret: the set is audited as it is made
    n_ng = max(min(len(ng), CALIBRATION_NG), CALIBRATION_IMAGES - len(ok))
    drawn = rng.sample(ng, n_ng) + rng.sample(ok, CALIBRATION_IMAGES - n_ng)
    rng.shuffle(drawn)
    return drawn


def agreement(a: dict[str, tuple[str, str | None]], b: dict[str, tuple[str, str | None]]) -> dict[str, Any]:
    """Two labellers' blind labels of the same images, {sample: (label, defect type)}, compared (REQ-TRN-016):
    `ok_ng_agree` of the `images` alike in OK or NG, `type_agree` of the `both_ng` images both labelled NG alike in
    defect type, and `agreed` when both reach their targets, compared in whole numbers (98 of 100 reaches 98 %). With
    no image both labelled NG the defect types show no agreement, so the targets are not reached."""
    both_ng = [s for s in a if a[s][0] == b[s][0] == "NG"]
    ok_ng, types = sum(a[s][0] == b[s][0] for s in a), sum(a[s][1] == b[s][1] for s in both_ng)
    agreed = 100 * ok_ng >= OK_NG_TARGET * len(a) > 0 and 100 * types >= TYPE_TARGET * len(both_ng) > 0
    counts = {"images": len(a), "ok_ng_agree": ok_ng, "both_ng": len(both_ng), "type_agree": types}
    return counts | {"ok_ng_target": OK_NG_TARGET, "type_target": TYPE_TARGET, "agreed": agreed}
