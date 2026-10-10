"""Build the demo bundle the app loads in one click (REQ-SET-007; S53; Customers & Launch, "Demos").

    python tools/make_demo_bundle.py [--out demo-bundle]

The build runs this before PyInstaller, which ships the folder with the app (aoi/core/demo.py says what it holds). It
makes a workspace the way an engineer would: the board model DEMO-TBOX-A1 with the synthetic boards of
tools/make_synthetic_dataset.py as its OK and NG samples, in a dataset store of their own (ADR 0010), an AI model
trained on them and activated, with its model card and Golden board; then the ten boards a scripted run plays, nine OK
and the fourth NG (a missing component), inspected once with that model before they are bundled. The build fails,
writing no bundle, unless they get those verdicts with a margin: an OK board's AI score at most MARGIN of the
threshold, so the same verdicts come back on any PC, whose CPU rounds a little differently.

The boards are drawn, never photographed: what the demo shows is how the app works, never how well it finds defects
(Customers & Launch, "Validation"), and its model card says so.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a script: the repository root holds the ``aoi`` and ``tools`` packages
    sys.path.insert(0, str(ROOT))

from aoi.config import APP_VERSION, Settings  # noqa: E402
from aoi.core import demo  # noqa: E402
from aoi.core.imaging import list_images  # noqa: E402
from aoi.core.services import AppContext  # noqa: E402
from aoi.data import credentials  # noqa: E402
from aoi.times import now_utc  # noqa: E402
from tools.make_synthetic_dataset import ng_type, write_dataset  # noqa: E402
from tools.trainable import key_of, trainable  # noqa: E402

BOARD_MODEL = "DEMO-TBOX-A1"
CUSTOMER = "Demo (synthetic boards)"  # the store's customer: our own synthetic boards (ADR 0010)
OK, NG, SEED = 60, 14, 7  # the generator's defaults: 40 OK boards train, 20 are held out
EPOCHS, IMAGE_SIZE = 20, 128
FAILING = "ng_007_missing_component.png"  # a held-out NG board: a part is missing from its pads, as Compare shows
FAIL_AT = 4  # the failing board's place in the run: the run is under way, and it stops early enough to explain
BOARDS = 10
MARGIN = 0.6  # an OK board's AI score over its threshold at most this (WARN starts at 0.8 by default)


def build(out: Path, epochs: int = EPOCHS, image_size: int = IMAGE_SIZE) -> dict[str, Any]:
    """Write the bundle into `out`, replacing a bundle there, and return its manifest. SystemExit when `out` holds
    files and no bundle, or when the boards do not get the verdicts the demo needs."""
    if out.exists() and any(out.iterdir()) and not (out / demo.BUNDLE_FILE).is_file():
        raise SystemExit(f"{out} holds files and is not a demo bundle; choose another --out")
    shutil.rmtree(out, ignore_errors=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, AOI_WORKSPACE=str(Path(tmp) / "settings")):
        dataset = Path(tmp) / "dataset"
        write_dataset(dataset, OK, NG, SEED)
        keys = credentials.MemoryCredentials()  # the store key goes to store-key.json, never to the station
        ctx = AppContext(Settings(workspace=str(out / demo.WORKSPACE), device="cpu"), keys)
        try:
            ctx.set_user("engineer")
            ctx.import_samples(BOARD_MODEL, [str(p) for p in list_images(dataset / "train" / "ok")], "OK")
            for p in list_images(dataset / "train" / "ng"):  # one call each: an NG sample is imported with its type
                ctx.import_samples(BOARD_MODEL, [str(p)], "NG", ng_type(p))
            version = trainable(ctx, BOARD_MODEL, customer=CUSTOMER)
            meta = ctx.train(version, epochs=epochs, image_size=image_size)
            ctx.activate_model(int(ctx.models(BOARD_MODEL)[0]["id"]))  # a version installs inactive (REQ-TRN-010)
            store = ctx.db.board_model_store(BOARD_MODEL) or {}
            key = {"store_uuid": store["uuid"], "key": key_of(ctx, store["uuid"]).hex()}
            boards = _boards(ctx, dataset, out / demo.WORKSPACE / demo.BOARDS)
        finally:
            ctx.close()
    for name in demo.BUILD_ONLY:  # the log and the lock of the build's own session
        p = out / demo.WORKSPACE / name
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    (out / demo.KEY_FILE).write_text(json.dumps(key, indent=2), encoding="utf-8")
    manifest = {
        "format": demo.FORMAT,
        "built_at": now_utc(),
        "app_version": APP_VERSION,
        "board_model": BOARD_MODEL,
        "ai_model": {"epochs": epochs, "image_size": image_size, "version": meta.get("version")},
        "boards": boards,
        "files": demo.file_hashes(out),
    }
    (out / demo.BUNDLE_FILE).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"Built {out} in {time.monotonic() - started:.0f} s: {len(manifest['files'])} files")
    return manifest


def _boards(ctx: AppContext, dataset: Path, folder: Path) -> list[dict[str, Any]]:
    """Copy the boards a scripted run plays into `folder` and return them in run order with the verdict and AI score
    each gets: the held-out OK boards that score lowest, and FAILING at FAIL_AT. SystemExit unless they get the
    verdicts the demo needs."""
    insp = ctx.inspector(BOARD_MODEL)
    scored = []
    for p in list_images(dataset / "test" / "ok"):
        res = insp.inspect(ctx.load_image(p))
        scored.append((res.score, p, res.verdict))
    scored.sort()
    picked = [(p, v, s) for s, p, v in scored[: BOARDS - 1]]
    failing = dataset / "test" / "ng" / FAILING
    res = insp.inspect(ctx.load_image(failing))
    picked.insert(FAIL_AT - 1, (failing, res.verdict, res.score))
    wrong = [p.name for i, (p, v, s) in enumerate(picked, 1) if v != ("NG" if i == FAIL_AT else "OK")]
    wrong += [p.name for i, (p, _, s) in enumerate(picked, 1) if i != FAIL_AT and s > MARGIN]
    if insp.model is None or wrong:  # the score is the AI score over its threshold
        raise SystemExit(f"The demo boards do not get the verdicts the demo needs: {wrong}; "
                         f"scores {[round(s, 3) for _, _, s in picked]}")  # fmt: skip
    folder.mkdir(parents=True)
    boards = []
    for i, (p, verdict, score) in enumerate(picked, 1):
        name = f"board_{i:02d}.png"
        shutil.copyfile(p, folder / name)
        boards.append({"file": f"{demo.BOARDS}/{name}", "from": p.name, "verdict": verdict, "score": round(score, 4)})
    return boards


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the demo bundle the app loads in one click (REQ-SET-007).")
    ap.add_argument("--out", type=Path, default=ROOT / "demo-bundle")
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    ap.add_argument("--image-size", type=int, default=IMAGE_SIZE)
    a = ap.parse_args(argv)
    manifest = build(a.out, a.epochs, a.image_size)
    for b in manifest["boards"]:
        print(f"{b['file']}  {b['verdict']}  score {b['score']}  ({b['from']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
