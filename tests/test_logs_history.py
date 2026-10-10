"""Logs & Export at scale (stage S51): REQ-LOG-001, filters over 100,000 records within 1 s through the indexes of
migration 0022, a Result filter and every column sorting.

The 100,000 records are written straight into the workspace's database in one transaction, as many as a line stores in
months, rather than inspected one by one; their verdicts are drawn at random, so nothing here is an accuracy. The
machine, its CPU count and the Python version are printed with the times (pytest -s shows them): a time means nothing
without the machine it was measured on, and these are never quoted as the product's speed.
"""

from __future__ import annotations

import os
import platform
import random
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from aoi.core.services import AppContext
from aoi.times import local_day_bounds_utc
from aoi.ui.main_window import MainWindow
from aoi.ui.pages.logs import LogsPage

N = 100_000
DAYS = 200  # spread over the last 200 days: 500 a day
RETENTION_DAYS = 30  # older records are archived, as the start-up archive leaves them
BOARD_MODELS = [f"BM-{i}" for i in range(8)]
OPERATORS = ["operator", "engineer", "admin", "kim", "lee", "park"]  # the first three are users, which Operator lists
BUDGET_S = 1.0  # REQ-LOG-001


def seed(db_path: Path, now: datetime) -> list[dict[str, Any]]:
    """N records, with one to three defects for each NG or WARN one, in one transaction; returns the records, each
    with its `defect_count`."""
    rng = random.Random(51)
    old = (now - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    defects: list[tuple[Any, ...]] = []
    for i in range(1, N + 1):
        t = (now - timedelta(seconds=rng.randrange(DAYS * 86400))).isoformat(timespec="seconds")
        result = rng.choices(("OK", "NG", "WARN"), (90, 7, 3))[0]
        rows.append({"id": i, "uuid": str(uuid.UUID(int=i)), "time": t, "board_model": rng.choice(BOARD_MODELS),
                     "model_version": "v1.0", "recipe_rev": 1, "image_path": f"images/board_{i}.png",
                     "overlay_path": f"results/board_{i}.png", "view": "Top", "result": result, "score": rng.random(),
                     "operator": rng.choice(OPERATORS), "archived": int(t < old),
                     "defect_count": rng.randint(1, 3) if result != "OK" else 0})  # fmt: skip
        defects += [(i, n, "Scratch", 0.9, "Top", 1, 1, 4, 4) for n in range(1, rows[-1]["defect_count"] + 1)]
    columns = [k for k in rows[0] if k != "defect_count"]
    with closing(sqlite3.connect(db_path)) as c, c:  # the inner `with` commits once, at the end
        c.executemany(
            f"INSERT INTO inspections({', '.join(columns)}) VALUES({', '.join('?' * len(columns))})",
            [tuple(r[k] for k in columns) for r in rows],
        )
        c.executemany("INSERT INTO defects(inspection_id, no, type, score, side, x, y, w, h) VALUES(?,?,?,?,?,?,?,?,?)",
                      defects)  # fmt: skip
    return rows


def matching(rows: list[dict[str, Any]], date_from: str, date_to: str, archived: bool, **equal: str) -> set[int]:
    """The ids of `rows` a filter lists, worked out here rather than by the code under test."""
    start, end = local_day_bounds_utc(date_from, date_to)
    assert start and end
    return {
        r["id"]
        for r in rows
        if start <= r["time"] < end and (archived or not r["archived"]) and all(r[k] == v for k, v in equal.items())
    }


def local_day(now: datetime, days_ago: int) -> str:
    return (now.astimezone() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def test_req_log_001_filters_over_100000_records_return_within_1_s(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A combined filter, dates plus board model plus operator plus result, over 100,000 records returns within 1 s,
    the newest 7 days and an archived month alike (archived records stay searchable, REQ-LOG-003), and so do the last 7
    days of every board model; each reads its rows through an index of migration 0022, never the whole table, and each
    record's defects through `defects_inspection`. On the page, Filter with the combined filter, and with one that
    matches nothing (its empty state reads the history's span, not every record), shows within 1 s too."""
    for board_model in BOARD_MODELS:
        ctx.ensure_board_model(board_model)
    now = datetime.now(UTC)
    start = perf_counter()
    rows = seed(ctx.settings.db_path, now)
    seeded = perf_counter() - start
    week = (local_day(now, 7), local_day(now, 0))
    archived_month = (local_day(now, 90), local_day(now, 60))
    combined = "7 days, BM-3, engineer, NG"
    cases = {
        combined: ((*week, "BM-3", "engineer", False, "NG"), matching(
            rows, *week, False, board_model="BM-3", operator="engineer", result="NG")),
        "archived month, BM-5, lee, WARN": ((*archived_month, "BM-5", "lee", True, "WARN"), matching(
            rows, *archived_month, True, board_model="BM-5", operator="lee", result="WARN")),
        "7 days, every board model": ((*week, None, None, False, None), matching(rows, *week, False)),
    }  # fmt: skip
    sql: list[tuple[str, list[Any]]] = []
    query = ctx.db.query

    def recorded(statement: str, params: Any = ()) -> list[dict[str, Any]]:
        sql.append((statement, list(params)))
        return query(statement, params)

    monkeypatch.setattr(ctx.db, "query", recorded)
    times: dict[str, float] = {}
    for name, ((date_from, date_to, board_model, operator, archived, result), expected) in cases.items():
        start = perf_counter()
        found = ctx.inspections(date_from, date_to, board_model, operator, archived, result=result)
        times[name] = perf_counter() - start
        assert {r["id"] for r in found} == expected and expected, name
        assert all(r["defect_count"] == rows[r["id"] - 1]["defect_count"] for r in found), name
    plans = [[r["detail"] for r in query(f"EXPLAIN QUERY PLAN {s}", p)] for s, p in sql]
    for name, plan in zip(cases, plans, strict=True):
        assert not any(d.startswith("SCAN i") for d in plan), (name, plan)  # through an index of 0022
        assert any("defects_inspection" in d for d in plan), (name, plan)

    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("operator")
    page = cast(LogsPage, win.pages["Logs & Export"])
    start = perf_counter()
    win.navigate("Logs & Export")  # a new page lists the last 7 days of every board model: timed, not held to 1 s
    default, opened = perf_counter() - start, {r["id"] for r in page.rows}
    assert opened == cases["7 days, every board model"][1]
    for combo, value in ((page.model, "BM-3"), (page.operator, "engineer"), (page.result, "NG")):
        combo.setCurrentIndex(combo.findData(value))
    listed = {}
    for name, d_from in ((f"page: {combined}", page.d_from.date()), ("page: no match", QDate.currentDate().addDays(1))):
        page.d_from.setDate(d_from)
        start = perf_counter()
        page.refresh()  # Filter
        times[name] = perf_counter() - start
        listed[name] = {r["id"] for r in page.rows}
    assert listed == {f"page: {combined}": cases[combined][1], "page: no match": set()}
    assert page.empty.isVisibleTo(page)  # the empty state, with its link

    machine = f"{platform.platform()} {platform.machine()}, {os.cpu_count()} CPUs, Python {platform.python_version()}"
    print(f"\nREQ-LOG-001 on {machine}: {N} records seeded in {seeded:.2f} s")
    for (name, (_, expected)), plan in zip(cases.items(), plans, strict=True):
        print(f"  {name}: {len(expected)} records in {times[name] * 1000:.1f} ms; plan {plan}")
    print(f"  page opened on 7 days, every board model: {len(opened)} rows in {default * 1000:.1f} ms")
    for name in (f"page: {combined}", "page: no match"):
        print(f"  {name}: {times[name] * 1000:.1f} ms")
    assert max(times.values()) < BUDGET_S, times


def _logs(qtbot: QtBot, ctx: AppContext, user: str = "operator") -> LogsPage:
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user(user)  # every role views the history
    win.navigate("Logs & Export")
    return cast(LogsPage, win.pages["Logs & Export"])


def _record(
    ctx: AppContext, result: str, operator: str, board_model: str = "B", defects: int = 0, evidence: bool = False
) -> int:
    """A record written through the data layer; with `evidence`, an overlay and two map files under results/."""
    rec = {"board_model": board_model, "result": result, "operator": operator, "image_path": f"{result}.png",
           "model_version": "v1.0", "recipe_rev": 1, "view": "Top", "score": 0.5}  # fmt: skip
    if evidence:
        overlay = ctx.settings.results_dir / "2026-10-10" / f"board_{uuid.uuid4()}_{result}.png"
        overlay.parent.mkdir(parents=True, exist_ok=True)
        for key, path in (("overlay_path", overlay), ("diff_map_path", overlay.with_name(f"{overlay.stem}_diff.png")),
                          ("ai_map_path", overlay.with_name(f"{overlay.stem}_ai2.png"))):  # fmt: skip
            path.write_bytes(b"evidence")
            rec[key] = str(path)
    box = {"type": "Scratch", "score": 0.9, "x": 1, "y": 1, "w": 4, "h": 4}
    return ctx.db.add_inspection(rec, [{"no": n, **box} for n in range(1, defects + 1)])


def test_req_log_001_result_filter_lists_one_verdict(qtbot: QtBot, ctx: AppContext) -> None:
    """The Result filter offers All, OK, NG and WARN, and combines with the other filters."""
    ctx.ensure_board_model("B")
    ok, ng, warn = (_record(ctx, v, "kim") for v in ("OK", "NG", "WARN"))
    other = _record(ctx, "NG", "lee")
    page = _logs(qtbot, ctx)
    assert [page.result.itemData(i) for i in range(page.result.count())] == [None, "OK", "NG", "WARN"]
    assert {r["id"] for r in page.rows} == {ok, ng, warn, other}
    shown: dict[str, set[int]] = {}
    for verdict in ("OK", "NG", "WARN"):
        page.result.setCurrentIndex(page.result.findData(verdict))
        page.refresh()
        shown[verdict] = {r["id"] for r in page.rows}
    assert shown == {"OK": {ok}, "NG": {ng, other}, "WARN": {warn}}
    page.operator.setCurrentIndex(page.operator.findData("kim"))
    page.refresh()
    assert [r["id"] for r in page.rows] == [warn]
    page.d_from.setDate(QDate.currentDate().addDays(1))  # dates combine too: none from tomorrow on
    page.refresh()
    assert page.rows == [] and page.table.rowCount() == 0


def test_req_log_001_every_column_sorts(qtbot: QtBot, ctx: AppContext) -> None:
    """A click on any header sorts the table by that column, up and down: numbers as numbers, text as text."""
    ctx.ensure_board_model("B")
    ctx.ensure_board_model("A")
    for i, (verdict, who, bm) in enumerate([("NG", "lee", "B"), ("OK", "kim", "A"), ("WARN", "park", "B")]):
        _record(ctx, verdict, who, bm, defects=i * 5)  # 0, 5 and 10 defects: as numbers 5 < 10, as text "10" < "5"
    table = _logs(qtbot, ctx).table
    assert table.isSortingEnabled() and table.rowCount() == 3
    for column in range(table.columnCount()):
        for order in (Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder):
            table.horizontalHeader().setSortIndicator(column, order)
            values = [table.item(r, column).data(Qt.ItemDataRole.DisplayRole) for r in range(table.rowCount())]
            assert values == sorted(values, reverse=order == Qt.SortOrder.DescendingOrder), (column, values)


def test_req_log_001_the_filters_fit_a_1600_px_window(qtbot: QtBot, ctx: AppContext) -> None:
    """With the Result filter the filter row asked for 1358 px, so the window could not be narrower than 1648 px, past
    the 1600 x 900 the pages are laid out for (Training's Freeze sheet keeps it). The Board model and Operator lists
    now give way down to 80 px in a narrow window, cutting a long name off, and are as wide as their names where there
    is room, at 1920 px."""
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.set_user("admin")  # the Admin sees every button of the page
    win.navigate("Logs & Export")
    page = cast(LogsPage, win.pages["Logs & Export"])
    win.resize(1920, 1080)
    win.show()
    qtbot.waitExposed(win)
    assert win.minimumSizeHint().width() <= 1600, win.minimumSizeHint().width()
    assert [c.width() >= c.sizeHint().width() for c in (page.model, page.operator, page.result)] == [True] * 3
    room = "PANEL-A1-REV2-TOP-SIDE-2"  # 24 characters: a whole name at 1920 px
    ctx.ensure_board_model(room)
    page.on_show()
    page.model.setCurrentIndex(page.model.findText(room))
    qtbot.waitUntil(lambda: page.model.width() >= page.model.sizeHint().width() > 240)
    name = "PANEL-" + "X" * 34  # 40 characters: no rule limits a board model or user name's length
    ctx.ensure_board_model(name)
    ctx.add_user(name, "Operator")
    page.on_show()
    assert [page.model.itemText(2), page.operator.itemText(page.operator.count() - 1)] == [name, name]
    assert win.minimumSizeHint().width() <= 1600, win.minimumSizeHint().width()


def test_req_log_002_each_export_audits_the_filter_that_listed_its_records(
    qtbot: QtBot, ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Export CSV and Export Image Overlays ask first, naming the record count, and write into their audit entries the
    filter that listed the records (From, To, board model, operator, result, archived included) and their count,
    beside the user and time every entry holds: the filter Filter applied, not a box changed after it."""
    ctx.ensure_board_model("B")
    for verdict in ("NG", "NG", "OK"):
        _record(ctx, verdict, "kim", evidence=True)
    page = _logs(qtbot, ctx, "engineer")
    page.result.setCurrentIndex(page.result.findData("NG"))
    page.refresh()  # Filter
    page.result.setCurrentIndex(page.result.findData("WARN"))  # not applied: the table still lists the NG records
    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a: asked.append(a[2]) or QMessageBox.StandardButton.Yes)
    )
    out = tmp_path / "out"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out / "history.csv"), "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(out)))
    for export in (page.export_csv, page.export_overlays):
        export()
        qtbot.waitUntil(lambda: page._bg is None, timeout=30000)
    assert [q.split("?")[0] for q in asked] == ["Export CSV for 2 record(s)", "Export overlay images for 2 record(s)"]
    dates = (page.d_from.date().toString("yyyy-MM-dd"), page.d_to.date().toString("yyyy-MM-dd"))
    listed = {"date_from": dates[0], "date_to": dates[1], "board_model": None, "operator": None, "result": "NG",
              "include_archived": False}  # fmt: skip
    entries = [*ctx.audit_entries(action="export.overlays"), *ctx.audit_entries(action="export.csv")]
    assert [(e["object_type"], e["after"]["filter"], e["after"]["records"]) for e in entries] == [
        ("inspections", listed, 2), ("checks", listed, 2), ("inspections", listed, 2)
    ]  # fmt: skip
    assert {(e["user_uuid"], e["role"]) for e in entries} == {(ctx.db.user_uuid("engineer"), "Engineer")}
    assert entries[0]["after"]["copied"] == 2 and all(e["at_utc"].endswith("+00:00") for e in entries)
