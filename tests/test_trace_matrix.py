"""tools/trace_matrix.py reads a register, test ids and commit subjects into the matrix and the G1 gate (S07)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools import trace_matrix as tm

REGISTER = """# Fixture register

| ID | The app shall… | Acceptance criteria | Source | Priority | v0.1 | Impacts |
|---|---|---|---|---|---|---|
| REQ-INSP-001 | load images | files open | GUI §5 | MUST G1 | Partial: no size check | Doc |
| REQ-INSP-002 | show the verdict first | 40 pt | GUI §4.1 | MUST G1 | Done: inspection.py:60 | Scr |
| REQ-CMP-001 | link zoom and pan | within 1 px | Jay | SHOULD G1 | Done | none |
| REQ-USR-002 | sign in | password | ADR 0002 | MUST 1.0 | No | Sch |
"""

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="5">
<testcase classname="tests.test_a" name="test_req_insp_001_png_opens" time="0.1"/>
<testcase classname="tests.test_a" name="test_req_insp_001_bmp_opens" time="0.1"><failure message="x"/></testcase>
<testcase classname="tests.test_a" name="test_req_cmp_001_linked[ok_00]" time="0.1"/>
<testcase classname="tests.test_a" name="test_req_cmp_001_linked[ok_01]" time="0.1"/>
<testcase classname="tests.test_a" name="test_req_usr_002_sign_in" time="0.1"><skipped message="later"/></testcase>
<testcase classname="tests.test_a" name="test_layers" time="0.1"/>
</testsuite></testsuites>
"""

SUBJECTS = [
    "[REQ-INSP-002] feat: verdict banner with a shape (S18)",
    "[#5] test: fixtures (S05a)",
    "[REQ-INSP-002] feat: verdict banner with a shape (S18)",
    "[REQ-ZZZ-999] fix: cites an unknown row",
    "docs: no citation",
]


@pytest.fixture
def register(tmp_path: Path) -> Path:
    (tmp_path / "stage1.md").write_text(REGISTER, encoding="utf-8")
    return tmp_path


def test_register_rows_and_matrix_columns(register: Path, tmp_path: Path) -> None:
    reqs = tm.read_register(register)
    assert list(reqs) == ["REQ-INSP-001", "REQ-INSP-002", "REQ-CMP-001", "REQ-USR-002"]
    assert (reqs["REQ-INSP-001"].priority, reqs["REQ-INSP-001"].v01) == ("MUST G1", "Partial: no size check")
    junit = tmp_path / "junit.xml"
    junit.write_text(JUNIT, encoding="utf-8")
    rows, unknown = tm.build(reqs, [], tm.read_junit(junit), SUBJECTS)
    by_id = {r.req.id: r for r in rows}
    assert by_id["REQ-INSP-001"].result == "FAIL (1 of 2 failing)"
    assert by_id["REQ-INSP-002"].result == "no test"
    assert by_id["REQ-INSP-002"].commits == ["[REQ-INSP-002] feat: verdict banner with a shape (S18)"]
    assert by_id["REQ-CMP-001"].tests == ["test_a.py::test_req_cmp_001_linked"]  # parameter cases fold into one
    assert by_id["REQ-CMP-001"].result == "pass (1)"
    assert by_id["REQ-USR-002"].result == "not run (1 of 1)"  # skipped counts as not run
    assert unknown == ["commit '[REQ-ZZZ-999] fix: cites an unknown row' cites REQ-ZZZ-999"]
    md, csv_path = tm.write(rows, tmp_path / "out")
    assert "| REQ-INSP-001 | MUST G1 | Partial | — | test_a.py::test_req_insp_001_bmp_opens; " in md.read_text()
    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == "id,priority,v01,commits,tests,last_result"


def test_collected_names_count_as_not_run_and_unknown_test_ids_are_reported(register: Path, tmp_path: Path) -> None:
    collected = tmp_path / "collected.txt"
    collected.write_text(
        "tests/test_b.py::test_req_cmp_001_pan[x]\ntests/test_b.py::test_req_nope_001_x\n\n2 tests collected\n"
    )
    rows, unknown = tm.build(tm.read_register(register), tm.read_collected(collected), {}, [])
    assert next(r for r in rows if r.req.id == "REQ-CMP-001").result == "not run (1 of 1)"
    assert unknown == ["test test_b.py::test_req_nope_001_x cites REQ-NOPE-001"]


def test_gate_fails_on_an_unproven_must_row_and_passes_when_every_must_row_passes(register: Path) -> None:
    reqs = tm.read_register(register)
    outcomes = {"test_a.py::test_req_insp_001_png_opens": "passed", "test_a.py::test_req_insp_002_banner": "passed"}
    rows, unknown = tm.build(reqs, [], outcomes, [])
    assert tm.gate(rows, unknown, "G1") == []  # REQ-CMP-001 is SHOULD, REQ-USR-002 is 1.0: not gated for G1
    assert tm.gate(rows, unknown, "1.0") == ["REQ-USR-002 (MUST 1.0): no test"]
    rows, unknown = tm.build(reqs, [], {"test_a.py::test_req_insp_002_banner": "failed"}, [])
    assert tm.gate(rows, unknown, "G1") == [
        "REQ-INSP-001 (MUST G1): no test",
        "REQ-INSP-002 (MUST G1): FAIL (1 of 1 failing)",
    ]


def test_the_real_register_parses_and_every_test_function_cites_a_known_row() -> None:
    reqs = tm.read_register(tm.ROOT / "docs" / "requirements")
    assert len(reqs) >= 90
    defined = re.compile(r"^def (test_req_[a-z0-9_]+)", re.M)
    cited = {
        tm.cited_requirement(name)
        for p in (tm.ROOT / "tests").rglob("test_*.py")
        for name in defined.findall(p.read_text(encoding="utf-8"))
    }
    assert cited and cited - set(reqs) == set()
