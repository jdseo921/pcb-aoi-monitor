"""REQ-TRN-005 for B4 of the 2026-10 business-readiness brief (D4 part, F9; ADR 0023): a new board model's name meets
the rule freeze applies (AOI-TRN-039, `datasets.token`) where it is entered, not after its images are labelled. A name
with no Latin letter or digit, which its dataset versions are named with, is refused with AOI-TRN-054 by every call
that makes a board model, writing nothing, and the New board model dialog says so as the name is typed, Create off. A
board model a workspace already holds under such a name, made before, is kept as it was, and freeze still refuses it.

Jay's decision of 2026-10-13 (ADR 0023, decisions 6 and 7) adds two refusals at entry: a name that looks the same as an
existing one on a screen (AOI-TRN-055) and one whose Latin letters and digits are an existing name's, so its versions
would take that board model's names (AOI-TRN-056, the rule freeze applies with AOI-TRN-040)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QLineEdit
from pytestqt.qtbot import QtBot

from aoi.core import datasets
from aoi.core.imaging import list_images
from aoi.core.services import AppContext, looks
from aoi.data import credentials
from aoi.errors import AoiError
from tests.test_dataset_stores import as_admin
from tests.test_first_board_model_store import opened, shell

# The names + New board model and a first import took, which freeze then refused with AOI-TRN-039 (F9): Korean only,
# symbols only, full-width Latin letters and digits (as a Korean input method types them in full-width mode), Cyrillic
# and Greek capitals that look like Latin ones, an emoji, and a single accented or German letter.
SLIPPED = ["보드", "기판 이호", "---", "___", "ＴＢＯＸ", "１２３", "АБВ", "ΑΒΓ", "😀", "é", "ß"]
# Names with a Latin letter or digit: taken, other letters and spaces kept. 기판 2호's digit names its versions DS-2-…
TAKEN = ["TBOX-A1", "tbox c3", "TBOX-A4 메인보드", "7", "기판 2호"]
# Names + New board model and a first import took beside the first, which freeze then refused once the first had a
# version (AOI-TRN-040), or which a person cannot tell from the first on a screen: each is refused at entry now.
MIXED = [  # the same Latin letters and digits, so the same DS-<BOARDMODEL>-…: AOI-TRN-056
    ("TBOX-A1", "tbox a1"),
    ("TBOX-A1", "TBOX_A1"),
    ("CAL-1", "CAL_1"),
    ("TBOX-A1", "TBOX–A1"),  # an en dash
    ("TBOX-A1", "TBOX-A1 메인보드"),
    ("보드 1", "기판 1"),  # Korean names with the same digit: DS-1-…
]
ALIKE = [  # the same on a screen: AOI-TRN-055
    ("TBOX-A1", "TBOX-A１"),  # a full-width digit
    ("TBOX-A1", "ＴＢＯＸ-A1"),  # full-width letters
    ("보드 1", "\u1107\u1169\u1103\u1173 1"),  # 보드 decomposed, as a macOS file name gives it
    ("TBOX A1", "TBOX\u00a0A1"),  # a no-break space
    ("TBOX A1", "TBOX  A1"),  # two spaces
    ("TBOX-A1", "TBOX\u200b-A1"),  # a zero-width space
    ("TBOX-A1", "TBOX-A1\u00ad"),  # a soft hyphen
]
BETA = "Beta Boards"  # a customer with a dataset store already


def written(ctx: AppContext, keys: credentials.MemoryCredentials) -> tuple[Any, ...]:
    """What a call that makes a board model writes: the board models, the audit trail, the default recipes, the files
    under images/, models/ and datasets/, the dataset stores and the keys in the key store."""
    root = ctx.settings.root
    files = sorted(
        p.relative_to(root).as_posix() for d in ("images", "models", "datasets") for p in (root / d).rglob("*")
    )
    recipes = {b: ctx.recipe_history(b) for b in ctx.board_models()}
    return ctx.board_models(), ctx.audit_entries(), recipes, files, ctx.stores(), sorted(keys._secrets)


def _entry_points(ctx: AppContext, ok_image: str, held: int) -> dict[str, Callable[[str], object]]:
    """Each call that makes a board model of a name it is given: + New's two (no customer, and a customer's, new or
    with a store), a first import, and Set Reference, which writes the board model's row."""
    return {
        "ensure_board_model": ctx.ensure_board_model,
        "import_samples": lambda n: ctx.import_samples(n, [ok_image], "OK"),
        "set_reference": lambda n: ctx.set_reference(n, held),
        "create_customer_board_model, a new customer": lambda n: as_admin(
            ctx, ctx.create_customer_board_model, n, "Acme"
        ),
        "create_customer_board_model, a customer's store": lambda n: as_admin(
            ctx, ctx.create_customer_board_model, n, BETA
        ),
    }


