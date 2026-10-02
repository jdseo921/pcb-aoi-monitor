"""Source rules from the Engineering standard that a reviewer should never have to re-check by hand."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = (ROOT / "aoi", ROOT / "tools")
SOURCE_FILES = (ROOT / "main.py",)
# Loaders that run code from the file they read: never called in the app (Engineering, "Untrusted inputs").
CODE_RUNNING_LOADS = {("pickle", "load"), ("pickle", "loads"), ("jit", "load"), ("joblib", "load"), ("dill", "load")}


def _source_files() -> list[Path]:
    files = [p for d in SOURCE_DIRS for p in d.rglob("*.py")]
    files.extend(SOURCE_FILES)
    return sorted(files)


def unsafe_loads(source: str) -> list[str]:
    """Each call in `source` that could load code from a file, as "line: why": a torch.load without a literal
    weights_only=True (a ** argument could turn it off), a pickle, joblib, dill or TorchScript load, an np.load that
    allows pickles, and a loader imported by name (whose calls this check could not see)."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module in ("torch", "pickle", "numpy", "joblib", "dill"):
            found += [f"{node.lineno}: imports {a.name} from {node.module}" for a in node.names if "load" in a.name]
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        owner, name = node.func.value, node.func.attr
        owner_name = owner.id if isinstance(owner, ast.Name) else owner.attr if isinstance(owner, ast.Attribute) else ""
        keywords = {k.arg: k.value for k in node.keywords}
        if (owner_name, name) == ("torch", "load"):
            safe = keywords.get("weights_only")
            if not (isinstance(safe, ast.Constant) and safe.value is True) or None in keywords:
                found.append(f"{node.lineno}: torch.load without a literal weights_only=True")
        elif (owner_name, name) in CODE_RUNNING_LOADS:
            found.append(f"{node.lineno}: {owner_name}.{name} runs code from the file")
        elif owner_name in ("np", "numpy") and name == "load" and "allow_pickle" in keywords:
            allow = keywords["allow_pickle"]
            if not (isinstance(allow, ast.Constant) and allow.value is False):
                found.append(f"{node.lineno}: np.load may allow pickles")
    return found


def test_req_trn_014_no_unsafe_torch_load_in_source() -> None:
    """REQ-TRN-014: every torch.load in the app is weights-only, written as a literal, and nothing else loads code from
    a file (Engineering, "Untrusted inputs"); read from the syntax tree, so spacing or a ** argument cannot hide one."""
    offenders = {
        str(p.relative_to(ROOT)): found for p in _source_files() if (found := unsafe_loads(p.read_text("utf-8")))
    }
    assert offenders == {}, f"code-running loads in the app: {offenders}"
    assert unsafe_loads("torch.load(p, map_location='cpu', weights_only=True)") == []
    for unsafe in (
        "torch.load(p, weights_only = False)",
        'torch.load(p, **{"weights_only": False})',
        "torch.load(p, weights_only=True, **extra)",
        "torch.load(p)",
        "pickle.load(f)",
        "torch.jit.load(p)",
        "np.load(p, allow_pickle=True)",
        "from torch import load",
    ):
        assert unsafe_loads(unsafe), f"not caught: {unsafe}"
