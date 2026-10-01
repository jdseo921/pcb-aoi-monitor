"""Hardware abstraction layer for Stages 2-4.

Stage 1 only needs `FolderCamera` (uploaded images behave like a camera that
returns one frame per file). Real drivers implement the same interfaces so the
Inspection page and the inspection cycle do not change when hardware arrives:

  Stage 2  Camera   -> GigE Vision / USB3 Vision (e.g. Harvester/GenICam, vendor SDK)
           Lighting -> serial or Ethernet controller
  Stage 3  Robot    -> Ethernet / RS-485 controller: load, inspect, unload, e-stop
  Stage 4  MES      -> REST API or OPC UA: lot id, model, result, timestamp, images
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from ..core.imaging import list_images, load_image

VIEWS = ("Top", "Side", "Bottom")


class Camera(ABC):
    name = "camera"

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def grab(self, view: str = "Top") -> np.ndarray | None:
        """Return one BGR frame for the requested view, or None when exhausted."""

    def close(self) -> None:  # noqa: B027
        """Release the device. Optional, so a no-op here: image-file cameras hold nothing open."""


class FolderCamera(Camera):
    """Stage 1 'camera': iterates over uploaded image files."""

    name = "Image files (Stage 1)"

    def __init__(self, paths: Sequence[str | Path]) -> None:
        self.paths = [Path(p) for p in paths]
        self.index = -1

    @classmethod
    def from_folder(cls, folder: str | Path) -> FolderCamera:
        return cls(list_images(folder))

    def open(self) -> None:
        self.index = -1

    def grab(self, view: str = "Top") -> np.ndarray | None:
        self.index += 1
        if self.index >= len(self.paths):
            return None
        return load_image(self.paths[self.index])

    @property
    def current_path(self) -> Path | None:
        return self.paths[self.index] if 0 <= self.index < len(self.paths) else None


class GigEVisionCamera(Camera):
    name = "GigE / USB3 Vision (Stage 2)"

    def open(self) -> None:
        raise NotImplementedError("Stage 2: integrate GenICam driver for the selected camera vendor")

    def grab(self, view: str = "Top") -> np.ndarray | None:
        raise NotImplementedError


class LightingController(ABC):
    @abstractmethod
    def set_channel(self, channel: int, level: int) -> None: ...


class RobotController(ABC):
    """Stage 3 command set from the spec: Load -> Inspect -> Unload, plus safety."""

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def move_to_inspect(self, view: str) -> None: ...

    @abstractmethod
    def unload(self, result: str) -> None: ...

    @abstractmethod
    def emergency_stop(self) -> None: ...


class MesClient(ABC):
    """Stage 4: push results for traceability and authenticate operators."""

    @abstractmethod
    def upload_result(
        self, lot_id: str, board_model: str, result: str, timestamp: str, image_paths: list[str]
    ) -> None: ...

    @abstractmethod
    def authenticate(self, user: str, password: str) -> str | None:
        """Return the user's role, or None if rejected."""
