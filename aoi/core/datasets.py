"""Frozen dataset versions (REQ-TRN-005; stage S35): a version's name, its manifest and a file's hash, and its split
into a training set and a locked validation set (REQ-TRN-006; S36). No Qt."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

REVISION = re.compile(r"[A-Za-z0-9]{1,16}")  # a board revision as entered with the board model, such as R3 (Q37)
ALLOWED_USES = ("own", "shared", "demos")  # their own AI models, shared improvement, demos: placeholders until Q38
FOLDER = "datasets"  # under the workspace: <name>/manifest.json
VALIDATION_OK = 50  # OK files a validation set holds at least: the 50 held out (Customers & Launch, Validation)
TRAIN_OK = 20  # OK files a training set holds at least, per board model and view (REQ-TRN-007)
VALIDATION_NG = Fraction(3, 10)  # and at least 30 % of the version's NG files, rounded up


def token(board_model: str) -> str:
    """The board model as a version's name gives it: its ASCII letters and digits in upper case (TBOX-A1: TBOXA1); empty
    for a name with none, such as one in Korean only, which no version can be named after (open for Jay, ADR 0009)."""
    return re.sub(r"[^A-Za-z0-9]", "", board_model).upper()


def name(board_model: str, revision: str, view: str, version: int) -> str:
    """DS-<BOARDMODEL>-<REV>-<VIEW>-v<N>: the board model's `token`, the revision as entered, the view in upper case,
    and N."""
    return f"DS-{token(board_model)}-{revision}-{view.upper()}-v{version}"


def sha256(path: str | Path) -> str:
    """The SHA-256 of a file's bytes in hex, read a block at a time; OSError when the file cannot be read."""
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def file_sha256(path: str | Path) -> str | None:
    """`sha256`, None when the file cannot be read."""
    try:
        return sha256(path)
    except OSError:
        return None


def manifest(head: dict[str, Any], files: list[dict[str, Any]]) -> tuple[bytes, str]:
    """The manifest's bytes and their SHA-256: the version's record and its files, keys sorted, so a version always
    gives the same bytes."""
    data = json.dumps({**head, "files": files}, indent=1, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    return data, hashlib.sha256(data).hexdigest()


def stratum(item: dict[str, Any]) -> str:
    """The defect type an NG file is split by: its label's, else its boxes' types in order joined by "+", else ""."""
    if item["defect_type"]:
        return str(item["defect_type"])
    return "+".join(sorted({str(b["dct_type"]) for b in item["boxes"]}))


def split(
    items: list[dict[str, Any]], seed: int, locked: set[str], trained: set[str]
) -> dict[str, list[dict[str, Any]]]:
    """A frozen version's files as "train" and "validation" (REQ-TRN-006), always the same for the same files, seed and
    earlier splits. A file whose SHA-256 an earlier split locked (in `locked`) is validation again; then, drawn with
    random.Random(seed), OK files until VALIDATION_OK are, and NG files until VALIDATION_NG of the NG are, rounded up,
    spread over the defect types (`stratum`) in proportion to their files: each next one from the type furthest below
    its share, ties in the draw's order. Files no earlier split put in training (not in `trained`) go first. Too few
    OK files is the caller's to refuse; each list keeps the files' order by SHA-256."""
    rng = random.Random(seed)  # noqa: S311 - no secret: the seed is stored and audited
    files = sorted(items, key=lambda i: (i["sha256"], i["uuid"]))  # not the rows' order: the same files split the same
    held = {i["uuid"] for i in files if i["sha256"] in locked}

    def free(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [i for i in pool if i["uuid"] not in held]

    def draw(pool: list[dict[str, Any]], n: int) -> None:
        for group in (
            [i for i in free(pool) if i["sha256"] not in trained],
            [i for i in free(pool) if i["sha256"] in trained],
        ):
            picked = rng.sample(group, min(max(n, 0), len(group)))
            held.update(i["uuid"] for i in picked)
            n -= len(picked)

    ok = [i for i in files if i["label"] == "OK"]
    draw(ok, VALIDATION_OK - (len(ok) - len(free(ok))))
    types: dict[str, list[dict[str, Any]]] = {}
    for i in files:
        if i["label"] == "NG":
            types.setdefault(stratum(i), []).append(i)
    order = sorted(types)
    rng.shuffle(order)
    room = {k: len(free(types[k])) for k in order}
    want = {k: VALIDATION_NG * len(types[k]) - (len(types[k]) - room[k]) for k in order}  # its share less those held
    take = dict.fromkeys(order, 0)
    need = math.ceil(VALIDATION_NG * sum(map(len, types.values()))) - sum(len(v) - room[k] for k, v in types.items())
    for _ in range(need):  # never more than the free NG files, since need <= NG files - held ones
        k = max((k for k in order if take[k] < room[k]), key=lambda k: want[k] - take[k])
        take[k] += 1
    for k in order:
        draw(types[k], take[k])
    return {"train": free(files), "validation": [i for i in files if i["uuid"] in held]}