def committed(field: QLineEdit, text: str) -> None:
    """`text` typed into `field` as a Korean input method gives it, composed and then committed; QTest types Latin-1
    keys only."""
    event = QInputMethodEvent()
    event.setCommitString(text)
    QApplication.sendEvent(field, event)


@pytest.mark.parametrize("name", SLIPPED)
def test_req_trn_005_a_name_freeze_refuses_is_refused_where_it_is_entered(
    ctx: AppContext, keys: credentials.MemoryCredentials, synthetic_dataset: Path, name: str
) -> None:
    """Each name that slipped through is one freeze refuses (AOI-TRN-039: no Latin letter or digit, `datasets.token`
    empty), and now every call that makes a board model refuses it first, with AOI-TRN-054 naming it, writing nothing:
    no board model, audit entry, recipe, file, store or key. Its message says what a valid name looks like."""
    assert datasets.token(name) == ""
    with pytest.raises(AoiError) as at_freeze:
        ctx.freeze_dataset(name, "Top", "R3", "Acme")
    assert at_freeze.value.code == "AOI-TRN-039"
    ok_image = str(list_images(synthetic_dataset / "train" / "ok")[0])
    ctx.import_samples("HELD", [ok_image], "OK")  # an OK sample Set Reference is given
    held = ctx.samples("HELD", "OK")[0]["id"]
    as_admin(ctx, ctx.create_store, BETA)
    before = written(ctx, keys)
    refusal = ctx.board_model_name_refusal(name)
    assert refusal is not None and (refusal.code, refusal.params) == ("AOI-TRN-054", {"name": name})
    assert refusal.message == (
        f'The board model name "{name}" has no Latin letter or digit (A to Z, 0 to 9, as an English keyboard types'
        " them), and a board model's dataset versions are named with those in its name. Give the board model a name"
        " with at least one Latin letter or digit, such as TBOX-A1; other letters, such as Korean ones, may be added to"
        ' it, as in "TBOX-A1 메인보드". Nothing was made.'
    )
    for call, make in _entry_points(ctx, ok_image, held).items():
        with pytest.raises(AoiError) as refused:
            make(name)
        assert (refused.value.code, refused.value.params) == ("AOI-TRN-054", {"name": name}), call
        assert written(ctx, keys) == before, call
    assert ctx.board_model_name_refusal(name) is not None and written(ctx, keys) == before  # asking writes nothing


def test_req_trn_005_a_name_with_a_latin_letter_or_digit_is_taken(ctx: AppContext, synthetic_dataset: Path) -> None:
    """A name with a Latin letter or digit, other letters and spaces beside them, is taken by + New and by a first
    import, and freeze takes its name too: it refuses such a board model for what it lacks (no label checked), never
    for its name (AOI-TRN-039)."""
    ok_image = str(list_images(synthetic_dataset / "train" / "ok")[0])
    for name in TAKEN:
        assert ctx.board_model_name_refusal(name) is None and datasets.token(name) != "", name
        ctx.ensure_board_model(name)
    ctx.import_samples("TBOX-B2 하부", [ok_image], "OK")
    assert sorted(ctx.board_models()) == sorted([*TAKEN, "TBOX-B2 하부"])
    assert {e["object_uuid"] for e in ctx.audit_entries(action="board_model.create")} >= set(TAKEN)
    for name in [*TAKEN, "TBOX-B2 하부"]:
        with pytest.raises(AoiError) as refused:
            ctx.freeze_dataset(name, "Top", "R3", "Acme")
        assert refused.value.code not in ("AOI-TRN-039", "AOI-TRN-040"), (name, refused.value)  # never its name


