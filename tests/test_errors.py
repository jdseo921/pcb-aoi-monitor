"""REQ-LOG-004 (codes part) and REQ-SET-019 (error half): one catalogue of error codes, stage S12a."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aoi import errors
from aoi.core.imaging import load_image
from aoi.core.services import AppContext
from aoi.errors import AoiError

CODE = re.compile(r"^AOI-([A-Z0-9]+)-(\d{3})$")


def test_req_log_004_error_code_doc_matches_the_registry() -> None:
    assert errors.DOC_PATH.read_text(encoding="utf-8") == errors.render(), "run: python -m aoi.errors"
    assert errors.main(["--check"]) == 0


def test_req_log_004_codes_are_well_formed() -> None:
    assert errors.CODES, "the catalogue is empty"
    for code, entry in errors.CODES.items():
        m = CODE.match(code)
        assert m and m.group(1) in errors.AREAS, code
        assert entry.code == code and entry.title and entry.what.endswith(".") and entry.action.endswith("."), code
    assert sorted(errors.CODES) == [c.code for c in sorted(errors.CODES.values(), key=lambda c: c.code)]


def test_req_set_019_errors_carry_code_what_and_action() -> None:
    e = AoiError("AOI-TRN-001", detail="traceback goes to the log", path="old.pt", reason="RuntimeError")
    assert str(e).startswith("AOI-TRN-001 AI model file refused: old.pt could not be loaded as a weights-only model")
    assert e.message == f"{e.what} {e.action}" and "Train the board model again" in e.action
    assert e.detail == "traceback goes to the log" and e.detail not in str(e)
    with pytest.raises(KeyError):
        AoiError("AOI-ZZZ-999")


def test_req_set_019_engine_errors_a_user_can_see_have_codes(tmp_path: Path, ctx: AppContext) -> None:
    with pytest.raises(AoiError) as unreadable:
        load_image(tmp_path / "missing.png")
    assert unreadable.value.code == "AOI-INSP-001" and "missing.png" in unreadable.value.what
    with pytest.raises(AoiError) as no_boards:
        ctx.train("EMPTY", epochs=1, image_size=32)
    assert no_boards.value.code == "AOI-TRN-002" and "0 found" in no_boards.value.what
