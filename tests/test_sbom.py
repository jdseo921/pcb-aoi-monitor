"""The Windows build's bill of materials (REQ-SET-012; Engineering standard, "Scans and SBOM").

tools/sbom.py is what installer/aoi.spec runs once PyInstaller has collected the app; these tests give it packages
installed in a temporary folder and a built folder holding an AI model file with its card.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.test_third_party_notices import install, installed
from tools import sbom
from tools.third_party_notices import INNO_SETUP_VERSION

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def site(tmp_path: Path) -> Path:
    site = tmp_path / "site-packages"
    install(site, "Shipped_Pkg", "1.0", {"licenses/LICENSE": "text"}, declared="BSD-3-Clause license text")
    install(site, "spdx", "2.1", {"LICENSE": "text"})
    meta = site / "spdx-2.1.dist-info" / "METADATA"
    meta.write_text(meta.read_text(encoding="utf-8") + "License-Expression: MIT OR Apache-2.0\n", encoding="utf-8")
    return site


def built(tmp_path: Path) -> Path:
    """A built folder with the demo workspace's AI model file and its card, as installer/aoi.spec collects it."""
    folder = tmp_path / "dist" / "AOI-PoC-Inspector"
    models = folder / "_internal" / "demo-bundle" / "workspace" / "models" / "DEMO-TBOX-A1"
    models.mkdir(parents=True)
    (models / "DEMO-TBOX-A1_v1.0.pt").write_bytes(b"weights")
    card = {"identity": {"board_model": "DEMO-TBOX-A1", "version": "v1.0", "dataset": "DS-DEMOTBOXA1-R1-TOP-v1"}}
    (models / "DEMO-TBOX-A1_v1.0.card.json").write_text(json.dumps(card), encoding="utf-8")
    (folder / "_internal" / "other.pt").write_bytes(b"no card")
    return folder


def test_req_set_012_the_bill_names_every_bundled_package_python_inno_setup_and_ai_model_file(
    site: Path, tmp_path: Path
) -> None:
    folder = built(tmp_path)
    serial, now = uuid.UUID(int=7), datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
    packages = {"shipped-pkg", "spdx"}
    bill = sbom.bom(packages, "AOI PoC Inspector", "0.3.0", folder, dists=installed(site), serial=serial, now=now)
    assert (bill["bomFormat"], bill["specVersion"], bill["version"]) == ("CycloneDX", "1.5", 1)
    assert bill["serialNumber"] == f"urn:uuid:{serial}"
    assert bill["metadata"]["timestamp"] == "2026-10-10T09:00:00+00:00"
    assert bill["metadata"]["component"] == {
        "type": "application",
        "bom-ref": "app",
        "name": "AOI PoC Inspector",
        "version": "0.3.0",
    }
    by_name = {c["name"]: c for c in bill["components"]}
    assert by_name["Shipped_Pkg"]["purl"] == "pkg:pypi/shipped-pkg@1.0"
    assert by_name["Shipped_Pkg"]["licenses"] == [{"license": {"name": "BSD-3-Clause license text"}}]
    assert by_name["spdx"]["licenses"] == [{"expression": "MIT OR Apache-2.0"}]  # the SPDX expression, as declared
    assert by_name["Python"]["licenses"] == [{"license": {"id": "PSF-2.0"}}]
    assert by_name["Inno Setup"]["version"] == INNO_SETUP_VERSION
    model = by_name["_internal/demo-bundle/workspace/models/DEMO-TBOX-A1/DEMO-TBOX-A1_v1.0.pt"]
    assert model["type"] == "machine-learning-model" and model["version"] == "v1.0"
    assert model["hashes"] == [{"alg": "SHA-256", "content": sbom.sha256(folder.joinpath(model["name"]))}]
    assert {"name": "aoi:dataset", "value": "DS-DEMOTBOXA1-R1-TOP-v1"} in model["properties"]
    assert "version" not in by_name["_internal/other.pt"]  # no card beside it: its hash only
    refs = [c["bom-ref"] for c in bill["components"]]
    assert len(refs) == len(set(refs)) == 6
    json.dumps(bill)  # plain JSON values only


def test_req_set_012_the_bill_stops_on_a_package_that_is_not_installed(site: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="not installed: missing"):
        sbom.bom({"spdx", "missing"}, "AOI PoC Inspector", "0.3.0", built(tmp_path), dists=installed(site))


def test_req_set_012_the_build_writes_the_bill_beside_the_notices_and_the_installer_check_wants_it() -> None:
    spec = (ROOT / "installer" / "aoi.spec").read_text(encoding="utf-8")
    assert 'bill = sbom.bom(used | {"pyinstaller"}, APP_NAME, APP_VERSION, Path(DISTPATH) / NAME)' in spec
    assert "(Path(DISTPATH) / NAME / sbom.FILE_NAME).write_text(json.dumps(bill, indent=1)" in spec
    assert sbom.FILE_NAME in (ROOT / "tools" / "check_installer.py").read_text(encoding="utf-8")
