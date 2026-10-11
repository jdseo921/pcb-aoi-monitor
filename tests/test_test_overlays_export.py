"""AI Model Test's Export Image Overlays (REQ-TST-004; GUI §5 Stage 1 deliverables, "Test result CSV and annotated
images"): an Admin copies a validation run's annotated images, one per row, named by row, image and verdict, misses and
false calls first, after a question naming their count; the copy is role-checked and audited on the run, and a row
whose overlay is gone is counted, not copied."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.errors import AoiError
from aoi.ui.pages.model_test import ModelTestPage
from tests.test_req_done_in_v01 import BOARD, _window


def _run(ctx: AppContext, synthetic_dataset: Path) -> list[dict[str, object]]:
    """A validation run on the test split's NG folder, as Run Test stores it, with its overlays."""
    ctx.set_user("engineer")
    _, rows, _ = ctx.batch_test(BOARD, str(synthetic_dataset / "test" / "ng"))
    assert rows and all(r.get("overlay") for r in rows)
    return rows


def test_req_tst_004_an_admin_exports_a_runs_annotated_images_audited_on_the_run(
    trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path
) -> None:
    """One file per row, `<row>_<image name>_<verdict>.png`, holding the overlay the run stored; the entry on the run
    counts the rows and the copies. A row whose overlay is gone is left out and counted as missing."""
    rows = _run(trained_ctx, synthetic_dataset)
    trained_ctx.set_user("engineer")
    with pytest.raises(AoiError) as refused:
        trained_ctx.export_test_overlays(rows, tmp_path / "refused")
    assert refused.value.code == "AOI-USR-001" and not (tmp_path / "refused").exists()
    trained_ctx.set_user("admin")
    out = tmp_path / "annotated"
    assert trained_ctx.export_test_overlays(rows, out) == len(rows)
    expected = [f"{i:04d}_{Path(str(r['image'])).stem}_{r['ai_result']}.png" for i, r in enumerate(rows, 1)]
    assert sorted(p.name for p in out.iterdir()) == sorted(expected)
    for name, r in zip(expected, rows, strict=True):
        assert (out / name).read_bytes() == Path(str(r["overlay"])).read_bytes()
    entry = trained_ctx.audit_entries(action="export.test_overlays")[0]
    assert (entry["object_type"], entry["object_uuid"]) == ("test_run", rows[0]["run_uuid"])
    assert {k: entry["after"][k] for k in ("rows", "copied", "missing", "cancelled")} == {
        "rows": len(rows), "copied": len(rows), "missing": 0, "cancelled": False,
    }  # fmt: skip
    failed = [dict(r) for r in rows]
    failed[-1]["pass_fail"] = "FAIL"  # a miss or a false call, however late in the run, is copied first
    stops = iter([False, True])
    assert trained_ctx.export_test_overlays(failed, tmp_path / "first", should_stop=lambda: next(stops)) == 1
    assert [p.name for p in (tmp_path / "first").iterdir()] == [expected[-1]]
    assert trained_ctx.audit_entries(action="export.test_overlays")[0]["after"]["cancelled"] is True
    gone = [dict(r) for r in rows]
    gone[0]["overlay"] = str(tmp_path / "no-such-overlay.png")
    assert trained_ctx.export_test_overlays(gone, tmp_path / "some") == len(rows) - 1
    assert trained_ctx.audit_entries(action="export.test_overlays")[0]["after"]["missing"] == 1


def test_req_tst_004_export_image_overlays_and_csv_ask_naming_the_count_then_write_on_the_pool(
    qtbot: QtBot, trained_ctx: AppContext, synthetic_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On AI Model Test an Admin's Export Image Overlays asks first, naming the run's image count, then copies the
    images into the folder picked and says how many; No copies nothing. Export CSV asks and writes the same way."""
    win = _window(qtbot, trained_ctx, "Admin")
    assert win.navigate("AI Model Test")
    page = win.pages["AI Model Test"]
    assert isinstance(page, ModelTestPage) and not page.btn_img.isHidden()
    page.folder = str(synthetic_dataset / "test" / "ng")
    page.run()
    qtbot.waitUntil(lambda: bool(page.rows) and page.btn_run.isEnabled(), timeout=60000)
    asked: list[str] = []
    answer = [QMessageBox.StandardButton.No]

    def question(_parent: object, _title: str, text: str, *_rest: object) -> QMessageBox.StandardButton:
        asked.append(text)
        return answer[0]

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    out = tmp_path / "annotated"
    out.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *_a, **_k: str(out)))
    page.btn_img.click()
    assert len(asked) == 1 and f"{len(page.rows)} images" in asked[0] and not any(out.iterdir())
    answer[0] = QMessageBox.StandardButton.Yes
    page.btn_img.click()
    qtbot.waitUntil(lambda: len(list(out.iterdir())) == len(page.rows), timeout=30000)
    qtbot.waitUntil(lambda: "annotated image(s)" in win.statusBar().currentMessage(), timeout=10000)
    assert f"Copied {len(page.rows)} annotated image(s)" in win.statusBar().currentMessage()
    # Export CSV beside them asks the same way, naming the count, then writes on the pool (REQ-SET-021)
    rows_csv = tmp_path / "results.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(rows_csv), "")))
    answer[0] = QMessageBox.StandardButton.No
    page.btn_csv.click()
    assert asked[-1] == f"Export the results of {len(page.rows)} images as CSV, one row per image?"
    assert not rows_csv.exists()
    answer[0] = QMessageBox.StandardButton.Yes
    page.btn_csv.click()
    qtbot.waitUntil(lambda: f"Exported {len(page.rows)} rows to" in win.statusBar().currentMessage(), timeout=10000)
    assert len(rows_csv.read_text(encoding="utf-8-sig").splitlines()) == len(page.rows) + 1
