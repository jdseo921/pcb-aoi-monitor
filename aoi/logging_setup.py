"""JSON-lines application log (REQ-LOG-004, log part; stage S12b). No Qt.

One JSON object per line in ``<workspace>/logs/aoi-YYYY-MM-DD.jsonl``, a new file each UTC day. Every line
carries the time (UTC, ISO 8601 with an offset), level, module, event, the app version and the ids the
caller attached (board model, inspection id, model version, a user's UUID). Images, passwords and personal
data beyond a user's UUID never go in: array and byte values are replaced by a size note, and keys that
look like secrets are dropped.
"""

from __future__ import annotations

import json
import logging
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from .config import APP_VERSION

LOGGER = "aoi"
SECRET_KEYS = ("password", "passwd", "secret", "token", "api_key")
_RECORD_FIELDS = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime", "taskName"}


class JsonLinesHandler(logging.Handler):
    """Writes one JSON object per record to ``aoi-<UTC date>.jsonl`` in `folder`, switching files at midnight UTC."""

    def __init__(self, folder: Path, clock: Callable[[], datetime] | None = None) -> None:
        super().__init__()
        self.folder = Path(folder)
        self.clock = clock or (lambda: datetime.now(UTC))
        self._day: str | None = None
        self._file: IO[str] | None = None

    def path_for(self, day: str) -> Path:
        return self.folder / f"aoi-{day}.jsonl"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            now = self.clock()
            day = now.strftime("%Y-%m-%d")
            if day != self._day or self._file is None:
                self._open(day)
            line: dict[str, Any] = {
                "time": now.isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "module": record.name,
                "event": record.getMessage(),
                "app_version": APP_VERSION,
            }
            line.update(scrub({k: v for k, v in record.__dict__.items() if k not in _RECORD_FIELDS}))
            if record.exc_info and record.exc_info[0] is not None:
                line["trace"] = "".join(traceback.format_exception(*record.exc_info))
            assert self._file is not None
            self._file.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
            self._file.flush()
        except Exception:
            self.handleError(record)

    def _open(self, day: str) -> None:
        if self._file is not None:
            self._file.close()
        self.folder.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path_for(day), "a", encoding="utf-8")
        self._day = day

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        super().close()


def scrub(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop keys that look like secrets and replace binary and array values: no image or password reaches the log."""
    return {str(k): _scrub_value(v) for k, v in fields.items() if not any(s in str(k).lower() for s in SECRET_KEYS)}


def _scrub_value(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes omitted>"
    if hasattr(value, "shape") and hasattr(value, "dtype"):  # a NumPy array or a tensor, without importing either
        return f"<array {tuple(value.shape)} omitted>"
    if isinstance(value, dict):
        return scrub(value)
    if isinstance(value, (list, tuple)):
        return [_scrub_value(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def setup(workspace: Path, level: int = logging.INFO, clock: Callable[[], datetime] | None = None) -> logging.Logger:
    """Point the "aoi" logger at `<workspace>/logs/`, replacing an earlier handler, and return it."""
    log = logging.getLogger(LOGGER)
    for h in list(log.handlers):
        if isinstance(h, JsonLinesHandler):
            log.removeHandler(h)
            h.close()
    log.addHandler(JsonLinesHandler(Path(workspace) / "logs", clock))
    log.setLevel(level)
    log.propagate = False  # the file is the record; nothing goes to the console the operator never sees
    return log
