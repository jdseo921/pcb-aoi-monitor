"""REQ-TRN-021 for B5 of the 2026-10 business-readiness brief (docs/sketches/first-run-guide.md, "Errors", Q78): the
first-run guide says a refusal in its own words, a line `aoi/errors.py` keeps for each code its screens raise, with the
catalogue's title and the code, and the catalogue's own text behind Show Details. Every message stays an AoiError from
the catalogue, and docs/error-codes.md lists the guide's lines."""

from __future__ import annotations

import re
import string
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from aoi.core.services import REQUIRED_WHAT, ROLES_FROM, AppContext, ErrorReport
from aoi.errors import CODES, GUIDE, AoiError, render
from tests.test_explain import not_words
from tests.test_first_board_model_store import shell
from tests.test_first_run_guide import guide_of, typed

SCREENS = {  # the codes each screen raises: the sketch's table less a role's and Inspection's, with AOI-TRN-057
    1: ("AOI-TRN-019", "AOI-TRN-054", "AOI-TRN-005", "AOI-TRN-055", "AOI-TRN-056", "AOI-TRN-044", "AOI-TRN-053",
        "AOI-LOG-002"),
    2: ("AOI-INSP-001", "AOI-INSP-004", "AOI-INSP-006", "AOI-INSP-005", "AOI-INSP-007", "AOI-TRN-013", "AOI-TRN-014",
        "AOI-TRN-015", "AOI-TRN-016", "AOI-TRN-008", "AOI-TRN-009", "AOI-TRN-010", "AOI-TRN-011", "AOI-TRN-025",
        "AOI-TRN-030", "AOI-TRN-031", "AOI-TRN-032"),
    3: ("AOI-TRN-027", "AOI-TRN-022", "AOI-TRN-040", "AOI-TRN-041", "AOI-TRN-042", "AOI-TRN-047", "AOI-TRN-045",
        "AOI-TRN-043", "AOI-TRN-004", "AOI-TRN-052", "AOI-TRN-048", "AOI-TRN-049", "AOI-TST-003", "AOI-TRN-057"),
}  # fmt: skip
NOT_THE_GUIDES = ("dataset", "version", "freeze", "split", "lock", "manifest", "store", "epoch", "seed")  # sketch
PLACEHOLDER = re.compile(r"\{[^}]*\}")


def names(text: str) -> set[str]:
    return {n for _, n, _, _ in string.Formatter().parse(text) if n}


def test_req_trn_021_the_guide_has_its_own_line_for_each_code_it_raises() -> None:
    """Each code the guide's screens raise but a role's has a line of the guide's, and no other code: its
    {placeholders} are its code's own, and it uses none of the Charter's Not words or the words the guide leaves out.
    An error carries its line filled in, and an error of a code with none carries None. docs/error-codes.md lists each
    line with its title."""
    assert set(GUIDE) == {c for codes in SCREENS.values() for c in codes} and set(GUIDE) <= set(CODES)
    for code, line in GUIDE.items():
        entry = CODES[code]
        assert names(line) <= names(entry.what) | names(entry.action), code
        assert not_words(line) == [], (code, line)
        shown = PLACEHOLDER.sub(" ", line)
        assert not [w for w in NOT_THE_GUIDES if re.search(rf"\b{w}", shown, re.IGNORECASE)], (code, line)
    taken = AoiError("AOI-TRN-005", existing="TBOX-A1", name="tbox-a1")
    assert taken.guide == "TBOX-A1 is already here. Pick it in the top bar, or type another name."
    assert taken.what.startswith("Board model TBOX-A1 already exists")  # the catalogue's text stays as it was
    assert AoiError("AOI-USR-001", what="Training", roles="Engineer").guide is None
    report = ErrorReport.of(AoiError("AOI-TRN-047"))
    assert report.guide == "Wait for the training under way to end, then press Train again."
    stopped = {"path": "ok_02.png", "at": 3, "total": 4, "imported": 2, "name": "TBOX-A1"}
    assert AoiError("AOI-TRN-009", reason="the drive is full", **stopped).guide == (
        "Copying stopped at image 3 of 4; the ones before it are kept. Check the USB drive and the free space, then"
        " pick the folder again."
    )  # what the drive or its space can cause
    assert AoiError("AOI-TRN-010", reason="the path is too long", **stopped).guide == (
        "Copying stopped at image 3 of 4 (the path is too long); the ones before it are kept. Fix that, then pick the"
        " folder again."
    )  # any other error, named, as Training says it (#245)
    assert (
        "| AOI-TRN-047 | Training already running | Wait for the training under way to end, then press Train again. |"
        in render()
    )


def test_req_trn_021_a_refusal_says_the_guides_line_and_shows_the_details(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[Any]
) -> None:
    """Create refused on screen 1 says the catalogue's title, the guide's line and the code, with no dialog; Show
    Details opens the catalogue's own text under it and Hide Details closes it. A code the guide has no line for is
    said as the catalogue says it, with no Show Details; typing again takes the refusal away. A line of the guide's own
    said after a refusal has nothing behind Show Details."""
    win = shell(qtbot, ctx)
    win.navigate("Home")
    guide = guide_of(win)
    typed(qtbot, guide, "TBOX-A1", "Acme")

    def refused(name: str, customer: str) -> Any:
        raise AoiError("AOI-TRN-044", store=customer, reason="the station's key store refused it")

    monkeypatch.setattr(ctx, "create_customer_board_model", refused)
    guide.btn_create.click()
    said = guide.refused
    assert said.isVisible() and said.code == "AOI-TRN-044" and dialogs == []
    assert said.text() == (
        "Dataset store not changed: Nothing was made: the station's key store refused it. (AOI-TRN-044)"
    )  # the catalogue's title, the guide's line and the code
    assert said.btn_details.isVisible() and said.btn_details.text() == "Show Details" and not said.details.isVisible()
    said.btn_details.click()
    assert said.details.isVisible() and said.btn_details.text() == "Hide Details"
    assert said.details.text().startswith("The dataset store of Acme was not changed: the station's key store refused")
    said.btn_details.click()
    assert not said.details.isVisible() and said.btn_details.text() == "Show Details"

    def not_allowed(name: str, customer: str) -> Any:  # as `requires` raises it, were the role changed underneath
        what = REQUIRED_WHAT["create_customer_board_model"]
        raise AoiError("AOI-USR-001", what=what, roles=ROLES_FROM["Admin"])

    monkeypatch.setattr(ctx, "create_customer_board_model", not_allowed)
    guide.btn_create.click()
    assert said.code == "AOI-USR-001" and not said.btn_details.isVisible() and not said.details.isVisible()
    assert said.text() == (
        "Not allowed for this role: Creating a board model in a customer's dataset store needs the Admin role. Sign in"
        " as a user with that role, or ask one to do it. (AOI-USR-001)"
    )
    typed(qtbot, guide, "TBOX-A2", "Acme")
    assert not said.isVisible() and said.code is None and said.text() == ""
    said.say(ErrorReport.of(AoiError("AOI-TRN-047")))
    said.btn_details.click()
    said.say_text("Train was cancelled.")  # a line of the guide's own after a refusal: nothing behind Show Details
    assert said.text() == "Train was cancelled." and said.code is None
    assert said.btn_details.isHidden() and said.details.isHidden() and said.details.text() == ""
