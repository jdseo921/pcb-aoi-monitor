"""The bytes `AppContext.log_result` writes per 5 MP board, judged OK and judged NG (D1, REQ-INSP-012):

    python tools/evidence_bytes.py

8 synthetic test boards, every board of the dataset scaled to 2592 x 1944 as the 2026-11 diagnosis measured them, on
a workspace trained with the shipped AI input of 256 px (3 epochs: the map sizes do not depend on how well it learned).
Each board is saved twice, judged OK and judged NG, so the two differ only by what the evidence policy keeps. Drawings
compress better than a camera's photographs: these are synthetic figures, never a station's.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aoi.config import Settings  # noqa: E402
from aoi.core.imaging import list_images, load_image, save_image  # noqa: E402
from aoi.core.services import AppContext  # noqa: E402
from aoi.data import credentials  # noqa: E402
from tools.make_synthetic_dataset import ng_type, write_dataset  # noqa: E402
from tools.trainable import trainable  # noqa: E402


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="evidence-bytes-"))
    write_dataset(tmp / "data", 40, 16, 7)
    for f in list_images(tmp / "data"):  # the training set too, so the Golden board is 5 MP
        save_image(f, cv2.resize(load_image(str(f)), (2592, 1944), interpolation=cv2.INTER_LINEAR))
    ctx = AppContext(Settings(workspace=str(tmp / "ws"), device="cpu"), credentials.MemoryCredentials())
    ctx.set_user("engineer")
    ctx.import_samples("B", [str(p) for p in list_images(tmp / "data" / "train" / "ok")], "OK")
    for p in list_images(tmp / "data" / "train" / "ng"):
        ctx.import_samples("B", [str(p)], "NG", ng_type(p))
    ctx.train(trainable(ctx, "B"), epochs=3, image_size=256)
    insp, sizes = ctx.inspector("B"), {"OK": [], "NG": []}
    boards = list_images(tmp / "data" / "test" / "ok")[:4] + list_images(tmp / "data" / "test" / "ng")[:4]
    for board in boards:
        res = insp.inspect(ctx.load_image(str(board)))
        for verdict, files in sizes.items():
            judged = copy.deepcopy(res)
            judged.verdict = verdict
            before = set(ctx.settings.results_dir.rglob("*"))
            ctx.log_result("B", str(board), judged, insp)
            new = [f for f in ctx.settings.results_dir.rglob("*") if f.is_file() and f not in before]
            files.append({f.name.rsplit("_", 1)[-1]: f.stat().st_size for f in new})
    ctx.close()
    out = {
        verdict: {kind: round(sum(r.get(kind, 0) for r in rows) / len(rows) / 1e6, 3) for kind in rows[0]}
        | {"total": round(sum(sum(r.values()) for r in rows) / len(rows) / 1e6, 2)}
        for verdict, rows in sizes.items()
    }
    print(json.dumps(out, indent=1))  # MB per board, by file: the overlay (`OK.jpg`, `NG.png`), `prev.jpg`, the maps
    return 0


if __name__ == "__main__":
    sys.exit(main())
