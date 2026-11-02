#!/usr/bin/env python
"""Assemble the release kit a station verifies offline (REQ-SET-027; docs/release/runbook.md). CI runs it after the
installer passed its check (.github/workflows/build.yml), and keeps the folder as the run's `-kit` artifact:

    python tools/release_kit.py --setup dist/installer/AOI-PoC-Inspector-0.4.0-setup-x64-pilot-signed.exe --out kit
        [--provenance BUNDLE.jsonl --trusted-root trusted_root.jsonl]

The kit holds the installer; `pilot-ca.cer`, which a pilot station trusts (docs/install/pilot-signing.md); the release
note, `<version>.md` once it is named, else `unreleased.md`; `verify.ps1` and `inventory.ps1` (tools/release/); on
main and tags the build's provenance (`provenance.sigstore.json`) and Sigstore's trusted root, so `verify.ps1` checks
it without a network; and `SHA256SUMS.txt`, the hash of every other file, last. Exit 0 when written, 2 when a file is
missing.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script: the repository root holds the ``aoi`` package
    sys.path.insert(0, str(ROOT))

from aoi.config import APP_VERSION  # noqa: E402

SCRIPTS = ("verify.ps1", "inventory.ps1")
PROVENANCE, TRUSTED_ROOT, SUMS = "provenance.sigstore.json", "trusted_root.jsonl", "SHA256SUMS.txt"


def note(version: str = APP_VERSION, notes: Path = ROOT / "docs" / "release-notes") -> Path:
    """The release note of `version`, or the draft of the next one."""
    named = notes / f"{version}.md"
    return named if named.is_file() else notes / "unreleased.md"


def assemble(setup: Path, out: Path, provenance: Path | None = None, trusted_root: Path | None = None) -> list[str]:
    """Copy the kit's files into `out` (emptied first) and write SHA256SUMS.txt; the files' names, sums last."""
    copies = {setup.name: setup, "pilot-ca.cer": ROOT / "installer" / "pilot-ca.cer"}
    copies |= {f"release-note-{note().stem}.md": note()} | {s: ROOT / "tools" / "release" / s for s in SCRIPTS}
    if provenance is not None:
        copies |= {PROVENANCE: provenance} | ({TRUSTED_ROOT: trusted_root} if trusted_root is not None else {})
    missing = [str(p) for p in copies.values() if not p.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    lines = []
    for name, source in sorted(copies.items()):
        shutil.copyfile(source, out / name)
        with (out / name).open("rb") as f:
            lines.append(f"{hashlib.file_digest(f, 'sha256').hexdigest()}  {name}")
    (out / SUMS).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\r\n")
    return [*sorted(copies), SUMS]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--setup", type=Path, required=True, help="the installer, signed on main and tags")
    ap.add_argument("--out", type=Path, required=True, help="the kit's folder, emptied first")
    ap.add_argument("--provenance", type=Path, help="the build's Sigstore bundle (attest-build-provenance)")
    ap.add_argument("--trusted-root", type=Path, help="gh attestation trusted-root's output, for offline checks")
    a = ap.parse_args(argv)
    try:
        names = assemble(a.setup, a.out, a.provenance, a.trusted_root)
    except FileNotFoundError as e:
        print(f"The kit is not written; missing: {e}", file=sys.stderr)
        return 2
    print(f"Release kit in {a.out}: " + ", ".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
