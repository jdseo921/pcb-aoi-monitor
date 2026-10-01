"""Source rules from the Engineering standard that a reviewer should never have to re-check by hand."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = (ROOT / "aoi", ROOT / "tools")
SOURCE_FILES = (ROOT / "main.py",)


def _source_files() -> list[Path]:
    files = [p for d in SOURCE_DIRS for p in d.rglob("*.py")]
    files.extend(SOURCE_FILES)
    return sorted(files)


def test_req_trn_014_no_unsafe_torch_load_in_source() -> None:
    """REQ-TRN-014: every torch.load in the app is weights-only (Engineering, "Untrusted inputs")."""
    offenders = [
        str(p.relative_to(ROOT)) for p in _source_files() if "weights_only=False" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"weights_only=False found in {offenders}"
