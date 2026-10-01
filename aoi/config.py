"""Application paths and persisted settings.

Everything the app writes (database, images, models, exports) lives under one
workspace folder so a PoC station can be backed up or moved by copying it.
The default is ~/AOI_Workspace; override with the AOI_WORKSPACE env variable
or from the Settings page.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "AOI PoC Inspector"
APP_VERSION = "0.1.0"


def default_workspace() -> Path:
    return Path(os.environ.get("AOI_WORKSPACE", Path.home() / "AOI_Workspace"))


@dataclass
class Settings:
    workspace: str = field(default_factory=lambda: str(default_workspace()))
    device: str = "auto"  # auto | cpu | cuda
    image_size: int = 256  # network input size (square)
    default_epochs: int = 60
    log_retention_days: int = 30  # spec 4.4: auto-archive logs older than 30 days
    language: str = "en"  # en | ko (localization planned for 2H 2027)

    # --- paths derived from workspace ------------------------------------
    @property
    def root(self) -> Path:
        return Path(self.workspace)

    @property
    def db_path(self) -> Path:
        return self.root / "aoi.sqlite"

    @property
    def images_dir(self) -> Path:
        return self.root / "images"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def recipes_dir(self) -> Path:
        return self.root / "recipes"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    def ensure_dirs(self) -> None:
        for p in (self.root, self.images_dir, self.models_dir, self.recipes_dir, self.results_dir, self.exports_dir):
            p.mkdir(parents=True, exist_ok=True)

    # --- persistence -------------------------------------------------------
    @staticmethod
    def _file() -> Path:
        return default_workspace() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        f = cls._file()
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            s = cls(**known)
        else:
            s = cls()
        s.ensure_dirs()
        return s

    def save(self) -> None:
        f = self._file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def resolve_device(pref: str) -> str:
    import torch

    if pref == "cuda" or (pref == "auto" and torch.cuda.is_available()):
        return "cuda" if torch.cuda.is_available() else "cpu"
    return "cpu"
