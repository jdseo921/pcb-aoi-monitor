"""The synthetic workspace the screen tests render and measure (REQ-SET-004; S21), built once per module."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from aoi.core.services import AppContext
from tools import render_screens


@pytest.fixture(scope="module")
def screens(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[AppContext, Path]]:
    """The workspace of `tools/render_screens.py` and its dataset folder; stored times are shown as UTC."""
    restore_zone = render_screens.pin_time_zone()
    root = tmp_path_factory.mktemp("screens")
    ctx = render_screens.build_workspace(root)
    yield ctx, root / "dataset"
    ctx.close()
    restore_zone()
