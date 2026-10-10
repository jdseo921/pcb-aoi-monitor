"""The Windows build's software bill of materials, as CycloneDX 1.5 JSON (REQ-SET-012; Engineering standard, "Scans
and SBOM": each release publishes a CycloneDX SBOM listing every library and AI model file with its version).

installer/aoi.spec calls `bom` once PyInstaller has collected the app, with the packages
tools/third_party_notices.py's `bundled_packages` found in it, and writes the result as `sbom.cdx.json` beside
THIRD_PARTY_NOTICES.txt, so it travels in the build's artifact and in the installer. The bill names:

- the app, as its subject, with the version in aoi/config.py;
- each bundled Python package: its name, version, package URL (`pkg:pypi/<name>@<version>`) and the license its
  metadata declares, an SPDX expression when the package gives one;
- Python, whose runtime and standard library every build carries, and Inno Setup, whose setup program and
  uninstaller the installer carries;
- every AI model file in the built folder (`*.pt`, the demo workspace's), with its SHA-256 and, from the AI model card
  beside it, its board model, version and dataset version.

It reads only what is installed and what was bundled: no network, no tool beyond the standard library.
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import json
import platform
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.third_party_notices import INNO_SETUP_VERSION, declared, norm

SPEC_VERSION = "1.5"
FILE_NAME = "sbom.cdx.json"


def sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def package(dist: md.Distribution) -> dict[str, Any]:
    """A bundled Python package as a CycloneDX library: its license is the SPDX expression its metadata gives, else
    the name it declares (tools/third_party_notices.py, `declared`), which tools/check_licenses.py checked in CI."""
    name, version = str(dist.metadata["Name"]), dist.version
    purl = f"pkg:pypi/{norm(name)}@{version}"
    expression = dist.metadata["License-Expression"]
    licenses = [{"expression": str(expression)}] if expression else [{"license": {"name": declared(dist)}}]
    return {"type": "library", "bom-ref": purl, "name": name, "version": version, "purl": purl, "licenses": licenses}


def ai_model(path: Path, folder: Path) -> dict[str, Any]:
    """An AI model file the build ships, by its path in the built folder and its SHA-256; its version, board model
    and dataset version come from its AI model card (`<version>.card.json`, aoi/core/model_card.py) beside it."""
    name = path.relative_to(folder).as_posix()
    out: dict[str, Any] = {
        "type": "machine-learning-model",
        "bom-ref": f"file:{name}",
        "name": name,
        "hashes": [{"alg": "SHA-256", "content": sha256(path)}],
    }
    try:
        identity = json.loads(path.with_suffix(".card.json").read_text(encoding="utf-8"))["identity"]
    except (OSError, ValueError, KeyError, TypeError):
        return out
    out["version"] = str(identity.get("version"))
    out["properties"] = [
        {"name": f"aoi:{key}", "value": str(identity[key])}
        for key in ("board_model", "dataset", "customer", "uuid")
        if identity.get(key) is not None
    ]
    return out


def bom(
    packages: Iterable[str],
    app_name: str,
    app_version: str,
    folder: Path,
    *,
    dists: Iterable[md.Distribution] | None = None,
    serial: uuid.UUID | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The bill of the build in `folder` that bundles `packages` (normalised names); stops when one is not installed,
    since the bill cannot vouch for a package it cannot see."""
    by_name = {norm(str(d.metadata["Name"])): d for d in (md.distributions() if dists is None else dists)}
    wanted = sorted(set(packages))
    missing = [name for name in wanted if name not in by_name]
    if missing:
        raise SystemExit(f"The bill of materials names packages that are not installed: {', '.join(missing)}")
    components = [package(by_name[name]) for name in wanted]
    python = platform.python_version()
    components.append(
        {
            "type": "application",
            "bom-ref": f"pkg:generic/python@{python}",
            "name": "Python",
            "version": python,
            "purl": f"pkg:generic/python@{python}",
            "licenses": [{"license": {"id": "PSF-2.0"}}],
            "description": "The runtime and standard library, with the libraries it bundles",
        }
    )
    components.append(
        {
            "type": "application",
            "bom-ref": f"pkg:generic/inno-setup@{INNO_SETUP_VERSION}",
            "name": "Inno Setup",
            "version": INNO_SETUP_VERSION,
            "purl": f"pkg:generic/inno-setup@{INNO_SETUP_VERSION}",
            "licenses": [{"license": {"name": "Inno Setup License"}}],
            "description": "The installer's setup program and its uninstaller; not part of the app",
        }
    )
    components += [ai_model(path, folder) for path in sorted(folder.rglob("*.pt"))]
    when = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "serialNumber": f"urn:uuid:{serial or uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": when,
            "tools": {"components": [{"type": "application", "name": "tools/sbom.py"}]},
            "component": {"type": "application", "bom-ref": "app", "name": app_name, "version": app_version},
        },
        "components": components,
    }