def test_req_trn_005_the_rules_for_a_new_name_keep_their_order(ctx: AppContext) -> None:
    """The folder rule first (AOI-TRN-019: an empty name, one ending with a dot, a device name), then the Latin letter
    or digit (AOI-TRN-054), then the case of an existing name (AOI-TRN-005), then how it looks (AOI-TRN-055), then its
    Latin letters and digits (AOI-TRN-056); a name that differs only in case from one with no Latin letter or digit is
    refused for its letters, and one that looks like an existing name is said to, not that its versions would mix."""
    ctx.ensure_board_model("TBOX-A1")
    ctx.db.ensure_board_model("Ωμέγα")  # made before names were checked
    for name, code in (("", "AOI-TRN-019"), ("...", "AOI-TRN-019"), ("보드.", "AOI-TRN-019"), ("CON", "AOI-TRN-019"),
                       ("ΩΜΈΓΑ", "AOI-TRN-054"), ("ＴＢＯＸ－Ａ１", "AOI-TRN-054"), ("tbox-a1", "AOI-TRN-005"),
                       ("tbox-a１", "AOI-TRN-055"), ("TBOX-A1\u200b", "AOI-TRN-055"),
                       ("TBOX A1", "AOI-TRN-056")):  # fmt: skip
        refusal = ctx.board_model_name_refusal(name)
        assert refusal is not None and refusal.code == code, (name, refusal)
        with pytest.raises(AoiError) as refused:
            ctx.ensure_board_model(name)
        assert refused.value.code == code, name


def test_req_trn_005_a_board_model_made_before_keeps_its_name(
    ctx: AppContext, keys: credentials.MemoryCredentials, synthetic_dataset: Path
) -> None:
    """A board model named in Korean only before this rule, as an older workspace holds it, is kept: + New with its
    name creates nothing and refuses nothing, and it imports, takes a reference and inspects as before; freeze refuses
    it with AOI-TRN-039, as it did, saying to import its images under a name with a Latin letter or digit."""
    oks = [str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:3]]
    ctx.db.ensure_board_model("보드")
    before = ctx.audit_entries()
    assert ctx.board_model_name_refusal("보드") is None
    ctx.ensure_board_model("보드")
    assert ctx.audit_entries() == before and ctx.board_models() == ["보드"]
    assert ctx.import_samples("보드", oks, "OK") == 3
    second = ctx.samples("보드", "OK")[1]
    ctx.set_reference("보드", second["id"])
    assert ctx.reference_image("보드") == second["path"]
    result = ctx.inspect_file("보드", oks[2])
    assert result.verdict in ("OK", "NG", "WARN") and ctx.inspections(board_model="보드")
    with pytest.raises(AoiError) as refused:
        ctx.freeze_dataset("보드", "Top", "R3", "Acme")
    assert (refused.value.code, refused.value.params["board"]) == ("AOI-TRN-039", "보드")
    assert "such as TBOX-A1" in refused.value.action and ctx.datasets("보드") == []


