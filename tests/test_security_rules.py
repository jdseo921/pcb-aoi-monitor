"""Source rules from the Engineering standard that a reviewer should never have to re-check by hand."""

from __future__ import annotations

import ast
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = (ROOT / "aoi", ROOT / "tools")
SOURCE_FILES = (ROOT / "main.py",)
# Loaders that run code from the file they read, by their full dotted name: never used in the app (Engineering,
# "Untrusted inputs"). torch.load is allowed only as a call with a literal weights_only=True, and a NumPy load only
# while its allow_pickle cannot be true (each NumPy loader with the position of that parameter).
TORCH_LOADS = ("torch.load", "torch.serialization.load")
NUMPY_LOADS = {"numpy.load": 2, "numpy.lib.format.read_array": 1}
CODE_RUNNING_LOADS = (
    "pickle.load", "pickle.loads", "pickle.Unpickler", "pickle._load", "pickle._loads", "pickle._Unpickler",
    "_pickle.load", "_pickle.loads", "_pickle.Unpickler", "shelve.open", "torch.jit.load", "joblib.load", "dill.load",
    "dill.loads", "dill.Unpickler",
)  # fmt: skip
LOADS = TORCH_LOADS + tuple(NUMPY_LOADS) + CODE_RUNNING_LOADS
LOADER_PREFIXES = frozenset(".".join(t.split(".")[:i]) for t in LOADS for i in range(1, t.count(".") + 2))


def _source_files() -> list[Path]:
    files = [p for d in SOURCE_DIRS for p in d.rglob("*.py")]
    files.extend(SOURCE_FILES)
    return sorted(files)


