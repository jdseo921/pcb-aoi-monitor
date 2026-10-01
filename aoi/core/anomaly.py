"""Self-training anomaly model (PyTorch).

Why this approach for Stage 1: a customer usually has many good (OK) boards and
only a handful of defective ones, and most defect types in the classification
table will not have examples yet. A convolutional autoencoder learns what a
*good* board of one model looks like from uploaded OK images alone; anything it
cannot reconstruct (missing parts, bridges, contamination, shifts) shows up as
high reconstruction error. Labelled NG uploads, when present, are used to
calibrate the decision threshold, not required for training.

Saved as a .pt file (spec Stage 1 deliverable) containing weights plus the
calibration metadata needed to score new images. The file holds only tensors and
plain Python values, so it loads with ``torch.load(weights_only=True)`` and a file
that would need code to unpickle is refused (Engineering standard, "Untrusted
inputs"; REQ-TRN-014).
"""

from __future__ import annotations

import pickle
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from torch import nn

from ..data import atomic


class ModelFileError(ValueError):
    """An AI model file was refused: not a weights-only model file this app wrote."""


# Metadata arrays that travel in the file as tensors and are used as NumPy arrays in memory.
_ARRAY_META_KEYS = ("err_mean", "err_std")


def _to_safe(value: Any) -> Any:
    """Convert metadata to what the weights-only unpickler accepts: tensors and plain Python values."""
    if isinstance(value, torch.Tensor):
        return value
    if isinstance(value, np.ndarray):
        return torch.from_numpy(np.ascontiguousarray(value))
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _to_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Model metadata of type {type(value).__name__} cannot be stored in a weights-only file")


def _from_safe(meta: dict[str, Any]) -> dict[str, Any]:
    out = dict(meta)
    for key in _ARRAY_META_KEYS:
        if isinstance(out.get(key), torch.Tensor):
            out[key] = out[key].cpu().numpy()
    return out