def test_req_trn_005_the_dialog_checks_the_name_as_it_is_typed(
    qtbot: QtBot, ctx: AppContext, dialogs: list[tuple[str, str]]
) -> None:
    """New board model: while the name typed is one a new board model may not have, Create is off, the line under the
    name gives its refusal (code, what happened, what to do), and Enter and Create make nothing, show no dialog and
    keep the form as typed; a name that is allowed clears the line and turns Create on, and Enter makes it once. A name
    that differs only in case from one that exists is said there too. Enter on an empty name leaves the form open (Qt
    had made Cancel the default button, so it closed it). A refusal the name alone does not give, such as a board model
    in no store named with a customer, still shows Create's dialog, and Enter there keeps the form. A board model made
    before under a name the rule refuses, typed exactly, is chosen as before, writing nothing."""
    ctx.ensure_board_model("TBOX-A1")
    ctx.ensure_board_model("PLAIN")
    ctx.db.ensure_board_model("옛보드")  # made before names were checked
    win = shell(qtbot, ctx)
    dialog = opened(qtbot, win)
    assert not dialog.btn_create.isEnabled() and not dialog.name_refusal.isVisible()
    before = ctx.board_models(), ctx.audit_entries()
    qtbot.keyClick(dialog.board, Qt.Key.Key_Return)
    assert dialog.isVisible() and dialog.result() == 0
    committed(dialog.board, "보드")
    assert dialog.board.text() == "보드" and not dialog.btn_create.isEnabled()
    assert dialog.name_refusal.isVisible() and dialog.name_refusal.text().startswith(
        'AOI-TRN-054 The board model name "보드" has no Latin letter or digit (A to Z, 0 to 9'
    )
    assert "such as TBOX-A1" in dialog.name_refusal.text()
    qtbot.keyClick(dialog.board, Qt.Key.Key_Return)
    dialog.make()  # as Create would, were it on
    assert (ctx.board_models(), ctx.audit_entries()) == before and dialogs == []
    assert dialog.isVisible() and dialog.made is None and dialog.board.text() == "보드"
    dialog.board.setText(" tbox-a1 ")  # spaces at its ends are dropped, as Create drops them
    assert not dialog.btn_create.isEnabled()
    assert dialog.name_refusal.text().startswith("AOI-TRN-005 Board model TBOX-A1 already exists, and tbox-a1 differs")
    dialog.board.setText("")
    assert not dialog.btn_create.isEnabled() and not dialog.name_refusal.isVisible()
    qtbot.keyClicks(dialog.board, "TBOX-A2 ")
    committed(dialog.board, "메인보드")
    assert dialog.btn_create.isEnabled() and not dialog.name_refusal.isVisible()
    qtbot.keyClick(dialog.board, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted and dialog.made == "TBOX-A2 메인보드" and dialogs == []
    made = [e["object_uuid"] for e in ctx.audit_entries(action="board_model.create")]
    assert made.count("TBOX-A2 메인보드") == 1 and "TBOX-A2 메인보드" in ctx.board_models()
    refused = opened(qtbot, win)
    refused.board.setText("PLAIN")
    refused.customer.setCurrentText(BETA)
    assert refused.btn_create.isEnabled() and not refused.name_refusal.isVisible()
    qtbot.keyClick(refused.board, Qt.Key.Key_Return)
    assert [d[0] for d in dialogs] == ["AOI-TRN-044 Dataset store not changed"]
    assert refused.isVisible() and refused.board.text() == "PLAIN" and refused.customer.currentText() == BETA
    kept = opened(qtbot, win)
    entries = ctx.audit_entries()
    kept.board.setText("옛보드")
    assert kept.btn_create.isEnabled() and not kept.name_refusal.isVisible()
    kept.btn_create.click()
    assert kept.result() == QDialog.DialogCode.Accepted and kept.made == "옛보드" and ctx.audit_entries() == entries


def test_req_trn_005_enter_in_customer_makes_the_store_and_stops_at_its_key(
    qtbot: QtBot, ctx: AppContext, monkeypatch: pytest.MonkeyPatch, dialogs: list[tuple[str, str]]
) -> None:
    """Enter in the Customer field creates as Create does, once, and goes no further: the key step is shown with its key
    and no file dialog opens, as one would were Save to File…, the key step's default button, pressed after it."""
    saves: list[object] = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a: saves.append(a) or ("", "")))
    dialog = opened(qtbot, shell(qtbot, ctx))
    dialog.board.setText("TBOX-A9")
    dialog.customer.setCurrentText("Acme")
    line = dialog.customer.lineEdit()
    assert line is not None
    line.setFocus()
    qtbot.keyClick(line, Qt.Key.Key_Return)
    assert dialog.steps.currentWidget() is dialog.key_step and dialog.recovery.key.text() != ""
    assert saves == [] and dialogs == [] and dialog.isVisible() and dialog.made == "TBOX-A9"
    assert [s["customer"] for s in ctx.stores()] == ["Acme"]


