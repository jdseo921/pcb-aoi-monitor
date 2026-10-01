# AOI PoC Inspector

Desktop app for PCB/PCBA defect inspection: upload sample board photos, let the app train itself, then inspect
boards and compare any board side by side with the learned golden board.

* Architecture, navigation and requirement traceability: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* Screenshots: [docs/screenshots/](docs/screenshots/)

## Install (Windows 10/11)

```powershell
# Python 3.11 from python.org, then in this folder:
python -m venv .venv
.venv\Scripts\activate
# CPU station or laptop: the CPU build of PyTorch, then every other package at its locked version
pip install "torch==2.14.1" --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.lock
# NVIDIA GPU station instead: the CUDA build of the same version, from https://pytorch.org/get-started/locally/
#   pip install "torch==2.14.1" --index-url https://download.pytorch.org/whl/cu130
#   pip install -r requirements.lock
python main.py
```

Linux/macOS: same steps with `source .venv/bin/activate`. Developers add `pip install -r requirements-dev.lock`
and run `ruff check .`, `ruff format --check .`, `mypy` and `pytest -q` before pushing. `requirements.txt` holds the
direct pins and `tools/make_lock.py` regenerates both lock files after a change.

## Try it in 5 minutes with synthetic boards

```powershell
python tools\make_synthetic_dataset.py --out sample_data
python main.py
```

1. Top bar → **+ New** → board model `TBOX-A1`.
2. **Training** → **Import Folder…** → `sample_data\train` (picks up `ok\` and `ng\`) → **Start Training**
   (about 1 minute on CPU at 60 epochs).
3. **AI Model Test** → **Select Test Folder…** → `sample_data\test` → **Run Test**.
4. **Inspection** → **Load Folder…** → `sample_data\test\ng` → **Start**.
5. Click **Compare with Golden ›** to see the board next to the golden template and the metrics that decided the verdict.

The first launch opens as `admin`; use **Switch User** to see the Operator view.

## With your own boards

* Put at least **20 good boards** (more is better) of one board model, photographed with the same camera, distance
  and lighting, into `ok\`. Defective examples go into `ng\` (optionally `ng\solder_bridge\` etc. to label the type).
* Train, then tune thresholds on **Compare** (what-if) or in **Recipe Editor**, and validate on a separate test folder.

## Checks

GitHub Actions runs these on every pull request ([.github/workflows/ci.yml](.github/workflows/ci.yml)), with the
tests on both Windows and Linux. Run them locally before pushing:

```powershell
pip install -r requirements-dev.txt
ruff check .            # lint
ruff format --check .   # formatting
mypy                    # strict types on aoi/core, aoi/data, aoi/hal and aoi/ui (Inspection and Compare: S22b, part 2)
pytest -q               # tests; add --cov for the line coverage of aoi/core and aoi/data
```

The tests draw their boards with `tools/make_synthetic_dataset.py` from a fixed seed, and the Qt pages are
tested offscreen (`QT_QPA_PLATFORM=offscreen`), so no display is needed. [`tests/regression/`](tests/regression/README.md)
holds the synthetic regression set: forty boards whose verdicts and metrics must not change unless a release
note says so. On every CI run `tools/trace_matrix.py` writes the trace matrix (each requirement in
`docs/requirements/` with the commits and tests that cite it and the last test result) as the `trace-matrix`
artifact; its G1 gate reports the rows still unproven and becomes blocking at the release candidate (S59).

CI also runs three security scans: Bandit (a High finding fails the build), pip-audit (any known vulnerability in
a dependency fails it) and gitleaks (a secret in any commit fails it).

## Layout

```
main.py                 entry point
aoi/config.py           workspace + settings
aoi/defects.py          PCBA defect classification table (taxonomy, severity, mandatory set)
aoi/data/db.py          SQLite schema + queries
aoi/core/               engine: imaging, anomaly (self-training), compare, inspector, recipe, services
aoi/hal/                camera / lighting / robot / MES interfaces (Stage 2–4 stubs)
aoi/ui/                 PySide6 shell, pages, widgets, theme
tools/                  synthetic dataset generator
tests/                  headless end-to-end test, engine-has-no-Qt rule
```