class ConvAutoencoder(nn.Module):
    def __init__(self, ch: int = 32, latent: int = 128):
        super().__init__()

        def down(i: int, o: int) -> nn.Sequential:
            return nn.Sequential(nn.Conv2d(i, o, 4, 2, 1), nn.BatchNorm2d(o), nn.LeakyReLU(0.2, True))

        def up(i: int, o: int) -> nn.Sequential:
            return nn.Sequential(nn.ConvTranspose2d(i, o, 4, 2, 1), nn.BatchNorm2d(o), nn.ReLU(True))

        self.encoder = nn.Sequential(down(3, ch), down(ch, ch * 2), down(ch * 2, ch * 4), down(ch * 4, latent))
        self.decoder = nn.Sequential(
            up(latent, ch * 4), up(ch * 4, ch * 2), up(ch * 2, ch), nn.ConvTranspose2d(ch, 3, 4, 2, 1), nn.Sigmoid()
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.decoder(self.encoder(x))
        return out


def to_tensor(img_bgr: np.ndarray, size: int) -> torch.Tensor:
    rgb = cv2.cvtColor(cv2.resize(img_bgr, (size, size), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    return torch.from_numpy(rgb).permute(2, 0, 1).float() / 255.0


def augment(t: torch.Tensor) -> torch.Tensor:
    """Lighting jitter only: geometry must stay fixed so the model learns layout."""
    gain = 1.0 + random.uniform(-0.08, 0.08)
    bias = random.uniform(-0.04, 0.04)
    return (t * gain + bias).clamp(0, 1)


@dataclass
class TrainConfig:
    image_size: int = 256
    epochs: int = 60
    batch_size: int = 8
    lr: float = 2e-3
    steps_per_epoch: int = 8
    val_fraction: float = 0.25
    device: str = "cpu"
    seed: int = 0


ProgressFn = Callable[[int, int, float, str], None]  # epoch, total, loss, message


class AnomalyModel:
    """Wraps the network with its calibration so callers only see scores."""

    def __init__(self, net: ConvAutoencoder, meta: dict[str, Any], device: str = "cpu"):
        self.net = net.to(device).eval()
        self.meta = meta
        self.device = device

    @property
    def size(self) -> int:
        return int(self.meta["image_size"])

    @property
    def image_threshold(self) -> float:
        return float(self.meta["image_threshold"])

    @property
    def pixel_threshold(self) -> float:
        return float(self.meta["pixel_threshold"])

    @torch.no_grad()
    def raw_error(self, img_bgr: np.ndarray) -> np.ndarray:
        """Reconstruction error at network resolution."""
        x = to_tensor(img_bgr, self.size).unsqueeze(0).to(self.device)
        rec = self.net(x)
        err = (x - rec).abs().mean(dim=1)[0].cpu().numpy()
        blurred: np.ndarray = cv2.GaussianBlur(err, (0, 0), sigmaX=1.5)
        return blurred

    def anomaly_map(self, img_bgr: np.ndarray) -> np.ndarray:
        """Per-pixel anomaly at the input image's resolution.

        Reconstruction error is normalised by how much error each pixel shows on
        good boards (component edges, text and connectors are always a little
        off), so the map reads as "standard deviations above normal".
        """
        err = self.raw_error(img_bgr)
        m = max(2, self.size // 64)  # warped borders are never meaningful
        err[:m, :] = err[-m:, :] = 0
        err[:, :m] = err[:, -m:] = 0
        mu, sd = self.meta.get("err_mean"), self.meta.get("err_std")
        if mu is not None:
            err = np.clip((err - mu) / sd, 0, None)
            err = cv2.GaussianBlur(err, (0, 0), sigmaX=1.5)
        return cv2.resize(err, (img_bgr.shape[1], img_bgr.shape[0]), interpolation=cv2.INTER_LINEAR)

    def score(self, amap: np.ndarray) -> float:
        # 99.9th percentile is robust to single hot pixels but catches small defects.
        return float(np.percentile(amap, 99.9))

    def save(self, path: Path) -> None:
        payload = {"state_dict": self.net.state_dict(), "meta": _to_safe(self.meta)}
        atomic.write_with(path, lambda f: torch.save(payload, f))

    @classmethod
    def load(cls, path: str | Path, device: str = "cpu") -> AnomalyModel:
        """Load a model file as weights only; any file that needs code to unpickle is refused."""
        try:
            ckpt = torch.load(path, map_location=device, weights_only=True)
        except (pickle.UnpicklingError, RuntimeError, ValueError, EOFError) as e:
            raise ModelFileError(
                f"AI model file refused: {path} is not a weights-only model file this app wrote ({type(e).__name__})."
            ) from e
        if not isinstance(ckpt, dict) or not isinstance(ckpt.get("meta"), dict) or "state_dict" not in ckpt:
            raise ModelFileError(f"AI model file refused: {path} does not hold a state_dict and metadata.")
        net = ConvAutoencoder()
        net.load_state_dict(ckpt["state_dict"])
        return cls(net, _from_safe(ckpt["meta"]), device)


def calibrate(ok_scores: list[float], ng_scores: list[float]) -> tuple[float, str]:
    """Pick the image-level threshold from validation scores."""
    ok = np.array(ok_scores, dtype=np.float64)
    stat = float(ok.mean() + 3 * ok.std()) if len(ok) > 1 else float(ok.max() * 1.25)
    base = max(stat, float(ok.max()) * 1.05)
    if not ng_scores:
        return base, "OK-only: max(mean+3σ, 1.05×max OK)"
    ng = np.array(ng_scores, dtype=np.float64)
    if ng.min() > ok.max():
        return float((ok.max() + ng.min()) / 2), "separable: midpoint of max OK and min NG"
    # Overlap: keep the OK-based cut so good boards are not flagged; the golden-sample
    # comparison is the second line of defence for the NG samples that fall below it.
    missed = int((ng < base).sum())
    return base, f"overlap: OK-based cut, {missed}/{len(ng)} labelled NG below it"


def train(
    ok_images: list[np.ndarray],
    ng_images: list[np.ndarray],
    cfg: TrainConfig,
    progress: ProgressFn | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> AnomalyModel:
    if len(ok_images) < 2:
        raise ValueError("Need at least 2 OK images to train.")
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    say = progress or (lambda *a: None)

    tensors = [to_tensor(im, cfg.image_size) for im in ok_images]
    idx = list(range(len(tensors)))
    random.shuffle(idx)
    n_val = max(1, int(round(len(idx) * cfg.val_fraction))) if len(idx) >= 5 else 0
    val_idx, train_idx = idx[:n_val], idx[n_val:]
    train_set = [tensors[i] for i in train_idx]

    net = ConvAutoencoder().to(cfg.device)
    opt = torch.optim.Adam(net.parameters(), lr=cfg.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=cfg.epochs)
    l1 = nn.L1Loss()
    t0 = time.time()
    say(
        0,
        cfg.epochs,
        0.0,
        f"Training on {len(train_set)} OK images "
        f"({n_val} held out, {len(ng_images)} NG for calibration) on {cfg.device}",
    )
    loss_hist = []
    for ep in range(1, cfg.epochs + 1):
        net.train()
        running = 0.0
        for _ in range(cfg.steps_per_epoch):
            batch = torch.stack([augment(random.choice(train_set)) for _ in range(cfg.batch_size)]).to(cfg.device)
            rec = net(batch)
            loss = l1(rec, batch) + 0.5 * ((rec - batch) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            running += loss.item()
        sched.step()
        loss_hist.append(running / cfg.steps_per_epoch)
        say(ep, cfg.epochs, loss_hist[-1], "")
        if should_stop and should_stop():
            say(ep, cfg.epochs, loss_hist[-1], "Stopped by user; calibrating current weights")
            break

    model = AnomalyModel(
        net, {"image_size": cfg.image_size, "image_threshold": 1.0, "pixel_threshold": 1.0}, cfg.device
    )
    # Per-pixel error statistics of good boards (the learned "normal variation").
    errs = np.stack([model.raw_error(ok_images[i]) for i in train_idx])
    sd = errs.std(axis=0)
    model.meta["err_mean"] = errs.mean(axis=0).astype(np.float32)
    model.meta["err_std"] = np.maximum(sd, max(float(np.median(sd)), 1e-3)).astype(np.float32)
    # Calibrate on held-out OK images when we have them, otherwise on training images.
    cal_ok = [ok_images[i] for i in (val_idx or train_idx)]
    ok_maps = [model.anomaly_map(im) for im in cal_ok]
    ok_scores = [model.score(m) for m in ok_maps]
    ng_scores = [model.score(model.anomaly_map(im)) for im in ng_images]
    thr, rule = calibrate(ok_scores, ng_scores)
    pix = max(float(np.percentile(np.concatenate([m.ravel() for m in ok_maps]), 99.95)) * 1.15, thr * 0.6)
    model.meta.update(
        image_threshold=thr,
        pixel_threshold=max(pix, 1e-4),
        threshold_rule=rule,
        ok_scores=ok_scores,
        ng_scores=ng_scores,
        n_ok_train=len(train_set),
        n_ok_val=n_val,
        n_ng=len(ng_images),
        epochs_run=len(loss_hist),
        final_loss=loss_hist[-1],
        loss_history=loss_hist,
        train_seconds=round(time.time() - t0, 1),
    )
    say(
        len(loss_hist),
        cfg.epochs,
        loss_hist[-1],
        f"Calibrated image threshold {thr:.4f} ({rule}); pixel threshold {pix:.4f}",
    )
    return model
