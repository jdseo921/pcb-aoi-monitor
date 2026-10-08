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

from .errors import AoiError

APP_NAME = "AOI PoC Inspector"
APP_VERSION = "0.2.0"


def default_workspace() -> Path:
    return Path(os.environ.get("AOI_WORKSPACE", Path.home() / "AOI_Workspace"))


@dataclass
class Settings:
    workspace: str = field(default_factory=lambda: str(default_workspace()))
    device: str = "auto"  # auto | cpu | cuda
    image_size: int = 256  # network input size (square)
    default_epochs: int = 60
    log_retention_days: int = 30  # spec 4.4: inspection records older than this are archived at start-up (REQ-LOG-003)
    map_retention_days_ok: int = 7  # REQ-INSP-012: the map files of OK results older than this go at start-up (0: next)
    max_image_megapixels: int = 50  # REQ-INSP-001: an image over either limit is refused before it is decoded
    max_image_megabytes: int = 200  # (the register's proposed values; an Admin edits them in settings.json)
    language: str = "en"  # en | ko (localization planned for 2H 2027)
    last_page: str = "Home"  # the page to reopen after a restart (REQ-LOG-005)

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
    def load(cls) -> Settings:
        """The settings in settings.json, or the defaults when there is none. A file that cannot be read is refused
        with AOI-SET-010 and a wrong value with AOI-SET-008, before the app starts (REQ-SET-019). The workspace folder
        is created by AppContext, which refuses one that cannot be (AOI-SET-011) and so offers another."""
        f = cls._file()
        if not f.exists():
            return cls()
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise AoiError(
                "AOI-SET-010", path=str(f), reason=f"it is not valid JSON (line {e.lineno}, column {e.colno}: {e.msg})"
            ) from e
        except UnicodeDecodeError as e:
            raise AoiError("AOI-SET-010", path=str(f), reason="it is not UTF-8 text") from e
        except OSError as e:
            raise AoiError("AOI-SET-010", path=str(f), reason=e.strerror or type(e).__name__) from e
        if not isinstance(data, dict):
            raise AoiError("AOI-SET-010", path=str(f), reason="it does not hold a JSON object of settings")
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        for name, value in known.items():
            cls.check(name, value)
        return cls(**known)

    @classmethod
    def check(cls, name: str, value: object) -> None:
        """Refuse a value of the wrong JSON type for a known setting, an image limit that is not above 0 and a retention
        below 0, with AOI-SET-008 before the app starts (REQ-INSP-001, S23c: a typo there used to fail every image load
        with AOI-SET-007). An unknown key is still ignored, so an old or a newer settings.json loads."""
        want = type(getattr(cls(), name))
        least = {"max_image_megapixels": 1, "max_image_megabytes": 1, "map_retention_days_ok": 0}.get(name)
        typed = isinstance(value, want) and not (want is int and isinstance(value, bool))
        if not typed or (least is not None and isinstance(value, int) and value < least):
            expected = {int: "a whole number", str: "text"}.get(want, want.__name__)
            if least is not None:
                expected += " above 0" if least else " of 0 or more"
            raise AoiError("AOI-SET-008", name=name, value=json.dumps(value), expected=expected)

    def save(self) -> None:
        f = self._file()
        from .data import atomic  # settings.json is read at start-up: never leave it half-written

        atomic.write_text(f, json.dumps(asdict(self), indent=2))


def resolve_device(pref: str) -> str:
    import torch

    if pref == "cuda" or (pref == "auto" and torch.cuda.is_available()):
        return "cuda" if torch.cuda.is_available() else "cpu"
    return "cpu"
