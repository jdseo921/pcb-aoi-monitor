"""Headless end-to-end check: synthetic data -> self-train -> batch test.

pytest -q tests
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aoi.config import Settings  # noqa: E402
from aoi.core.imaging import list_images  # noqa: E402
from aoi.core.services import AppContext  # noqa: E402


def test_train_and_detect(tmp_path):
    data = tmp_path / "data"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "make_synthetic_dataset.py"),
            "--out",
            str(data),
            "--ok",
            "30",
            "--ng",
            "14",
        ],
        check=True,
    )
    ctx = AppContext(Settings(workspace=str(tmp_path / "ws")))
    ctx.import_samples("TEST", [str(p) for p in list_images(data / "train" / "ok")], "OK")
    ctx.import_samples("TEST", [str(p) for p in list_images(data / "train" / "ng")], "NG")
    meta = ctx.train("TEST", epochs=15, image_size=128)
    assert meta["image_threshold"] > 0
    assert Path(ctx.db.active_model("TEST")["path"]).exists()

    metrics, rows = ctx.batch_test("TEST", str(data / "test"))
    assert metrics["labelled"] == len(rows) > 0
    assert metrics["recall"] >= 0.8  # defects must be caught
    assert metrics["false_call_rate"] <= 0.5  # loose bound: tiny CPU training run

    res = ctx.inspect_file("TEST", rows[0]["image"])
    assert {c.source for c in res.checks} >= {"AI", "Compare"}
    assert res.elapsed_ms < 5000