@pytest.mark.parametrize("name", [" 보드", "보드 ", "\u00a0보드", "보드\t"])
def test_req_trn_005_a_padded_name_is_refused_by_every_entry_point(
    ctx: AppContext, keys: credentials.MemoryCredentials, synthetic_dataset: Path, name: str
) -> None:
    """A Korean-only name with spaces at its ends, as a call that does not strip it gets it, is refused by every entry
    point too, writing nothing: for its letters (AOI-TRN-054) or, where its last character names no folder on Windows,
    for that (AOI-TRN-019); the customer's path strips it, as the dialog does, and says AOI-TRN-054."""
    ok_image = str(list_images(synthetic_dataset / "train" / "ok")[0])
    ctx.import_samples("HELD-1", [ok_image], "OK")
    held = ctx.samples("HELD-1", "OK")[0]["id"]
    as_admin(ctx, ctx.create_store, BETA)
    before = written(ctx, keys)
    for call, make in _entry_points(ctx, ok_image, held).items():
        with pytest.raises(AoiError) as refused:
            make(name)
        expected = {"AOI-TRN-054"} if call.startswith("create_customer") else {"AOI-TRN-054", "AOI-TRN-019"}
        assert refused.value.code in expected, (call, refused.value)
        assert written(ctx, keys) == before, call


@pytest.mark.parametrize(("existing", "name"), MIXED + ALIKE)
def test_req_trn_005_a_name_like_an_existing_one_is_refused_where_it_is_entered(
    ctx: AppContext, keys: credentials.MemoryCredentials, synthetic_dataset: Path, existing: str, name: str
) -> None:
    """A name whose Latin letters and digits are an existing board model's gives its versions that board model's names,
    which freeze refused only once that board model had a version (AOI-TRN-040), and one that looks the same as an
    existing name on a screen is told from it by no one; both were taken by + New and a first import. Now every call
    that makes a board model refuses each first, writing nothing: no board model, audit entry, recipe, file, store or
    key; with AOI-TRN-055 for a look-alike and AOI-TRN-056 for the rest, naming the existing board model, and for
    AOI-TRN-056 the DS-<BOARDMODEL> both would share."""
    ctx.ensure_board_model(existing)
    code = "AOI-TRN-055" if (existing, name) in ALIKE else "AOI-TRN-056"
    token = datasets.token(name)
    assert name != existing and name.casefold() != existing.casefold()
    assert (code == "AOI-TRN-055") == (looks(name) == looks(existing))
    assert code == "AOI-TRN-055" or token == datasets.token(existing) != ""
    ok_image = str(list_images(synthetic_dataset / "train" / "ok")[0])
    ctx.import_samples("HELD", [ok_image], "OK")
    held = ctx.samples("HELD", "OK")[0]["id"]
    as_admin(ctx, ctx.create_store, BETA)
    before = written(ctx, keys)
    params = {"name": name, "existing": existing} | ({"token": token} if code == "AOI-TRN-056" else {})
    refusal = ctx.board_model_name_refusal(name)
    assert refusal is not None and (refusal.code, refusal.params) == (code, params)
    for call, make in _entry_points(ctx, ok_image, held).items():
        with pytest.raises(AoiError) as refused:
            make(name)
        assert (refused.value.code, refused.value.params) == (code, params), call
        assert written(ctx, keys) == before, call


