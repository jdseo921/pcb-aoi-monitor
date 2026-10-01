# AOI PoC Inspector

Desktop app for PCB/PCBA defect inspection: upload sample board photos, let the app train itself, then inspect
boards and compare any board side by side with the learned golden board.

* Architecture, navigation and requirement traceability: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* Screenshots: [docs/screenshots/](docs/screenshots/)

## Install (Windows 10/11)

```powershell
# Python 3.10–3.12 from python.org, then in this folder:
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# NVIDIA GPU station: replace torch with the CUDA build from https://pytorch.org/get-started/locally/
python main.py
```

Linux/macOS: same steps with `source .venv/bin/activate`.

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

## Tests

```powershell
pip install pytest
pytest -q tests
```

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
tests/                  headless end-to-end test
```
