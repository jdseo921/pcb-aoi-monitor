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

import math
import random
import time
import zipfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from torch import nn

from ..data import atomic
from ..errors import QT_TRANSLATE_NOOP, AoiError, Phrase
from . import lineage, run_progress
from .jobs import JobCancelled

# Why an AI model file or a trained AI model is refused (AOI-TRN-001, AOI-TRN-004), as phrases shown translated (#198)
DAMAGED = QT_TRANSLATE_NOOP("Errors", "the file is damaged ({damaged})")
CRC_FAILS = QT_TRANSLATE_NOOP("Errors", "{entry} does not match its CRC-32")
IS_FOLDER = QT_TRANSLATE_NOOP("Errors", "{entry} is marked as a folder")
BAD_SIZE = QT_TRANSLATE_NOOP("Errors", "its input size {size} is not a multiple of {stride} pixels")
BAD_MAP = QT_TRANSLATE_NOOP("Errors", "its {key} is not a {size} x {size} map of finite numbers")
MALFORMED = QT_TRANSLATE_NOOP("Errors", "its metadata is malformed ({error})")
# A training run's progress lines and threshold rules: phrases the Training page shows in the UI language (#199).
TRAINING_ON = QT_TRANSLATE_NOOP(
    "Training", "Training on {train} OK images ({held_out} held out, {ng} NG for calibration) on {device}"
)
EPOCH_LOSS = QT_TRANSLATE_NOOP("Training", "Epoch {epoch} of {epochs}: loss {loss:.4f}")  # epoch 1 and every 5th
CALIBRATED = QT_TRANSLATE_NOOP(
    "Training", "Calibrated image threshold {threshold:.4f} ({rule}); pixel threshold {pixel:.4f}"
)
OK_ONLY = QT_TRANSLATE_NOOP("Training", "OK-only: max(mean+3σ, 1.05×max OK)")
SEPARABLE = QT_TRANSLATE_NOOP("Training", "separable: midpoint of max OK and min NG")
OVERLAP = QT_TRANSLATE_NOOP("Training", "overlap: OK-based cut, {missed}/{ng} labelled NG below it")
NOT_ABOVE_0 = {
    "image_threshold": QT_TRANSLATE_NOOP("Errors", "its image threshold {value} is not a number above 0"),
    "pixel_threshold": QT_TRANSLATE_NOOP("Errors", "its pixel threshold {value} is not a number above 0"),
}


class ModelFileError(AoiError):
    """An AI model file was refused: missing, damaged, or not a weights-only model file this app wrote (AOI-TRN-001)."""


# Metadata arrays that travel in the file as tensors and are used as NumPy arrays in memory.
_ARRAY_META_KEYS = ("err_mean", "err_std")
STRIDE = 16  # the encoder halves the input four times, so the network's input size is a multiple of this
# The least spread of the reconstruction error a pixel is scored by: with errors at most 1 (the decoder ends in a
# sigmoid) no score reaches 1 / SPREAD_FLOOR = 1000 σ, which a stored AI map holds (maps.AI_MAX).
SPREAD_FLOOR = 1e-3


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
    def __init__(self, ch: int = 32, latent: int = 128) -> None:
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


@dataclass(frozen=True)
class Prepared:
    """An image as the AI model reads it: its tensor at the network's input size, made once, and the image's height and
    width, to which its anomaly map is scaled back. A training run keeps these, not the images (REQ-TRN-007)."""

    tensor: torch.Tensor
    shape: tuple[int, int]


def prepare(img_bgr: np.ndarray, size: int) -> Prepared:
    """`img_bgr` as a training run keeps it: `to_tensor` at `size` px, and its height and width."""
    return Prepared(to_tensor(img_bgr, size), (int(img_bgr.shape[0]), int(img_bgr.shape[1])))


PIXEL_PERCENTILE = 99.95  # of every pixel of the calibration OK images' anomaly maps together


