"""Image I/O and registration helpers (OpenCV)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def load_image(path: str | Path) -> np.ndarray:
    """Read as BGR uint8. Uses imdecode so non-ASCII (e.g. Korean) Windows paths work."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Cannot read image: {path}")
    return img


def save_image(path: str | Path, img: np.ndarray) -> None:
    ext = Path(path).suffix or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise ValueError(f"Cannot encode image: {path}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    buf.tofile(str(path))


def list_images(folder: str | Path) -> list[Path]:
    return sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in IMAGE_EXTS)


def align_to_reference(img: np.ndarray, ref: np.ndarray, max_features: int = 4000) -> tuple[np.ndarray, dict]:
    """Register `img` onto `ref` with ORB features + RANSAC homography.

    Boards are never placed at exactly the same spot, so every pixel comparison
    (golden-sample diff, ROI checks) happens after this step. Falls back to a plain
    resize when not enough features match; `info["aligned"]` tells the UI which.
    """
    h, w = ref.shape[:2]
    info = {"aligned": False, "inliers": 0, "method": "resize"}
    g1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(max_features)
    k1, d1 = orb.detectAndCompute(g1, None)
    k2, d2 = orb.detectAndCompute(g2, None)
    if d1 is not None and d2 is not None and len(k1) >= 10 and len(k2) >= 10:
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = sorted(matcher.match(d1, d2), key=lambda m: m.distance)[:500]
        if len(matches) >= 10:
            src = np.float32([k1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
            dst = np.float32([k2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
            H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
            if H is not None and mask is not None and int(mask.sum()) >= 12:
                warped = cv2.warpPerspective(img, H, (w, h), borderMode=cv2.BORDER_REPLICATE)
                info.update(aligned=True, inliers=int(mask.sum()), method="orb-homography")
                return warped, info
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA), info


def heatmap(values: np.ndarray, vmax: float | None = None) -> np.ndarray:
    """Float map -> BGR color heatmap (for the Compare page and overlays)."""
    v = values.astype(np.float32)
    vmax = vmax if vmax and vmax > 0 else float(v.max() or 1.0)
    u8 = np.clip(v / vmax * 255.0, 0, 255).astype(np.uint8)
    return cv2.applyColorMap(u8, cv2.COLORMAP_JET)


def blend(img: np.ndarray, overlay: np.ndarray, alpha: float = 0.45) -> np.ndarray:
    if overlay.shape[:2] != img.shape[:2]:
        overlay = cv2.resize(overlay, (img.shape[1], img.shape[0]))
    return cv2.addWeighted(img, 1 - alpha, overlay, alpha, 0)


def heat_overlay(img: np.ndarray, values: np.ndarray, vmax: float) -> np.ndarray:
    """Colour only where `values` is high, so the board stays readable underneath."""
    if values.shape[:2] != img.shape[:2]:
        values = cv2.resize(values, (img.shape[1], img.shape[0]))
    a = np.clip(values.astype(np.float32) / max(vmax, 1e-6), 0, 1)[..., None] * 0.8
    return (img * (1 - a) + heatmap(values, vmax) * a).astype(np.uint8)