def test_req_trn_005_the_messages_say_what_to_type_instead(ctx: AppContext) -> None:
    """AOI-TRN-055 names the board model the name looks like and what can make two names look alike; AOI-TRN-056 the one
    whose versions it would share, and their DS-<BOARDMODEL>; each says to select that board model, or what a name
    that differs needs, and that nothing was made."""
    ctx.ensure_board_model("TBOX-A1")
    alike, mixed = ctx.board_model_name_refusal("TBOX-A１"), ctx.board_model_name_refusal("tbox a1")
    assert alike is not None and alike.message == (
        'The board model name "TBOX-A１" looks the same as board model "TBOX-A1", which exists already: they differ'
        " only in characters that look alike, such as full-width letters or digits, a space of another kind, or a"
        ' character that shows nothing. Select "TBOX-A1" in the top bar to work on that board model, or type a name'
        " that differs from it in its letters or digits, using an English keyboard for A to Z and 0 to 9. Nothing was"
        " made."
    )
    assert mixed is not None and mixed.message == (
        'The board model name "tbox a1" has the same Latin letters and digits as board model "TBOX-A1", so the dataset'
        ' versions of both would be named DS-TBOXA1-…, and their names would mix. Select "TBOX-A1" in the top bar if'
        " it is the same board, or give the new board model a name whose Latin letters or digits differ from those of"
        ' "TBOX-A1", such as one with another digit added. Nothing was made.'
    )


def test_req_trn_005_board_models_made_before_that_mix_keep_working(ctx: AppContext, synthetic_dataset: Path) -> None:
    """Board models made before this rule under names it now refuses beside each other (CAL-1 and CAL_1, or a name and
    its look-alike) are kept: + New with either name, typed exactly, creates nothing and refuses nothing, and each
    imports and takes a reference as before; freeze still refuses the second once the first has a version
    (AOI-TRN-040, tests/test_datasets.py)."""
    oks = [str(p) for p in list_images(synthetic_dataset / "train" / "ok")[:2]]
    made = ["CAL-1", "CAL_1", "TBOX A1", "TBOX\u00a0A1"]
    for name in made:
        ctx.db.ensure_board_model(name)
    before = ctx.audit_entries()
    for name in made:
        assert ctx.board_model_name_refusal(name) is None
        ctx.ensure_board_model(name)
    assert ctx.audit_entries() == before and sorted(ctx.board_models()) == sorted(made)
    for name in made:
        assert ctx.import_samples(name, oks, "OK") == 2
        ctx.set_reference(name, ctx.samples(name, "OK")[1]["id"])
        assert ctx.reference_image(name) == ctx.samples(name, "OK")[1]["path"]


def test_req_trn_005_the_dialog_says_a_name_looks_like_or_mixes_with_another(qtbot: QtBot, ctx: AppContext) -> None:
    """New board model: a name that looks like an existing one, or whose versions would take another's names, is said
    under the name as it is typed, with its code, and Create is off; a name that differs turns Create on."""
    ctx.ensure_board_model("TBOX-A1")
    dialog = opened(qtbot, shell(qtbot, ctx))
    committed(dialog.board, "TBOX-A１")
    assert not dialog.btn_create.isEnabled() and dialog.name_refusal.isVisible()
    assert dialog.name_refusal.text().startswith('AOI-TRN-055 The board model name "TBOX-A１" looks the same as')
    dialog.board.setText("TBOX_A1")
    assert not dialog.btn_create.isEnabled() and dialog.name_refusal.isVisible()
    assert dialog.name_refusal.text().startswith('AOI-TRN-056 The board model name "TBOX_A1" has the same Latin')
    assert "DS-TBOXA1-…" in dialog.name_refusal.text()
    dialog.board.setText("TBOX_A2")
    assert dialog.btn_create.isEnabled() and not dialog.name_refusal.isVisible()
