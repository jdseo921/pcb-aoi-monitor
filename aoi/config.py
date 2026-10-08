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
from typing import Any

from .errors import QT_TRANSLATE_NOOP, AoiError

APP_NAME = "AOI PoC Inspector"
APP_VERSION = "0.2.0"


# Why settings.json is refused (AOI-SET-010, AOI-SET-008), as phrases shown translated (#198)
NOT_JSON = QT_TRANSLATE_NOOP("Errors", "it is not valid JSON (line {line}, column {column}: {problem})")
NOT_UTF8 = QT_TRANSLATE_NOOP("Errors", "it is not UTF-8 text")
NOT_OBJECT = QT_TRANSLATE_NOOP("Errors", "it does not hold a JSON object of settings")
FULL_PATH = QT_TRANSLATE_NOOP("Errors", "the full path of a folder")
EXPECTED = {  # what a setting must be, by its type and _LEAST
    (int, None): QT_TRANSLATE_NOOP("Errors", "a whole number"),
    (int, 1): QT_TRANSLATE_NOOP("Errors", "a whole number above 0"),
    (int, 0): QT_TRANSLATE_NOOP("Errors", "a whole number of 0 or more"),
    (str, None): QT_TRANSLATE_NOOP("Errors", "text"),
}
_LEAST = {  # the smallest whole number a count setting takes; a map retention of 0 deletes OK maps at the next start
    "max_image_megapixels": 1,
    "max_image_megabytes": 1,
    "log_retention_days": 1,
    "image_size": 1,
    "default_epochs": 1,
    "map_retention_days_ok": 0,
}


def default_workspace() -> Path:
    """The workspace folder, and where settings.json lives: AOI_WORKSPACE or ~/AOI_Workspace as a full path, so the
    workspace the app holds is one settings.json accepts (AOI-SET-008 refuses a relative one). os.path.abspath, not
    Path.absolute(), which on Python 3.11 leaves a drive-relative "C:AOI_Workspace" relative on Windows (#170)."""
    return Path(os.path.abspath(os.path.expanduser(os.environ.get("AOI_WORKSPACE", Path.home() / "AOI_Workspace"))))


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
        data = cls._read()
        if data is None:
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        for name, value in known.items():
            cls.check(name, value)
        return cls(**known)

    @classmethod
    def _read(cls) -> dict[str, Any] | None:
        """settings.json as it is on disk now, or None when there is none; a file that cannot be read is refused with
        AOI-SET-010."""
        f = cls._file()
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise AoiError(
                "AOI-SET-010", path=str(f), reason=NOT_JSON.fill(line=e.lineno, column=e.colno, problem=e.msg)
            ) from e
        except UnicodeDecodeError as e:
            raise AoiError("AOI-SET-010", path=str(f), reason=NOT_UTF8) from e
        except OSError as e:
            raise AoiError("AOI-SET-010", path=str(f), reason=e.strerror or type(e).__name__) from e
        if not isinstance(data, dict):
            raise AoiError("AOI-SET-010", path=str(f), reason=NOT_OBJECT)
        return data

    @classmethod
    def check(cls, name: str, value: object) -> None:
        """Refuse a value of the wrong JSON type for a known setting, an image limit, a log retention, an image size or
        an epoch count below 1, a map retention below 0, and a workspace that is not an absolute path (empty, spaces
        only or relative: Path("") is the folder the app was started in), with AOI-SET-008: at start-up, and on the
        Settings page before it saves (REQ-INSP-001, S23c: a typo there used to fail every image load with
        AOI-SET-007; #170: a log retention of 0 or below archived every record at start-up). An unknown key is
        still ignored, so an old or a newer settings.json loads."""
        want = type(getattr(cls(), name))
        least = _LEAST.get(name)
        typed = isinstance(value, want) and not (want is int and isinstance(value, bool))
        if name == "workspace" and typed and not Path(str(value)).is_absolute():
            raise AoiError("AOI-SET-008", name=name, value=json.dumps(value), expected=FULL_PATH)
        if not typed or (least is not None and isinstance(value, int) and value < least):
            expected = EXPECTED.get((want, least), want.__name__)
            raise AoiError("AOI-SET-008", name=name, value=json.dumps(value), expected=expected)

    def save_keys(self, values: dict[str, object]) -> dict[str, object]:
        """Write `values` over settings.json as it is on disk now, so every other key keeps what the file holds, a hand
        edit made while the app runs included (#170); with no file yet, over these settings, every one of which is then
        checked too, so the first write never stores a value the next start refuses. Each value is checked first, as
        `load` checks it (AOI-SET-008), and a file that cannot be read is refused with AOI-SET-010, never overwritten.
        These settings themselves are left as they are: the caller sets what the running app follows. Returns what was
        in effect for each key of `values` before: the value in the file, or the default a start reads (#197)."""
        for name, value in values.items():
            self.check(name, value)
        data = self._read()
        if data is None:
            data = asdict(self)
            for name, value in data.items():
                self.check(name, values.get(name, value))
        defaults = asdict(type(self)())  # what a start reads for a key the file does not hold
        before = {name: data.get(name, defaults.get(name)) for name in values}
        data.update(values)
        from .data import atomic  # settings.json is read at start-up: never leave it half-written

        atomic.write_text(self._file(), json.dumps(data, indent=2))
        return before

    def save(self) -> None:
        f = self._file()
        from .data import atomic  # settings.json is read at start-up: never leave it half-written

        atomic.write_text(f, json.dumps(asdict(self), indent=2))


def resolve_device(pref: str) -> str:
    import torch

    if pref == "cuda" or (pref == "auto" and torch.cuda.is_available()):
        return "cuda" if torch.cuda.is_available() else "cpu"
    return "cpu"
