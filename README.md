# AOI PoC Inspector

Desktop app for PCB/PCBA defect inspection: upload sample board photos, let the app train itself, then inspect
boards and compare any board side by side with the learned golden board.

* Architecture, navigation and requirement traceability: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* Screenshots: [docs/screenshots/](docs/screenshots/)
* Release notes, one file per build from 0.2.0 on: [docs/release-notes/](docs/release-notes/)
* Threat model, one page per product area, reviewed at every minor release: [docs/security/threat-model.md](docs/security/threat-model.md)

## Install (Windows 10/11)

```powershell
# Python 3.11 from python.org, then in this folder:
python -m venv .venv
.venv\Scripts\activate
# CPU station or laptop: the CPU build of PyTorch, then every other package; pip checks each file's hash
python -m pip install --require-hashes --no-deps -r requirements-torch-cpu.lock
python -m pip install --require-hashes -r requirements.lock
python -m pip check
# NVIDIA GPU station instead: the CUDA build of the same version
#   python -m pip install --require-hashes --no-deps -r requirements-torch-cuda.lock
#   python -m pip install --require-hashes -r requirements.lock
#   python -m pip check
python main.py
```

Linux: same steps with `source .venv/bin/activate` (macOS is not a target: PyTorch's index has no 2.14.1+cpu
build for it). Developers install `requirements-dev.lock` in place of `requirements.lock` and run `ruff check .`,
`ruff format --check .`, `mypy` and `pytest -q` before pushing. `requirements.txt` and `requirements-dev.txt` hold
the direct pins; after changing one, `python tools/make_lock.py` regenerates the five lock files with the hash of
every file pip may install, and CI fails while a lock file does not match its inputs. Qt comes from
`PySide6-Essentials`, not `PySide6` (whose Addons hold GPL-only modules such as Qt Charts; ADR 0003): in an
environment installed before that change, run `python -m pip uninstall -y PySide6 PySide6-Addons PySide6-Essentials`
first, then the steps above.

## Windows build without Python (internal test build)

GitHub Actions builds the app for Windows on every push to main
([.github/workflows/build.yml](.github/workflows/build.yml), ADR 0007): open the latest **Windows build** run under
**Actions**, download its `AOI-PoC-Inspector-…-unsigned` artifact, unzip it and start
`AOI-PoC-Inspector\AOI-PoC-Inspector.exe`. **Run workflow** on that page builds any branch. The build is not signed,
so Windows SmartScreen warns about an unknown publisher (**More info → Run anyway**), and it is **not a release**: no
customer or demo gets it (Engineering standard, "Signing"; Customers & Launch, "Demos"). `BUILD-INFO.txt` names its
commit, `THIRD_PARTY_NOTICES.txt` holds the third-party licenses and `SHA256SUMS.txt` the hash of every file. To
build it on a Windows PC:

```powershell
python -m pip install --require-hashes --no-deps -r requirements-torch-cpu.lock
python -m pip install --require-hashes -r requirements-build.lock    # the runtime packages plus PyInstaller
pyinstaller --noconfirm --clean installer\aoi.spec                 # -> dist\AOI-PoC-Inspector\
python tools\smoke_test_build.py dist\AOI-PoC-Inspector\AOI-PoC-Inspector.exe
```

## Try it in 5 minutes with synthetic boards

```powershell
python tools\make_synthetic_dataset.py --out sample_data
python main.py
```

1. Top bar → **+ New** → board model `TBOX-A1`.
2. **Training** → **Import Folder…** → `sample_data\train` (picks up `ok\` and `ng\`) → **Start Training**
   (about 1 minute on CPU at 60 epochs). Until the Datasets tab comes, Start Training stays off here: training reads
   only a frozen dataset version with a locked validation set, and no screen freezes or locks one yet. Select an OK
   image and press **Set Reference** instead: steps 4 and 5 then judge by the Golden board comparison alone, and
   step 3 waits for an AI model.
3. **AI Model Test** → **Select Test Folder…** → `sample_data\test` → **Run Test**.
4. **Inspection** → **Load Folder…** → `sample_data\test\ng` → **Start**.
5. Click **Compare with Golden ›** to see the board next to the golden template and the metrics that decided the verdict.

The first launch opens as `admin`; use **Switch User** to see the Operator view.

## With your own boards

* Put at least **70 good boards** (more is better; 50 are locked for validation and never trained on) of one board
  model, photographed with the same camera, distance and lighting, into `ok\`. Defective examples go into `ng\`
  (optionally `ng\solder_bridge\` etc. to label the type).
* Train, then tune thresholds on **Compare** (Try other thresholds, Engineer and Admin) or in **Recipe Editor**, and
  validate on a separate test folder.

## Checks

GitHub Actions runs these on every pull request ([.github/workflows/ci.yml](.github/workflows/ci.yml)), with the
tests on both Windows and Linux. Run them locally before pushing:

```powershell
python -m pip install --require-hashes --no-deps -r requirements-torch-cpu.lock
python -m pip install --require-hashes -r requirements-dev.lock
ruff check .            # lint
ruff format --check .   # formatting
mypy                    # strict types on aoi/core, aoi/data, aoi/hal and aoi/ui
pytest -q --cov         # tests; the line coverage of aoi/core and aoi/data must stay at 80 % or more
```

The tests draw their boards with `tools/make_synthetic_dataset.py` from a fixed seed, and the Qt pages are
tested offscreen (`QT_QPA_PLATFORM=offscreen`), so no display is needed. [`tests/regression/`](tests/regression/README.md)
holds the synthetic regression set: forty boards whose verdicts and metrics must not change unless a release
note says so. On every CI run `tools/trace_matrix.py` writes the trace matrix (each requirement in
`docs/requirements/` with the pull requests, or commits not merged yet, and tests that cite it and the last test
result) as the `trace-matrix` artifact; its G1 gate reports the rows still unproven and becomes blocking at the
release candidate (S59).

CI also runs three security scans: Bandit (a High finding fails the build), pip-audit (any known vulnerability in
a dependency fails it) and gitleaks (a secret in any commit fails it). The threat model in
[docs/security/threat-model.md](docs/security/threat-model.md) is reviewed against STRIDE at every minor release;
its review log says which build it was last checked for.

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
