"""Shared fixtures (stage S05): a temporary workspace, an AppContext on it, the seeded synthetic dataset,
and a tiny model trained once per session.

The synthetic boards come from tools/make_synthetic_dataset.py with a fixed seed, so every machine gets the
same images. Results on them prove a code path works; they are never quoted as accuracy (Customers & Launch
standard, "Validation and accuracy claims").
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

# Qt pages render offscreen in tests (CI runners have no display). Set before any Qt import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QMessageBox, QWidget  # noqa: E402

from aoi.config import Settings  # noqa: E402
from aoi.core import anomaly  # noqa: E402
from aoi.core.imaging import list_images, load_image  # noqa: E402
from aoi.core.services import AppContext  # noqa: E402
from aoi.data.db import new_uuid  # noqa: E402
from aoi.ui.theme import QSS  # noqa: E402
from tools.make_synthetic_dataset import ng_type, write_dataset  # noqa: E402

DATASET_SEED = 7  # the generator's default seed, so the fixture matches `python tools/make_synthetic_dataset.py`
DATASET_OK, DATASET_NG = 30, 14
TINY_EPOCHS, TINY_IMAGE_SIZE = 6, 64  # seconds on a CPU; enough for tests of the training and model code paths
ZWSP = "\u200b"  # zero width space


def wrapped(name: str) -> str:
    """`name` as a page shows a file name that may wrap after each _ and - (`breakable` in aoi/ui/pages/base.py, #245),
    spelled out here, so that a test does not take its expected text from the code under test."""
    return "".join(c + ZWSP if c in "_-" else c for c in name)


def distinct_copies(src: Path, folder: Path, n: int) -> list[Path]:
    """`n` copies of the image `src` in `folder`, each with bytes of its own after the image's end, which decoders never
    read: one picture under n SHA-256s, so an import takes each rather than skipping it as already imported (Q31)."""
    folder.mkdir(parents=True, exist_ok=True)
    data, out = src.read_bytes(), [folder / f"{src.stem}_{i:03d}{src.suffix}" for i in range(n)]
    for i, p in enumerate(out):
        p.write_bytes(data + f"{folder.name}{i:06d}".encode())  # another folder's copies have other bytes
    return out


@pytest.fixture
def workspace(tmp_path: Path) -> Settings:
    """Settings on a fresh temporary workspace; nothing in the tests touches ~/AOI_Workspace."""
    return Settings(workspace=str(tmp_path / "workspace"), device="cpu")


def engineer(ctx: AppContext) -> AppContext:
    """Sign the context in as the seeded Engineer, so a test writes through it as an Engineer would; the role check
    itself is tested in tests/test_roles_and_audit.py."""
    ctx.set_user("engineer")
    return ctx


@pytest.fixture
def ctx(workspace: Settings) -> AppContext:
    """An AppContext on the temporary workspace: the layer the screens call, with an empty database."""
    return engineer(AppContext(workspace))


@pytest.fixture(scope="session")
def synthetic_dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The synthetic dataset (golden.png, train/ and test/ splits, labels.csv), written once per session."""
    out = tmp_path_factory.mktemp("synthetic")
    write_dataset(out, DATASET_OK, DATASET_NG, DATASET_SEED)
    return out


@dataclass(frozen=True)
class TrainedModel:
    """A tiny model trained once per session on the synthetic dataset.

    Read-only by convention: `ctx` here is shared by every test in the session, so tests that write to a
    workspace use the function-scoped `ctx` fixture instead.
    """

    ctx: AppContext
    board_model: str
    version: str
    model: anomaly.AnomalyModel
    reference: np.ndarray  # the golden board learned from the OK images, as the inspector uses it
    meta: dict[str, Any]


@pytest.fixture(scope="session")
def tiny_model(tmp_path_factory: pytest.TempPathFactory, synthetic_dataset: Path) -> TrainedModel:
    settings = Settings(workspace=str(tmp_path_factory.mktemp("model_workspace")), device="cpu")
    ctx = engineer(AppContext(settings))
    board_model = "TINY"
    ctx.import_samples(board_model, [str(p) for p in list_images(synthetic_dataset / "train" / "ok")], "OK")
    for p in list_images(synthetic_dataset / "train" / "ng"):  # one call each: an NG sample is imported with its type
        ctx.import_samples(board_model, [str(p)], "NG", ng_type(p))
    meta = ctx.train(board_model, epochs=TINY_EPOCHS, image_size=TINY_IMAGE_SIZE)
    loaded = ctx.load_model(board_model)
    assert loaded is not None, "training registered no active model"
    reference = ctx.db.reference(board_model)
    assert reference is not None, "training set no reference image"
    return TrainedModel(ctx, board_model, loaded[0], loaded[1], load_image(reference), meta)


def another_version(ctx: AppContext, board_model: str, version: str) -> int:
    """A second AI model version of `board_model`, registered but not active, and its id for `activate_model`: the
    active version's weights saved again under a UUID of their own, as training registers a version, so a test can
    activate another AI model without a training run, which would also set a new Golden board."""
    active = ctx.active_model(board_model)
    assert active is not None, "no AI model to copy"
    model, uid = anomaly.AnomalyModel.load(active["path"]), new_uuid()
    model.meta.update(version=version, uuid=uid)
    path = Path(active["path"]).with_name(f"{board_model}_{version}_copy.pt")
    model.save(path)
    return ctx.db.register_model(board_model, version, str(path), {}, activate=False, uid=uid)


@pytest.fixture
def trained_ctx(tmp_path: Path, tiny_model: TrainedModel) -> AppContext:
    """A writable copy of the tiny model's workspace: samples, golden board and the active model are registered,
    no inspection has run yet. Tests that inspect, save recipes or log results use this one."""
    ws = tmp_path / "trained_workspace"
    shutil.copytree(tiny_model.ctx.settings.root, ws)
    return engineer(AppContext(Settings(workspace=str(ws), device="cpu")))


@pytest.fixture(autouse=True)
def _settings_file_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """settings.json is read and written in the default workspace (Settings.load and save, REQ-LOG-005); point
    it at a folder of this test so that no test touches ~/AOI_Workspace."""
    monkeypatch.setenv("AOI_WORKSPACE", str(tmp_path / "default_workspace"))


@pytest.fixture(autouse=True)
def dialogs(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, str]]]:
    """Error dialogs shown during a test, as (title, text), in place of a modal box that would block offscreen.
    At the end every title must start with an error code: no error reaches a user without one (REQ-SET-019)."""
    shown: list[tuple[str, str]] = []

    def record(parent: object, title: str, text: str, *buttons: object) -> QMessageBox.StandardButton:
        shown.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(record))
    yield shown
    assert all(title.startswith("AOI-") for title, _ in shown), f"an error dialog without a code: {shown}"


