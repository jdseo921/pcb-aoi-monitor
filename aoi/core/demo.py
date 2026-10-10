"""The demo workspace (REQ-SET-007; S53; Customers & Launch, "Demos"). No Qt.

`tools/make_demo_bundle.py` builds the bundle at build time; the app loads it in one click into a folder of its own
beside the production workspace, resets it to the bundle in under 10 s, and never reads or writes the production
workspace meanwhile. A bundle is a folder:

    bundle.json      the manifest: the format, the app version that built it, the board model, the demo boards in the
                     order a scripted run plays them with the verdict each got when the bundle was built, and the
                     SHA-256 of every other file of the bundle
    store-key.json   the key of the demo board model's dataset store: its images are synthetic boards (ADR 0010 gives
                     our own and synthetic boards a store too), and the key goes to the station's key store at each
                     load and reset, never into the workspace
    workspace/       a workspace as the app leaves it: aoi.sqlite, images/, models/, recipes/, datasets/, and
                     demo-boards/ with the boards a scripted run plays

The demo folder is the production workspace's folder name with "-Demo" after it, in the same parent folder. demo.json
in it marks it as a demo workspace, so a load or a reset never deletes or overwrites a folder that is not one.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..config import Settings
from ..data import atomic, credentials
from ..errors import QT_TRANSLATE_NOOP, AoiError
from ..times import now_utc

FORMAT = 1
BUNDLE_FILE = "bundle.json"
KEY_FILE = "store-key.json"
WORKSPACE = "workspace"
BOARDS = "demo-boards"  # in the workspace: the boards a scripted run plays (REQ-SET-009)
MARKER = "demo.json"
KEEP = frozenset({"settings.json", MARKER})  # what a reset leaves in the demo folder
BUILD_ONLY = frozenset({"logs", ".aoi.lock"})  # what a workspace holds while it is open, left out of a bundle


def bundle_dir() -> Path:
    """Where the bundle is: the AOI_DEMO_BUNDLE folder when set, demo-bundle/ beside the app's files in a build
    (PyInstaller's folder), or demo-bundle/ in the repository when the app runs from its sources."""
    if folder := os.environ.get("AOI_DEMO_BUNDLE"):
        return Path(folder)
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "demo-bundle"
    return Path(__file__).resolve().parents[2] / "demo-bundle"


def demo_folder(production: Path) -> Path:
    """The demo workspace of the production workspace `production`: its own folder beside it, never inside it."""
    return production.parent / f"{production.name or 'AOI_Workspace'}-Demo"  # no name: a drive's root folder


def is_demo(folder: Path) -> bool:
    """True when `folder` is a demo workspace, as its demo.json says."""
    return (folder / MARKER).is_file()


def sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def file_hashes(folder: Path) -> dict[str, str]:
    """The SHA-256 of every file under `folder`, by its path relative to `folder` with forward slashes."""
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def read_bundle(bundle: Path) -> dict[str, Any]:
    """The bundle's manifest once every other file of the bundle matches it, none missing and none added; refused with
    AOI-SET-015 naming what is wrong: no manifest, one that is not this format, or a file that does not match."""
    try:
        manifest: dict[str, Any] = json.loads((bundle / BUNDLE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise AoiError("AOI-SET-015", str(e), path=str(bundle), reason=NO_MANIFEST) from e
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise AoiError("AOI-SET-015", path=str(bundle), reason=OTHER_FORMAT)
    files = {n: h for n, h in file_hashes(bundle).items() if n != BUNDLE_FILE}
    wrong = sorted(set(files) ^ set(manifest.get("files", {})))
    wrong += sorted(n for n, h in files.items() if manifest["files"].get(n, h) != h)
    if wrong:
        raise AoiError("AOI-SET-015", path=str(bundle), reason=CHANGED.fill(file=wrong[0], count=len(wrong)))
    return manifest


NO_MANIFEST = QT_TRANSLATE_NOOP("Errors", "it has no readable bundle.json")
OTHER_FORMAT = QT_TRANSLATE_NOOP("Errors", "its bundle.json is not one this version of the app reads")
CHANGED = QT_TRANSLATE_NOOP("Errors", "{count} file(s) do not match its bundle.json, the first {file}")


def load(bundle: Path, folder: Path, settings: dict[str, Any], keys: credentials.Credentials) -> dict[str, Any]:
    """Make `folder` the demo workspace of `bundle` and return the bundle's manifest: copied from the bundle with
    `settings` as its settings.json (the workspace set to `folder`) when it is not a demo workspace yet, kept as it is
    when it is one already, so a second load goes on where the demo was. The demo store's key goes to `keys` either way.
    Refused with AOI-SET-015 for a bundle that is missing or damaged and AOI-SET-016 for a folder that exists, is not
    empty and is not a demo workspace; nothing is written then."""
    manifest = read_bundle(bundle)
    if not is_demo(folder):
        if folder.exists() and any(folder.iterdir()):
            raise AoiError("AOI-SET-016", path=str(folder))
        _copy_in(bundle, folder)
        atomic.write_text(folder / "settings.json", json.dumps(settings | {"workspace": str(folder)}, indent=2))
        marker = {
            "bundle_built_at": manifest["built_at"],
            "loaded_at": now_utc(),
            "board_model": manifest["board_model"],
        }
        atomic.write_text(folder / MARKER, json.dumps(marker, indent=2))  # last: a folder half copied is no demo yet
    _store_key(bundle, keys)
    return manifest


def load_beside(settings: Settings, keys: credentials.Credentials | None = None) -> Path:
    """The demo workspace beside the workspace of `settings`, loaded from the installed bundle (`bundle_dir`) when it
    is not there yet and kept as it is when it is, with the station's own settings (AI device, language and the rest),
    opening at Inspection, where its boards are queued; its folder. The key goes to `keys`, else to the station's key
    store. AoiError as `load` refuses it (AOI-SET-015, AOI-SET-016)."""
    folder = demo_folder(settings.root)
    values = asdict(settings)
    del values["workspace"]  # load() sets the demo folder
    load(bundle_dir(), folder, values | {"last_page": "Inspection"}, keys or credentials.default())
    return folder


def reset(bundle: Path, folder: Path, keys: credentials.Credentials) -> float:
    """Put the demo workspace `folder` back as `bundle` holds it and return the seconds it took: every file but
    settings.json and demo.json is deleted, results, records and logs included, and the bundle's workspace copied in
    again. The workspace must be closed. Refused with AOI-SET-015 for a bundle that is missing or damaged, AOI-SET-016
    for a folder that is not a demo workspace (nothing is deleted then), and AOI-SET-017 for a file another program
    holds; the folder stays a demo workspace, so a second reset finishes what the first left."""
    started = time.monotonic()
    read_bundle(bundle)
    if not is_demo(folder):
        raise AoiError("AOI-SET-016", path=str(folder))
    try:
        for child in folder.iterdir():
            if child.name in KEEP:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        _copy_in(bundle, folder)
    except OSError as e:
        raise AoiError("AOI-SET-017", str(e), path=str(e.filename or folder), error=e.strerror or str(e)) from e
    _store_key(bundle, keys)
    return time.monotonic() - started


def _copy_in(bundle: Path, folder: Path) -> None:
    """The bundle's workspace files into `folder`, each copied crash-safe (temporary name, then renamed)."""
    src = bundle / WORKSPACE
    for p in sorted(src.rglob("*")):
        if p.is_file():
            atomic.copy_file(p, folder / p.relative_to(src))


def _store_key(bundle: Path, keys: credentials.Credentials) -> None:
    """The demo store's key into the station's key store, under the name the app reads it by (REQ-TRN-017)."""
    try:
        held = json.loads((bundle / KEY_FILE).read_text(encoding="utf-8"))
        keys.write(credentials.STORE_PREFIX + held["store_uuid"], bytes.fromhex(held["key"]))
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise AoiError("AOI-SET-015", str(e), path=str(bundle), reason=NO_KEY) from e


NO_KEY = QT_TRANSLATE_NOOP("Errors", "its store-key.json cannot be read")
