"""Frozen dataset versions (REQ-TRN-005; stage S35): a version's name, its manifest and a file's hash. No Qt."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

REVISION = re.compile(r"[A-Za-z0-9]{1,16}")  # a board revision as entered with the board model, such as R3 (Q37)
ALLOWED_USES = ("own", "shared", "demos")  # their own AI models, shared improvement, demos: placeholders until Q38
FOLDER = "datasets"  # under the workspace: <name>/manifest.json


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
