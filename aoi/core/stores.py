"""Which files a customer's dataset store holds (REQ-TRN-017; S38; ADR 0010, decision 5). No Qt.

A board model's store holds every file under images/<board model>/ (its samples, the reference among them, and the
files of samples deleted since, which frozen versions may still name) and datasets/<name>/manifest.json of each of its
frozen versions. Its AI models and golden boards under models/ are derived and stay plain (ADR 0010, Consequences)."""

from __future__ import annotations

from pathlib import Path

from . import crypto, datasets

IMAGES = "images"  # Settings.images_dir, relative to the workspace


def owner(stored: str) -> tuple[str, str] | None:
    """For a workspace-relative path as the rows store it: ("images", board model) for a file under images/,
    ("datasets", version name) for one under datasets/, else None (results, models, a file outside the workspace)."""
    parts = stored.replace("\\", "/").split("/")
    if len(parts) < 3 or parts[0] not in (IMAGES, datasets.FOLDER) or not parts[1]:
        return None
    return parts[0], parts[1]


def files_of(root: Path, board_model: str, versions: list[str]) -> list[Path]:
    """The files of `board_model` a store holds, in a fixed order: under images/<board model>/, then each version's
    manifest that exists."""
    folder = root / IMAGES / board_model
    found = sorted(p for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []
    manifests = [root / datasets.FOLDER / name / "manifest.json" for name in versions]
    return found + [m for m in manifests if m.is_file()]


def header_of(path: Path) -> crypto.Header | None:
    """The format-1 header the file starts with, None for a plain file; reads only that much."""
    with open(path, "rb") as f:
        return crypto.header(f.read(crypto.HEADER.size + crypto.TAG_BYTES))
