"""REQ-TRN-014: AI model files load as weights only, and a file that needs code to load is refused.

Engineering standard, "Untrusted inputs": PyTorch files can run code when loaded, so the app loads
with ``torch.load(weights_only=True)`` and its own files hold only tensors and plain Python values.
"""

from __future__ import annotations

import math
import random
import re
import struct
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

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
    # The control: the same file loaded the unsafe way, in a process of its own, does run its code.
    unsafe = f"import torch; torch.load({str(crafted)!r}, weights_only={not True})"
    subprocess.run([sys.executable, "-c", unsafe], check=False, capture_output=True, timeout=120)
    assert marker.exists(), "the payload is live, so the refusal above is what kept it from running"


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


def _refused(path: Path) -> str:
    """The reason AI model file `path` is refused, from its AOI-TRN-001 error, which names the file."""
    with pytest.raises(anomaly.ModelFileError) as refused:
        anomaly.AnomalyModel.load(path)
    assert refused.value.code == "AOI-TRN-001" and str(path) in str(refused.value), refused.value
    return str(refused.value)


def test_req_trn_014_damaged_model_files_are_refused_with_a_code(tmp_path: Path) -> None:
    """A model file cut short, changed in place on disk, gone, a folder, or holding another network or numbers the
    model cannot judge with is refused with AOI-TRN-001 naming it, never a raw error or a model with wrong weights."""
    model = _tiny_model()
    good = tmp_path / "model.pt"
    model.save(good)
    data = good.read_bytes()
    for n in (0, 1000, 5000, 20000, len(data) // 2, len(data) - 10):
        cut = tmp_path / f"cut-{n}.pt"
        cut.write_bytes(data[:n])
        _refused(cut)
    with zipfile.ZipFile(good) as z:  # the largest tensor's bytes: the weights of one layer
        entry = max((e for e in z.infolist() if "/data/" in e.filename), key=lambda e: e.file_size)
    names, extra = struct.unpack("<HH", data[entry.header_offset + 26 : entry.header_offset + 30])
    start = entry.header_offset + 30 + names + extra
    rng = random.Random(7)
    for i in range(5):  # the lowest bit of one to five weights: still finite numbers, which used to load and judge
        flipped = bytearray(data)
        for _ in range(i + 1):
            flipped[start + 4 * rng.randrange(entry.file_size // 4)] ^= 1
        changed = tmp_path / f"changed-{i}.pt"
        changed.write_bytes(bytes(flipped))
        assert "damaged" in _refused(changed)
    assert "No such file" in _refused(tmp_path / "gone.pt")
    _refused(tmp_path)  # a folder

    def saved(name: str, state_dict: Any = None, **meta: Any) -> Path:
        path = tmp_path / f"{name}.pt"
        weights = model.net.state_dict() if state_dict is None else state_dict
        torch.save({"state_dict": weights, "meta": {**anomaly._to_safe(model.meta), **meta}}, path)
        return path

    assert "do not fit" in _refused(saved("other-network", {"conv.weight": torch.zeros(3)}))
    assert "no state_dict" in _refused(saved("weights-not-a-dict", [1, 2]))
    weights = model.net.state_dict()
    nan_weights = {k: torch.full_like(v, math.nan) if v.is_floating_point() else v for k, v in weights.items()}
    assert "not finite" in _refused(saved("nan-weights", nan_weights))
    assert "input size" in _refused(saved("size-50", image_size=50))
    assert "input size" in _refused(saved("size-missing", image_size=None))
    for bad in (0, -1.5, math.nan, math.inf, "1.5", True, None):
        assert "image threshold" in _refused(saved("threshold", image_threshold=bad)), bad
    assert "pixel threshold" in _refused(saved("pixel-threshold", pixel_threshold=0))
    assert "err_mean" in _refused(saved("map-shape", err_mean=torch.zeros(8, 8)))
    assert "err_std" in _refused(saved("std-missing", err_std=None))
    assert "spread" in _refused(saved("std-zero", err_std=torch.zeros(64, 64)))
    assert anomaly.AnomalyModel.load(saved("unchanged")).image_threshold == 1.5, "the control loads"
