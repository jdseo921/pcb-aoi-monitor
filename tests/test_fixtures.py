"""The shared fixtures in conftest.py do what they say (stage S05)."""

from __future__ import annotations

from pathlib import Path

from aoi.config import Settings
from aoi.core.imaging import list_images
from aoi.core.inspector import Inspector
from aoi.core.recipe import Recipe
from aoi.core.services import AppContext
from tests.conftest import TrainedModel


def test_workspace_fixture_is_temporary_and_empty(workspace: Settings, ctx: AppContext, tmp_path: Path) -> None:
    assert Path(workspace.workspace).is_relative_to(tmp_path)
    assert ctx.settings.db_path.exists()
    assert ctx.db.board_models() == []


def test_synthetic_dataset_fixture_has_the_seeded_splits(synthetic_dataset: Path) -> None:
    assert (synthetic_dataset / "golden.png").exists()
    assert len(list_images(synthetic_dataset / "train" / "ok")) == 20  # 30 OK boards: 10 held out for test/
    assert len(list_images(synthetic_dataset / "train" / "ng")) == 3  # 14 NG boards: 3 for calibration
    assert len(list_images(synthetic_dataset / "test")) == 21


def test_tiny_model_fixture_scores_its_own_golden_board_as_normal(tiny_model: TrainedModel) -> None:
    assert tiny_model.model.image_threshold > 0
    assert tiny_model.ctx.db.active_model(tiny_model.board_model)["version"] == tiny_model.version
    recipe = Recipe(board_model=tiny_model.board_model, use_compare=False)
    res = Inspector(recipe, tiny_model.model, tiny_model.reference).inspect(tiny_model.reference)
    ai = next(c for c in res.checks if c.source == "AI")
    assert ai.value < ai.threshold, "the golden board the model learned from must not score as an anomaly"
