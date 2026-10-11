"""REQ-INSP-017 (ADR 0014): each shift starts with the master samples, a known-OK board and a known-NG board of each
Critical defect type, judged with the engine in use; boards are inspected only while a passed check counts, and a
failed check stops the line with an alarm."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from aoi import config
from aoi.config import Settings
from aoi.core.imaging import list_images
from aoi.core.services import AppContext
from aoi.errors import AoiError
from tests.test_req_done_in_v01 import BOARD, _window

pytestmark = pytest.mark.shift_check  # the check stays on, as a station has it (tests/conftest.py)


def test_req_insp_017_a_passed_check_lets_boards_in_and_is_audited(trained_ctx: AppContext) -> None:
    """The master samples are the oldest OK sample and the oldest NG sample of each Critical type; before a check no
    board may be inspected (AOI-INSP-016), and a check that judges every one right counts for the shift, stored and
    audited with what judged it."""
    samples = trained_ctx.master_samples(BOARD)
    assert [s["expected"] for s in samples] == ["OK", "NG", "NG"]
    assert [s["defect_type"] for s in samples[1:]] == ["Missing Component", "Solder Bridge"]  # TINY's Critical types
    assert trained_ctx.shift_check(BOARD)["state"] == "none"
    with pytest.raises(AoiError) as refused:
        trained_ctx.require_shift_check(BOARD)
    assert refused.value.code == "AOI-INSP-016" and "no shift check has run" in str(refused.value)
    found = trained_ctx.run_shift_check(BOARD)
    assert found["state"] == "passed" and found["check"]["passed"] and found["hours"] == 12
    assert [r["right"] for r in found["check"]["rows"]] == [True, True, True]
    assert trained_ctx.require_shift_check(BOARD)["state"] == "passed"
    (entry,) = trained_ctx.audit_entries(action="inspection.shift_check")
    assert entry["after"]["passed"] is True and entry["role"] == "Engineer"
    assert [r["sample_uuid"] for r in entry["after"]["rows"]] == [s["uuid"] for s in samples]
    assert found["check"]["inputs"]["reference_path"] == trained_ctx.db.reference(BOARD)


def test_req_insp_017_a_change_or_a_new_shift_asks_again(trained_ctx: AppContext) -> None:
    """A saved recipe makes the check stop counting, as would an activation, a Golden board or a scale; a check older
    than the setting's hours has expired; 0 hours asks for none."""
    trained_ctx.run_shift_check(BOARD)
    trained_ctx.save_recipe(trained_ctx.recipe(BOARD)[1], "a new revision")
    assert trained_ctx.shift_check(BOARD)["state"] == "changed"
    trained_ctx.run_shift_check(BOARD)
    assert trained_ctx.shift_check(BOARD)["state"] == "passed"
    trained_ctx.db.execute("UPDATE shift_checks SET time='2026-01-01T00:00:00+00:00'")
    found = trained_ctx.shift_check(BOARD)
    assert (found["state"], found["until"]) == ("expired", "2026-01-01T12:00:00+00:00")
    with pytest.raises(AoiError, match="more than 12 hours old"):
        trained_ctx.require_shift_check(BOARD)
    trained_ctx.settings.shift_check_hours = 0
    assert trained_ctx.require_shift_check(BOARD)["state"] == "off"


def test_req_insp_017_a_wrong_verdict_fails_the_check_and_alarms(trained_ctx: AppContext) -> None:
    """A known board judged wrongly fails the check: it is stored and audited as failed, an NG alarm AOI-INSP-016
    keeps it, and no board may be inspected until a check passes."""
    ok_master = trained_ctx.master_samples(BOARD)[0]
    trained_ctx.update_sample(int(ok_master["id"]), "NG", "Solder Bridge")  # now the oldest Solder Bridge sample
    found = trained_ctx.run_shift_check(BOARD)
    assert found["state"] == "failed" and not found["check"]["passed"]
    wrong = [r for r in found["check"]["rows"] if not r["right"]]
    assert [(r["sample_uuid"], r["expected"], r["verdict"]) for r in wrong] == [(ok_master["uuid"], "NG", "OK")]
    alarm = trained_ctx.alarms()[0]
    assert (alarm["level"], alarm["code"]) == ("NG", "AOI-INSP-016") and "1 of 3 wrong" in alarm["message"]
    with pytest.raises(AoiError, match="judged a master sample wrongly"):
        trained_ctx.require_shift_check(BOARD)


def test_req_insp_017_no_master_sample_refuses_and_stores_nothing(ctx: AppContext, synthetic_dataset: Path) -> None:
    """A board model with OK samples only has no known-NG board to judge: AOI-INSP-017 names what is missing, and
    no check, entry or alarm is stored."""
    ok = [str(p) for p in list_images(synthetic_dataset / "train" / "ok")][:2]
    ctx.import_samples("FRESH", ok, "OK")
    with pytest.raises(AoiError) as refused:
        ctx.run_shift_check("FRESH")
    assert refused.value.code == "AOI-INSP-017" and "labelled NG" in str(refused.value)
    assert ctx.shift_check("FRESH")["state"] == "none"
    assert not ctx.audit_entries(action="inspection.shift_check") and not ctx.alarms()


def test_req_insp_017_inspection_waits_for_the_check(
    qtbot: QtBot, trained_ctx: AppContext, ng_board: Path, dialogs: list[tuple[str, str]]
) -> None:
    """On Inspection, Next Board before a check shows AOI-INSP-016 and takes no board from the queue; Shift Check
    (F7) by an Operator judges the master samples, lists them under the banner, and the board is then inspected."""
    win = _window(qtbot, trained_ctx, "Operator")
    page = win.pages["Inspection"]
    win.navigate("Inspection")
    assert "Shift check needed" in page.shift_line.text()
    page._set_queue([ng_board])
    page.next_board()
    assert dialogs and dialogs[-1][0].startswith("AOI-INSP-016") and page.queue_pos == -1 and page.worker is None
    assert page.act_check.isEnabled() and page.act_check.shortcut().toString() == "F7"
    page.act_check.trigger()
    qtbot.waitUntil(lambda: "Shift check passed" in page.shift_line.text(), timeout=30000)
    assert "3 of 3 master samples judged right" in page.summary.text()
    assert trained_ctx.audit_entries(action="inspection.shift_check")[0]["role"] == "Operator"
    page.next_board()
    qtbot.waitUntil(lambda: page.last is not None, timeout=30000)
    assert page.last.verdict == "NG" and len(dialogs) == 1


def test_req_insp_017_the_setting_is_12_hours_and_0_to_24() -> None:
    """A station asks for a check every 12 hours by default; an Admin sets 0 (none asked for) to 24 on Settings, and
    settings.json holding another value is refused with AOI-SET-008."""
    assert config.SHIFT_CHECK_HOURS == 12 and Settings().shift_check_hours == 12
    for hours in (0, 24):
        Settings.check("shift_check_hours", hours)
    for wrong in (-1, 25, "12", True):
        with pytest.raises(AoiError) as refused:
            Settings.check("shift_check_hours", wrong)
        assert refused.value.code == "AOI-SET-008"
