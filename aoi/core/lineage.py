"""Where an AI model came from (REQ-TRN-009; Engineering standard, "Lineage"): the code that trained it and the random
sources it drew from. No Qt, no subprocess and no network: the commit is read from the repository's own files.

A training run seeds every random source it draws from (Python's, NumPy's and PyTorch's, which also set the order the
training images are drawn in) and runs PyTorch's deterministic algorithms where it has them, so retraining the same
inputs on the same machine gives the same AI model; `tests/test_lineage.py` proves it on CPU."""

from __future__ import annotations

import random
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import torch

from ..config import APP_VERSION

ROOT = Path(__file__).resolve().parents[2]  # the repository a source checkout runs from
SHA = re.compile(r"^[0-9a-f]{40}$")


def _git_dir(root: Path) -> Path | None:
    """The repository's git folder: `.git`, or the folder a worktree's `.git` file names."""
    dot = root / ".git"
    if dot.is_dir():
        return dot
    if dot.is_file():
        text = dot.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            found = Path(text[len("gitdir:") :].strip())
            return found if found.is_absolute() else (root / found).resolve()
    return None


def _commit(git: Path) -> str | None:
    """The commit HEAD names, read from HEAD, the ref it points to or packed-refs; None if none of them gives one."""
    head = (git / "HEAD").read_text(encoding="utf-8").strip()
    if SHA.match(head):  # a detached HEAD
        return head
    if not head.startswith("ref:"):
        return None
    ref = head[len("ref:") :].strip()
    common = git / "commondir"  # a worktree keeps its branches in the main repository's folder
    homes = [git] + ([(git / common.read_text(encoding="utf-8").strip()).resolve()] if common.is_file() else [])
    for home in homes:
        loose = home / ref
        if loose.is_file() and SHA.match(sha := loose.read_text(encoding="utf-8").strip()):
            return sha
        packed = home / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split(" ")
                if len(parts) == 2 and parts[1] == ref and SHA.match(parts[0]):
                    return parts[0]
    return None


def code_version(root: Path = ROOT) -> str:
    """The code that runs: "commit <sha>" in a source checkout, else "build <app version>" (a packaged app has no git
    folder; its version is the build's). A git folder that cannot be read falls back to the build version too."""
    try:
        git = _git_dir(root)
        sha = _commit(git) if git is not None else None
    except (OSError, UnicodeDecodeError):
        sha = None
    return f"commit {sha}" if sha else f"build {APP_VERSION}"


def seed_everything(seed: int) -> None:
    """Seed Python's, NumPy's and PyTorch's random sources; the order training images are drawn in comes from
    Python's."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


@contextmanager
def deterministic() -> Iterator[None]:
    """PyTorch's deterministic algorithms for the block, where it has them (`warn_only`: an operation without one
    warns rather than stopping the run), then the setting as it was. On CPU the AI model's operations have them."""
    was, warn = torch.are_deterministic_algorithms_enabled(), torch.is_deterministic_algorithms_warn_only_enabled()
    torch.use_deterministic_algorithms(True, warn_only=True)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(was, warn_only=warn)