def unsafe_loads(source: str) -> list[str]:
    """Each place in `source` that could load code from a file, as "line: why". Every name is resolved through each of
    the module's imports (`import torch as T`, `from torch import serialization`) and name bindings (`T = torch`, a
    conditional or boolean value, `:=`, `with`, `a, b = torch, np`, a parameter's default value, an attribute such as
    `self.lib = torch` or a class attribute, by its own name whatever object holds it, and chains of them) in any scope
    or order, so a later binding never hides an earlier one (a fallback after a failed import, a local of the same
    name), and through getattr with a literal name; every loader a name may stand for is checked. An alias or a longer
    path meets the same rules (`anomaly.np.load` as `np.load`): a torch.load without a literal weights_only=True (a **
    argument could turn it off), a pickle, shelve, joblib, dill or TorchScript load, a NumPy load whose allow_pickle can
    be true, a loader imported by name, and a loader passed or stored without a call (where it is called cannot be
    checked). Only the loaders in LOADS are known: one reached through importlib, a container, a loop variable, a call
    result, or a module passed in as an argument (`r(torch, p)` calling `m.load(p)`) is not, and code review covers
    those."""
    tree = ast.parse(source)
    aliases: dict[str, set[str]] = {"np": {"numpy"}}  # each name: every other dotted name it may stand for
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]  # `import torch.serialization` binds torch
                aliases.setdefault(a.asname or top, set()).add(a.name if a.asname else top)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                aliases.setdefault(a.asname or a.name, set()).add(f"{node.module}.{a.name}")

    def dotted(node: ast.AST) -> set[str]:
        """Every full dotted name `node` may stand for, its own spelling included; empty when it is not a name."""
        if isinstance(node, ast.Name):
            return {node.id} | aliases.get(node.id, set())
        if isinstance(node, ast.Attribute):  # and what the attribute's own name is bound to (`self.lib`, `C.lib`)
            return {f"{owner}.{node.attr}" for owner in dotted(node.value)} | aliases.get(node.attr, set())
        if isinstance(node, ast.Call) and "getattr" in dotted(node.func) and len(node.args) > 1:
            name = node.args[1]
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                return {f"{owner}.{name.value}" for owner in dotted(node.args[0])}
        if isinstance(node, ast.IfExp):
            return dotted(node.body) | dotted(node.orelse)
        if isinstance(node, ast.BoolOp):
            return set().union(*map(dotted, node.values))
        if isinstance(node, ast.NamedExpr):
            return dotted(node.value)
        return set()

    def may_load(name: str) -> bool:
        """Whether `name`, or a dotted tail of it, is the start of a loader's name: only those are followed, so a name
        bound to anything else (`node = node.body` in a tree walk) never grows the alias sets, and a name longer than
        any path to a loader (`x = x.torch` again and again) is not followed."""
        parts = name.split(".")
        return len(parts) <= 8 and any(".".join(parts[i:]) in LOADER_PREFIXES for i in range(len(parts)))

    pairs: list[tuple[ast.AST, ast.AST]] = []  # (target, value) of every binding (#168 review)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            pairs += [(target, node.value) for target in node.targets]
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            pairs.append((node.target, node.value))
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            pairs.append((node.optional_vars, node.context_expr))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):  # `def f(lib=torch)`
            a, given = node.args, node.args.posonlyargs + node.args.args
            defaults = list(zip(given[len(given) - len(a.defaults) :], a.defaults, strict=True))
            defaults += [(p, d) for p, d in zip(a.kwonlyargs, a.kw_defaults, strict=True) if d is not None]
            pairs += [(ast.Name(p.arg), d) for p, d in defaults]
    bound: list[tuple[str, ast.AST]] = []
    for target, value in pairs:
        if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)):
            bound += [(t.id, v) for t, v in zip(target.elts, value.elts, strict=False) if isinstance(t, ast.Name)]
        elif isinstance(target, ast.Name):
            bound.append((target.id, value))
        elif isinstance(target, ast.Attribute):  # `self.lib = torch`: by the attribute's name, whatever holds it
            bound.append((target.attr, value))
    for _ in range(3):  # `a = torch; b = a` takes a second round; three cover any chain a reviewer would let pass
        for name, value in bound:
            aliases.setdefault(name, set()).update(owner for owner in dotted(value) - {name} if may_load(owner))

    def loader(name: str) -> str | None:
        return next((t for t in LOADS if name == t or name.endswith(f".{t}")), None)

    found = []
    calls = {id(node.func): node for node in ast.walk(tree) if isinstance(node, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found += [
                f"{node.lineno}: imports {t} by name" for a in node.names if (t := loader(f"{node.module}.{a.name}"))
            ]
        if not isinstance(node, (ast.Name, ast.Attribute, ast.Call)):
            continue
        for what in sorted({t for name in dotted(node) if (t := loader(name))}):  # every loader it may stand for
            found += [f"{node.lineno}: {why}" for why in [unsafe_call(what, calls.get(id(node)))] if why]
    return found


def unsafe_call(what: str, call: ast.Call | None) -> str | None:
    """Why a use of the loader `what` could load code (`call` is the call it makes, None when it is not called), or
    None when it cannot."""
    if call is None:
        return f"{what} is used without a call that can be checked"
    keywords = {k.arg: k.value for k in call.keywords}
    if what in TORCH_LOADS:
        safe = keywords.get("weights_only")
        if not (isinstance(safe, ast.Constant) and safe.value is True) or None in keywords:
            return f"{what} without a literal weights_only=True"
        return None
    if what in NUMPY_LOADS:  # allow_pickle by keyword, or by position: an argument there or *args can set it too
        at = NUMPY_LOADS[what]
        allow = keywords.get("allow_pickle", call.args[at] if len(call.args) > at else ast.Constant(False))
        spread = None in keywords or any(isinstance(a, ast.Starred) for a in call.args)
        if spread or not (isinstance(allow, ast.Constant) and allow.value is False):
            return f"{what} may allow pickles"
        return None
    return f"{what} runs code from the file"


def test_req_trn_014_no_unsafe_torch_load_in_source() -> None:
    """REQ-TRN-014: every torch.load in the app is weights-only, written as a literal, and nothing else loads code from
    a file (Engineering, "Untrusted inputs"); read from the syntax tree with the imports resolved, so spacing, a **
    argument, an import alias or a longer path to the loader cannot hide one."""
    offenders = {
        str(p.relative_to(ROOT)): found for p in _source_files() if (found := unsafe_loads(p.read_text("utf-8")))
    }
    assert offenders == {}, f"code-running loads in the app: {offenders}"
    for safe in (  # the controls: the rule is not so broad that a safe load or another library's load fails it
        "torch.load(p, map_location='cpu', weights_only=True)",
        "import torch as T\nT.load(p, weights_only=True)",
        "import torch.serialization\ntorch.serialization.load(p, weights_only=True)",
        "np.load(p)",
        "import numpy\nnumpy.load(p, None, False)\nnp.load(p, allow_pickle=False)",
        "json.load(f)\nAnomalyModel.load(p)\nload = settings.load",
        "T = torch\nT.load(p, weights_only=True)",
        "np.lib.format.read_array(f)\nx = x.y\ny = x.z\nx.load(p)",
    ):
        assert unsafe_loads(safe) == [], f"a safe load caught: {safe}"
    for unsafe in (
        "torch.load(p, weights_only = False)",
        'torch.load(p, **{"weights_only": False})',
        "torch.load(p, weights_only=True, **extra)",
        "torch.load(p)",
        "pickle.load(f)",
        "torch.jit.load(p)",
        "np.load(p, allow_pickle=True)",
        "from torch import load",
        # an alias or another path to the same loader (#168)
        "import torch as T\nT.load(p, weights_only=False)",
        "torch.serialization.load(p)",
        "import torch.serialization as ser\nser.load(p, weights_only=False)",
        "from torch import serialization\nserialization.load(p)",
        "from torch.serialization import load as read",
        "getattr(torch, 'load')(p)",
        "load = torch.load\nload(p, weights_only=True)",
        "functools.partial(torch.load, weights_only=False)",
        "pickle.Unpickler(f).load()",
        "import pickle as pk\npk.loads(b)",
        "from pickle import Unpickler",
        "import joblib as jl\njl.load(p)",
        "import dill\ndill.loads(b)",
        "from torch import jit\njit.load(p)",
        "np.load(p, **opts)",
        "import numpy as N\nN.load(p, allow_pickle=flag)",
        "numpy.load(p, None, True)",
        "np.load(p, *args)",
        "T = torch\nT.load(p)",  # a module bound by assignment, as by an import
        "ser: object = torch.serialization\nser.load(p, weights_only=False)",
        "a = torch\nb = a\nb.load(p)",
        "try:\n    import torch\nexcept ImportError:\n    torch = _stub\ntorch.load(p, weights_only=False)",
        "import pickle\ndef f(cache):\n    pickle = cache\npickle.loads(b)",  # a later or local binding hides none
        "import _pickle\n_pickle.loads(b)",
        "pickle._Unpickler(f).load()",
        "shelve.open(p)",
        "np.lib.format.read_array(f, True)",
        "import numpy\nnumpy.lib.format.read_array(f, allow_pickle=flag)",
        # every loader a name may stand for is checked, and every way of binding it (#168 second review)
        "try:\n    import torch as be\nexcept ImportError:\n    import numpy as be\nbe.load(p, weights_only=False)",
        "m = np\nm = torch.jit\nm.load(p)",
        "xp = torch if gpu else np\nxp.load(p, weights_only=False)",
        "T = torch or None\nT.load(p)",
        "if (T := torch):\n    T.load(p)",
        "T, U = torch, 1\nT.load(p)",
        "with torch as T:\n    T.load(p)",
        # a parameter's default, an attribute by its name, a longer path through a module's alias (#168 third review)
        "def read(path, lib=torch):\n    return lib.load(path, weights_only=False)",
        "f = lambda b, m=pickle: m.loads(b)",
        "def f(b, *, m=pickle):\n    return m.loads(b)",
        "async def f(b, /, m=pickle):\n    return m.loads(b)",
        "class R:\n    def __init__(self):\n        self.lib = torch\n    def read(self, p):\n        self.lib.load(p)",
        "class C:\n    lib = pickle\nC.lib.loads(b)",
        "from aoi.core import anomaly\nanomaly.np.load(p, allow_pickle=True)",
    ):
        assert unsafe_loads(unsafe), f"not caught: {unsafe}"
    walk = "".join(f"def f{i}(node):\n    node = node.a{i}\n    a, b = b.x{i}, a.y{i}\n" for i in range(12))
    walk += "x = x.torch if c else x.numpy\n" * 8  # a name rebound to loader-module names never grows without end
    took = time.perf_counter()
    assert unsafe_loads(walk) == [] and time.perf_counter() - took < 1, "a tree walk's rebindings must stay cheap"