@pytest.fixture(autouse=True)
def _questions_answer_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Yes in place of a modal question that would block offscreen: a window closed at a test's end while work runs
    asks whether to stop it (#171). A test that answers otherwise patches QMessageBox.question itself."""
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *_: QMessageBox.StandardButton.Yes))


def let_go_of_keys() -> None:
    """Qt reads no key as held after this. QTest's click with Ctrl lets go of Ctrl in an event that still carries Ctrl,
    so Qt reads Ctrl as held until the next key event."""
    if QGuiApplication.keyboardModifiers() != Qt.KeyboardModifier.NoModifier:
        QTest.keyRelease(QWidget(), Qt.Key.Key_Control)  # an event with no modifier: Qt reads none held after it


@pytest.fixture(autouse=True)
def _no_key_held(qapp: Any) -> None:
    """Each test starts with no key held: with Ctrl read as held from an earlier test, a test's selectRow() adds its
    row to the selection instead of selecting it alone (the AI Model Test preview test's another_row failed so on
    Linux CI, after the import sheet's Ctrl+N)."""
    let_go_of_keys()


@pytest.fixture
def ng_board(synthetic_dataset: Path) -> Path:
    """A test-split board with a missing component: the largest defect, found by the compare step alone."""
    return next(synthetic_dataset.glob("test/ng/*missing_component*.png"))


@pytest.fixture(scope="session", autouse=True)
def _theme(qapp: Any) -> None:
    """The shell's stylesheet, as main.py applies it, so page tests see the app's fonts and sizes (REQ-SET-004)."""
    qapp.setStyleSheet(QSS)
