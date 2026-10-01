"""REQ-TRN-014: AI model files load as weights only, and a file that needs code to load is refused.

Engineering standard, "Untrusted inputs": PyTorch files can run code when loaded, so the app loads
with ``torch.load(weights_only=True)`` and its own files hold only tensors and plain Python values.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
import torch

from aoi.core import anomaly


class _RunsCodeWhenUnpickled:
    """Unpickling this object would call ``open(marker, "w")`` and create the marker file."""

    def __init__(self, marker: str) -> None:
        self.marker = marker

    def __reduce__(self) -> tuple[object, ...]:
        return (open, (self.marker, "w"))


def _tiny_model(seed: int = 3, size: int = 64) -> anomaly.AnomalyModel:
    torch.manual_seed(seed)
    net = anomaly.ConvAutoencoder()
    rng = np.random.default_rng(seed)
    meta = {
        "image_size": size,
        "image_threshold": 1.5,
        "pixel_threshold": 0.8,
        "err_mean": rng.random((size, size), dtype=np.float32) * 0.01,
        "err_std": rng.random((size, size), dtype=np.float32) * 0.01 + 0.005,
        "threshold_rule": "test",
        "ok_scores": [0.5, 0.7],
        "ng_scores": [],
        "n_ok_train": np.int64(2),  # NumPy scalars must become plain values
        "loss_history": [0.3, 0.2],
    }
    return anomaly.AnomalyModel(net, meta)


def _board(seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, size=(120, 160, 3), dtype=np.uint8)


def test_req_trn_014_crafted_pickle_is_refused(tmp_path: Path) -> None:
    marker = tmp_path / "code-ran.txt"
    crafted = tmp_path / "crafted.pt"
    torch.save({"state_dict": {}, "meta": {"evil": _RunsCodeWhenUnpickled(str(marker))}}, crafted)

    with pytest.raises(anomaly.ModelFileError, match="refused") as refused:
        anomaly.AnomalyModel.load(crafted)

    assert not marker.exists(), "the crafted file's code ran"
    assert refused.value.code == "AOI-TRN-001" and "Train the board model again" in refused.value.action


def test_req_trn_014_non_model_file_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "not-a-model.pt"
    bad.write_bytes(b"\x89PNG not a torch file")
    with pytest.raises(anomaly.ModelFileError, match=re.escape(str(bad))):
        anomaly.AnomalyModel.load(bad)

    wrong_shape = tmp_path / "wrong-shape.pt"
    torch.save({"weights": torch.zeros(1)}, wrong_shape)
    with pytest.raises(anomaly.ModelFileError, match="state_dict"):
        anomaly.AnomalyModel.load(wrong_shape)


def test_req_trn_014_round_trip(tmp_path: Path) -> None:
    model = _tiny_model()
    path = tmp_path / "model.pt"
    model.save(path)

    # The file loads under the strict unpickler on its own, with no allow-list.
    raw = torch.load(path, map_location="cpu", weights_only=True)
    assert set(raw) == {"state_dict", "meta"}
    assert isinstance(raw["meta"]["err_mean"], torch.Tensor)
    assert isinstance(raw["meta"]["n_ok_train"], int)

    loaded = anomaly.AnomalyModel.load(path)
    assert isinstance(loaded.meta["err_mean"], np.ndarray)
    assert loaded.meta["err_mean"].dtype == np.float32
    board = _board()
    expected = model.anomaly_map(board)
    actual = loaded.anomaly_map(board)
    assert np.array_equal(expected, actual)
    assert model.score(expected) == loaded.score(actual)
    assert loaded.image_threshold == 1.5 and loaded.size == 64


def test_req_trn_014_unsafe_metadata_is_not_written(tmp_path: Path) -> None:
    model = _tiny_model()
    model.meta["callback"] = lambda x: x
    with pytest.raises(TypeError, match="weights-only"):
        model.save(tmp_path / "model.pt")