def top_percentile(maps: Iterable[np.ndarray], count: int, q: float) -> np.floating:
    """`np.percentile(np.concatenate([m.ravel() for m in maps]), q)`, numpy's linear method to the bit, holding only
    the largest values of each map rather than every map at once (REQ-TRN-007): the values at and above the rank the
    percentile reads are among them. `count` is the pixels of every map together, so a q near 100 keeps few values
    (99.95 keeps 0.05 % of them); `maps` may make each map as it is asked for."""
    at = (count - 1) * (q / 100)
    lo = math.floor(at)
    keep = count - lo  # the ranks lo to count - 1, counted from the smallest
    tops = []
    for m in maps:
        flat = m.ravel()
        k = min(keep, flat.size)
        tops.append(np.partition(flat, flat.size - k)[flat.size - k :].copy())  # a view would keep the whole map
    top = np.concatenate(tops)  # holds every value of rank lo or more, ties included
    first = top.size - keep  # rank lo is here, rank lo + 1 next
    part = np.partition(top, [first, first + 1] if keep > 1 else [first])
    a, b = part[first], part[first + 1] if keep > 1 else part[first]
    gamma, diff = at - lo, b - a
    out: np.floating = b - diff * (1 - gamma) if gamma >= 0.5 else a + diff * gamma  # numpy's _lerp, in its order
    return out


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


# What a run has done (REQ-TRN-008): its "step"s (training steps) or "map"s (calibration maps) done of the total, and a
# line for its log, "" or a Phrase (#199); a report repeats the count when it only brings a line.
ProgressFn = Callable[[str, int, int, str], None]


def held_out(n: int, fraction: float) -> int:
    """How many of `n` OK images a run holds out to calibrate on rather than train on: none under 5."""
    return max(1, int(round(n * fraction))) if n >= 5 else 0


def probe(image: Prepared, cfg: TrainConfig) -> tuple[float, float]:
    """The seconds one training step and one calibration map of `image` take on `cfg.device`, timed on a throwaway
    network, so a run's time left is known before its first training step (REQ-TRN-008). The step is timed the second
    time: the first in a process also starts PyTorch's threads, about 1.2 s against a step's 0.15 s on a 4-core VM at
    256 px. It draws from the random sources before `train` seeds them, so the AI model trained is the same with or
    without it."""
    net = ConvAutoencoder().to(cfg.device)
    opt = torch.optim.Adam(net.parameters(), lr=cfg.lr)

    def step() -> None:
        batch = torch.stack([augment(image.tensor) for _ in range(cfg.batch_size)]).to(cfg.device)
        rec = net(batch)
        loss = nn.L1Loss()(rec, batch) + 0.5 * ((rec - batch) ** 2).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
        loss.item()  # the step is done once its loss is on the CPU, as a run's is

    step()
    start = run_progress.clock()
    step()
    stepped = run_progress.clock()
    model = AnomalyModel(
        net, {"image_size": cfg.image_size, "image_threshold": 1.0, "pixel_threshold": 1.0}, cfg.device
    )
    model.score(model.prepared_map(image))
    return stepped - start, run_progress.clock() - stepped


class AnomalyModel:
    """Wraps the network with its calibration so callers only see scores."""

    def __init__(self, net: ConvAutoencoder, meta: dict[str, Any], device: str = "cpu") -> None:
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

    def raw_error(self, img_bgr: np.ndarray) -> np.ndarray:
        """Reconstruction error at network resolution."""
        return self._raw(to_tensor(img_bgr, self.size))

    @torch.no_grad()
    def _raw(self, t: torch.Tensor) -> np.ndarray:
        x = t.unsqueeze(0).to(self.device)
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
        return self._scaled(self.raw_error(img_bgr), (img_bgr.shape[0], img_bgr.shape[1]))

    def prepared_map(self, image: Prepared) -> np.ndarray:
        """`anomaly_map` of the image `image` was prepared from, to the bit, made from its tensor (REQ-TRN-007)."""
        return self._scaled(self._raw(image.tensor), image.shape)

    def _scaled(self, err: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        m = max(2, self.size // 64)  # warped borders are never meaningful
        err[:m, :] = err[-m:, :] = 0
        err[:, :m] = err[:, -m:] = 0
        mu, sd = self.meta.get("err_mean"), self.meta.get("err_std")
        if mu is not None:
            err = np.clip((err - mu) / sd, 0, None)
            err = cv2.GaussianBlur(err, (0, 0), sigmaX=1.5)
        return cv2.resize(err, (shape[1], shape[0]), interpolation=cv2.INTER_LINEAR)

    def score(self, amap: np.ndarray) -> float:
        # 99.9th percentile is robust to single hot pixels but catches small defects.
        return float(np.percentile(amap, 99.9))

    def save(self, path: Path) -> None:
        payload = {"state_dict": self.net.state_dict(), "meta": _to_safe(self.meta)}
        atomic.write_with(path, lambda f: torch.save(payload, f))

    @classmethod
    def load(cls, path: str | Path, device: str = "cpu") -> AnomalyModel:
        """Load a model file as weights only (REQ-TRN-014). A file that needs code to unpickle, or that is missing,
        truncated, damaged in place, not this app's AI model or holding numbers it cannot judge with, is refused
        with AOI-TRN-001 naming it; nothing falls back to a less strict load."""
        try:
            with zipfile.ZipFile(path) as z:  # torch.save writes a zip, and each entry carries a CRC-32 of its bytes
                crc = z.testzip()  # a weight changed on disk would otherwise load and judge boards wrongly
                # torch never reads the bytes of an entry flagged as a folder: its weights would be stray memory
                folder = next((i.filename for i in z.infolist() if i.is_dir() or i.external_attr & 0x10), None)
            damaged = CRC_FAILS.fill(entry=crc) if crc else IS_FOLDER.fill(entry=folder) if folder else None
            ckpt = None if damaged else torch.load(path, map_location=device, weights_only=True)
        except OSError as e:  # gone, a folder, unreadable, or cut short (torch reports EINVAL)
            raise ModelFileError("AOI-TRN-001", path=str(path), reason=e.strerror or type(e).__name__) from e
        except Exception as e:  # any other way a malformed file trips the reader: refused, never an uncoded error
            raise ModelFileError("AOI-TRN-001", path=str(path), reason=type(e).__name__) from e
        if damaged:
            raise ModelFileError("AOI-TRN-001", path=str(path), reason=DAMAGED.fill(damaged=damaged))
        if (
            not isinstance(ckpt, dict)
            or not isinstance(ckpt.get("meta"), dict)
            or not isinstance(ckpt.get("state_dict"), dict)
        ):
            raise ModelFileError(
                "AOI-TRN-001", path=str(path), reason=QT_TRANSLATE_NOOP("Errors", "it holds no state_dict and metadata")
            )
        try:
            meta = _from_safe(ckpt["meta"])
            why = _unusable(meta, ckpt["state_dict"])
        except Exception as e:  # metadata of a kind this app never writes, such as a bfloat16 map
            raise ModelFileError("AOI-TRN-001", path=str(path), reason=MALFORMED.fill(error=type(e).__name__)) from e
        if why is not None:
            raise ModelFileError("AOI-TRN-001", path=str(path), reason=why)
        net = ConvAutoencoder()
        try:
            net.load_state_dict(ckpt["state_dict"])
        except Exception as e:  # names or shapes of another network, or weights that are not tensors
            why = QT_TRANSLATE_NOOP("Errors", "its weights do not fit this app's AI model")
            raise ModelFileError("AOI-TRN-001", path=str(path), reason=why) from e
        return cls(net, meta, device)


def _unusable(meta: dict[str, Any], weights: dict[str, Any]) -> str | None:
    """Why a model file's contents cannot judge a board, or None: the input size, the two thresholds as finite numbers
    above 0, the normal-error maps (both or neither) as finite size x size maps with a spread above 0, and finite
    weights."""
    size = meta.get("image_size")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= 4096 or size % STRIDE:
        return BAD_SIZE.fill(size=repr(size), stride=STRIDE)
    for key in ("image_threshold", "pixel_threshold"):
        value = meta.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (math.isfinite(value) and value > 0):
            return NOT_ABOVE_0[key].fill(value=repr(value))
    maps = [meta.get(key) for key in _ARRAY_META_KEYS]
    if any(m is not None for m in maps):
        for key, m in zip(_ARRAY_META_KEYS, maps, strict=True):
            if not isinstance(m, np.ndarray) or m.shape != (size, size) or not np.isfinite(m).all():
                return BAD_MAP.fill(key=key, size=size)
        if (meta["err_std"] <= 0).any():
            return QT_TRANSLATE_NOOP("Errors", "its err_std holds a spread of 0 or less")
    if not all(bool(torch.isfinite(t).all()) for t in weights.values() if torch.is_tensor(t) and t.is_floating_point()):
        return QT_TRANSLATE_NOOP("Errors", "its weights hold numbers that are not finite")
    return None


def calibrate(ok_scores: list[float], ng_scores: list[float]) -> tuple[float, Phrase]:
    """Pick the image-level threshold from validation scores; the rule that picked it is a phrase (#199)."""
    ok = np.array(ok_scores, dtype=np.float64)
    stat = float(ok.mean() + 3 * ok.std()) if len(ok) > 1 else float(ok.max() * 1.25)
    base = max(stat, float(ok.max()) * 1.05)
    if not ng_scores:
        return base, OK_ONLY
    ng = np.array(ng_scores, dtype=np.float64)
    if ng.min() > ok.max():
        return float((ok.max() + ng.min()) / 2), SEPARABLE
    # Overlap: keep the OK-based cut so good boards are not flagged; the golden-sample
    # comparison is the second line of defence for the NG samples that fall below it.
    missed = int((ng < base).sum())
    return base, OVERLAP.fill(missed=missed, ng=len(ng))


def train(
    ok_images: Sequence[Prepared],
    ng_images: Sequence[Prepared],
    cfg: TrainConfig,
    progress: ProgressFn | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> AnomalyModel:
    """An AI model learnt from the OK images, prepared at `cfg.image_size`; the NG images only calibrate its image
    threshold (REQ-TRN-007). Each anomaly map is made at its image's size when it is scored and then let go: the run
    holds no image and no map at the camera's resolution beyond the one in hand.

    `progress` hears of the start of training and of every training step and calibration map as it ends, and
    `should_stop()` is asked after each report: once it is true the run raises JobCancelled there, so it stops within
    a step and returns no AI model (REQ-TRN-008).

    Lineage (REQ-TRN-009): the run seeds every random source it draws from with `cfg.seed` and uses PyTorch's
    deterministic algorithms, so the same images and `cfg` give the same AI model on the same machine; its metadata
    records the seed and every setting of `cfg`."""
    if len(ok_images) < 2:
        raise AoiError("AOI-TRN-002", found=len(ok_images))
    with lineage.deterministic():
        model = _train(ok_images, ng_images, cfg, progress, should_stop)
    model.meta.update(seed=cfg.seed, settings=asdict(cfg), deterministic=True)
    return model


def _train(
    ok_images: Sequence[Prepared],
    ng_images: Sequence[Prepared],
    cfg: TrainConfig,
    progress: ProgressFn | None,
    should_stop: Callable[[], bool] | None,
) -> AnomalyModel:
    """`train`'s run, inside PyTorch's deterministic algorithms."""
    lineage.seed_everything(cfg.seed)
    say = progress or (lambda *a: None)

    def stop() -> None:  # Cancel, or the window closing: nothing of the run is kept (#171)
        if should_stop is not None and should_stop():
            raise JobCancelled("training")

    tensors = [p.tensor for p in ok_images]
    idx = list(range(len(tensors)))
    random.shuffle(idx)
    n_val = held_out(len(idx), cfg.val_fraction)
    val_idx, train_idx = idx[:n_val], idx[n_val:]
    train_set = [tensors[i] for i in train_idx]

    net = ConvAutoencoder().to(cfg.device)
    opt = torch.optim.Adam(net.parameters(), lr=cfg.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=cfg.epochs)
    l1 = nn.L1Loss()
    t0 = time.time()
    steps = cfg.epochs * cfg.steps_per_epoch
    say("step", 0, steps, TRAINING_ON.fill(train=len(train_set), held_out=n_val, ng=len(ng_images), device=cfg.device))
    stop()
    loss_hist = []
    for ep in range(1, cfg.epochs + 1):
        net.train()
        running = 0.0
        for i in range(1, cfg.steps_per_epoch + 1):
            batch = torch.stack([augment(random.choice(train_set)) for _ in range(cfg.batch_size)]).to(cfg.device)
            rec = net(batch)
            loss = l1(rec, batch) + 0.5 * ((rec - batch) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            running += loss.item()
            note = ""
            if i == cfg.steps_per_epoch:  # the epoch's last step
                sched.step()
                loss_hist.append(running / cfg.steps_per_epoch)
                if ep == 1 or ep % 5 == 0:
                    note = EPOCH_LOSS.fill(epoch=ep, epochs=cfg.epochs, loss=loss_hist[-1])
            say("step", (ep - 1) * cfg.steps_per_epoch + i, steps, note)
            stop()

    model = AnomalyModel(
        net, {"image_size": cfg.image_size, "image_threshold": 1.0, "pixel_threshold": 1.0}, cfg.device
    )
    # Per-pixel error statistics of good boards (the learned "normal variation"), summed in float64: the mean of equal
    # errors is then that error to the bit, whatever their count, so a board like every training board scores 0 (#168).
    errs = np.stack([model._raw(tensors[i]) for i in train_idx])
    sd = errs.std(axis=0, dtype=np.float64)
    model.meta["err_mean"] = errs.mean(axis=0, dtype=np.float64).astype(np.float32)
    model.meta["err_std"] = np.maximum(sd, max(float(np.median(sd)), SPREAD_FLOOR)).astype(np.float32)
    # Calibrate on held-out OK images when we have them, otherwise on training images.
    cal_ok = [ok_images[i] for i in (val_idx or train_idx)]
    ok_scores: list[float] = []
    ng_scores: list[float] = []
    maps = len(cal_ok) + len(ng_images)

    def scored(images: Sequence[Prepared]) -> Iterable[np.ndarray]:  # each map scored, then read for its top
        for p in images:
            amap = model.prepared_map(p)
            ok_scores.append(model.score(amap))
            yield amap
            say("map", len(ok_scores), maps, "")  # once the map's largest values are read
            stop()

    pixels = sum(p.shape[0] * p.shape[1] for p in cal_ok)
    top = float(top_percentile(scored(cal_ok), pixels, PIXEL_PERCENTILE))
    for p in ng_images:
        ng_scores.append(model.score(model.prepared_map(p)))
        say("map", len(ok_scores) + len(ng_scores), maps, "")
        stop()
    thr, rule = calibrate(ok_scores, ng_scores)
    pix = max(top * 1.15, thr * 0.6)
    model.meta.update(
        image_threshold=thr,
        pixel_threshold=max(pix, 1e-4),
        threshold_rule=str(rule),  # plain text: a model file holds tensors and plain values only
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
    # A model the loader would refuse is refused here, before anything is saved or activated: OK images that are copies
    # of one photo score 0, so the threshold is 0.
    if (why := _unusable(model.meta, model.net.state_dict())) is not None:
        raise AoiError("AOI-TRN-004", reason=why)
    say("map", maps, maps, CALIBRATED.fill(threshold=thr, rule=rule, pixel=pix))
    return model
