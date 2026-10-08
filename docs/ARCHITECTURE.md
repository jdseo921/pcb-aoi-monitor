# AOI PoC Inspector: Architecture & Navigation (v0.1 draft)

Desktop application for PCB/PCBA defect inspection, built against three source documents:

| Ref | Document |
|---|---|
| **GUI** | AOI PoC Software GUI – Concept & Functional Specification (Extended) |
| **RM** | AOI PoC Software – Development Roadmap & Commercialization Plan |
| **DCT** | PCBA Defect Classification Table v1.0 (27 Apr 2026) |

This draft covers **Stage 1** (image upload, AI learning, customer validation) end to end, and lays out the
interfaces that Stages 2–4 (cameras, robot, MES/ERP) plug into without changing the UI or the pipeline.

---

## 1. Technology choices

| Concern | Choice | Why |
|---|---|---|
| Language / UI | **Python 3.11 / PySide6 (Qt 6)** | GUI §6 allows ".NET / C# or Python (PyQt / Tkinter)". PySide6 is the official, LGPL-licensed Qt binding (PyQt is GPL/commercial), which matters for selling 50–200+ licenses (RM §3–4). Qt also gives a native Windows 10/11 look, high-DPI, and 1920×1080 layouts. |
| AI | **PyTorch** | GUI §6 names TensorFlow / PyTorch; Stage 1 deliverable is a `.pt` or `.h5` model. CUDA used automatically when present. |
| Vision | **OpenCV** | Registration, image differencing, morphology, SSIM (scikit-image's formula with OpenCV box filters since S08). |
| Storage | **SQLite** (one file per workspace) | GUI §6 "Local SQLite or PostgreSQL". All SQL is in one module so PostgreSQL can be swapped in for multi-station / MES use. |
| Reports | CSV, PNG overlays, PDF (Qt `QPdfWriter`) | GUI §6 export formats. |
| Packaging (next) | PyInstaller → Windows installer | Single-folder deploy for PoC stations. |

---

## 2. Layered architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ UI layer  (aoi/ui)                     PySide6                               │
│  MainWindow: header (board model, user/role) · sidebar nav · page stack      │
│  Pages: Home · Inspection · Compare · Training · AI Model Test ·             │
│         Recipe Editor · 3D Profile · Logs & Export · Settings                │
│  Widgets: ImageView (zoom/pan, overlays, ROI drawing, linked views)          │
│  Workers: QThreadPool runners so training / batch tests never freeze the UI  │
├──────────────────────────────────────────────────────────────────────────────┤
│ Application services  (aoi/core/services.py → AppContext)                    │
│  import_samples · train · load_model · recipe/save_recipe · inspector ·      │
│  inspect_file · log_result · batch_test · export_csv                          │
├──────────────────────────────────────────────────────────────────────────────┤
│ Inspection engine  (aoi/core)                                                │
│  imaging.py   I/O (Unicode paths), ORB+RANSAC registration, heatmaps         │
│  anomaly.py   self-training conv. autoencoder + calibration (.pt)            │
│  compare.py   golden-sample diff (shift-tolerant Lab ΔE), SSIM, blobs        │
│  inspector.py pipeline → Checks (decision variables) + Defects + verdict     │
│  recipe.py    ROIs + thresholds per board model                              │
│  defects.py   DCT taxonomy, severities, mandatory AOI set                    │
├──────────────────────────────────────────────────────────────────────────────┤
│ Data  (aoi/data/db.py)  SQLite: samples · models · recipes · inspections ·   │
│                         defects · test_runs · alarms · users · board_models  │
├──────────────────────────────────────────────────────────────────────────────┤
│ HAL  (aoi/hal)  Camera · LightingController · RobotController · MesClient    │
│   Stage 1: FolderCamera (images)   Stage 2–4: GigE/USB3, serial, RS-485, OPC │
└──────────────────────────────────────────────────────────────────────────────┘
```

Rules: pages call **only** `AppContext`; the engine has **no Qt imports**, so the same code runs headless
(tests, a future CLI, the Stage 3 robot cycle, or a Stage 4 MES service).

### Workspace on disk

```
AOI_Workspace/                 (default ~/AOI_Workspace, set in Settings or AOI_WORKSPACE env var)
  aoi.sqlite                   database
  settings.json
  images/<board>/<OK|NG>/      uploaded training samples (copied in, so source folders can move)
  models/<board>/<board>_vX.Y.pt            trained model + calibration
  models/<board>/<board>_vX.Y_golden.png    learned golden template
  results/<date>/*.png         auto-saved overlay per inspected board
  exports/                     CSV / PDF / overlay exports
```

---

## 3. How the app "trains itself" (Stage 1 AI)

Customers usually have many good boards and very few defective ones, and most of the 33 DCT defect types will
have no examples at PoC start. So the default model learns **what a good board looks like** and flags deviations,
instead of needing labelled examples of every defect.

```
Upload OK images (+ optional NG)                         Training page
        │
        ▼
1. Register every image onto one reference board (ORB features + RANSAC homography)
2. Golden template  = per-pixel median of the aligned OK boards       → *_golden.png
3. Autoencoder      = learns to reconstruct OK boards (lighting jitter augmentation)
4. Normal variation = per-pixel mean/std of reconstruction error on OK boards
5. Calibration      = threshold from held-out OK scores (mean+3σ, ≥1.05×max OK);
                      if labelled NG exist and separate cleanly → midpoint between OK and NG
6. Register version vX.Y in the model registry, activate it                  → *.pt
```

Re-training after more uploads creates a new version; older versions stay selectable (model version control, GUI §6).

**Next AI step (not in this draft):** once enough labelled NG crops exist per type, add a small supervised
classifier that names the defect (Solder Bridge, Tombstone, …) for each flagged region. Today a region is named by
the ROI it falls in (Presence → Missing Component, Polarity → Polarity Error, Solder Bridge → Solder Bridge,
Height → Pin Height Error) or reported as "Anomaly".

---

## 4. Decision logic: the variables that decide OK / WARN / NG

Every inspection produces a list of **Checks**. The Compare page shows exactly this list, so the operator sees why
a board failed. All thresholds live in the recipe and can be tried out live on the Compare page.

| Check | Source | Rule (default) | Meaning |
|---|---|---|---|
| SSIM similarity | Compare | NG if < 0.80 | Whole-board structural similarity to the golden template (1 = identical) |
| Changed area % | Compare | NG if ≥ 0.50 % | Share of pixels whose colour differs by ≥ *Pixel difference* (45/255) after a ±2 px tolerance |
| Difference regions | Compare | NG if > 0 | Number of difference blobs ≥ *Min defect area* (40 px) |
| Alignment inliers | Compare | info; WARN if < 12 | Confidence that the board was registered correctly |
| AI anomaly score | AI | NG if ≥ model threshold | 99.9th percentile of the anomaly map (σ above normal variation) |
| ROI *name* [type] | ROI | NG if ≥ ROI AI Score | Strongest anomaly inside the ROI, as a multiple of the model threshold |
| Inspection time | System | spec < 1 s | GUI §11 acceptance criterion |

Verdict: **NG** if any check is NG; else **WARN** if any check is within the warning band (default 80 % of a
threshold) or a non-minor defect region exists; else **OK**. Colours follow GUI §4.1: green OK, red NG, yellow WARN.

---

## 5. Navigation

```
┌──────────── Header ───────────────────────────────────────────────────────────┐
│ AOI PoC Inspector │ Board model [TBOX-A1 ▾] [+ New] │        user · role [Switch User] │
├────────────┬──────────────────────────────────────────────────────────────────┤
│ Home       │                                                                  │
│ PRODUCTION │                                                                  │
│  Inspection│                  active page                                     │
│  Compare   │                                                                  │
│ ENGINEERING│                                                                  │
│  Training  │                                                                  │
│  AI Model Test                                                                │
│  Recipe Editor                                                                │
│  3D Profile│                                                                  │
│ DATA       │                                                                  │
│  Logs & Export                                                                │
│ SYSTEM     │                                                                  │
│  Settings  │                                                                  │
└────────────┴──────────────── status bar ──────────────────────────────────────┘
```

* **Board model** is chosen once in the header; every page follows it (dataset, model, recipe, golden image).
* **Cross-links:** Inspection → "Compare with Golden ›" opens Compare on the current board; Home step cards open
  the page for each step; AI Model Test row preview feeds "Use Last Inspected" on Compare.
* **Roles** (GUI §8). Disabled entries show a tooltip naming the required role.

| Page | Operator | Engineer | Admin |
|---|:-:|:-:|:-:|
| Home, Inspection, Compare, Logs (view) | ✓ | ✓ | ✓ |
| Logs export / archive | | ✓ | ✓ |
| Training, AI Model Test, Recipe Editor, 3D Profile | | ✓ | ✓ |
| Compare → Save to Recipe | | ✓ | ✓ |
| Settings (users, workspace, device, hardware) | | | ✓ |

User switching is a local picker for the PoC; Stage 4 replaces it with MES authentication (`MesClient.authenticate`).

### Pages

| Page | Main functions | Spec |
|---|---|---|
| **Home** | Six step cards (Upload → Self-train → Tune recipe → Validate → Inspect → Export) with live status for the selected board model | RM Stage 1 flow |
| **Inspection** | Load images/folder (Stage 1 "camera"); Top/Side/Bottom view tag; **Start / Stop / Next Board / Save Result**; image with defect boxes coloured by severity; defect list **No, Type, Score, Side, X, Y** (click to zoom); big OK/NG/WARN banner; timestamped alarm log; auto-save each board | GUI §4.1 |
| **Compare** (optional) | Golden reference and test board **side by side** with **synchronised zoom/pan**; views: side-by-side, difference heatmap, AI anomaly heatmap, boxes only; **metrics table** (check, source, value, threshold, rule, result) with failing rows highlighted; plain-language "why" explanation; **what-if thresholds** with Re-evaluate and Save to Recipe; pick any reference image instead of the golden template | Jay's request |
| **Training** | **+OK / +NG upload** (NG labelled with DCT category, type and view), import folder with `ok/` `ng/` sub-folders; dataset table with relabel / set reference / remove; preview; epochs, input size, device; Start/Stop with progress and log; **model version registry** with activate and export `.pt` | GUI §4.3, Stage 1, §6 model version control |
| **AI Model Test** | Select labelled folder; Run Test / Run Test Again; **Accuracy, Precision, Recall, False Call Rate** tiles; confusion counts; results table **Image, GT, AI Result, Score, Pass/Fail** with failures in red; preview; **Export CSV / Export Report (PDF)**; runs stored in DB | GUI §4.3 |
| **Recipe Editor** | Draw ROIs on the golden board (zoom/pan); ROI types **Presence, Polarity, Solder Bridge, Height, Anomaly**; parameters **AI Score, Height Min/Max, Volume Min/Max**; yellow = selected, green = saved; global thresholds; **mandatory AOI set** checklist (DCT §4) marking checks that need Stage 2 3D/side cameras; Test Run; Save Recipe → revision with user + timestamp | GUI §4.2, DCT §4 |
| **3D Profile** | Layout placeholder (height map, defect details, Accept/Reject) until Stage 2 3D data exists | GUI §4.5 |
| **Logs & Export** | Filter by date, model, operator; sortable table; overlay preview; Export CSV / overlay images with confirmation; auto-archive > 30 days (on start and on demand) | GUI §4.4 |
| **Settings** | Workspace, AI device (auto/CPU/CUDA), defaults, retention, language (en/ko placeholder for 2H 2027 localisation); users & roles; hardware interface status per stage | GUI §6, §8, RM 2H 2027 |

---

## 6. Database schema (SQLite)

| Table | Key columns |
|---|---|
| `board_models` | name, reference_image (golden) |
| `samples` | board_model, path, label OK/NG, defect_type (DCT), side |
| `models` | board_model, version, path (.pt), metrics JSON (thresholds, scores, timing), active |
| `recipes` | board_model, revision, body JSON, user, created_at |
| `inspections` | time, board_model, model_version, recipe_rev, image/overlay paths, result, score, metrics JSON, operator, archived |
| `defects` | inspection_id, no, type, score, side, x, y, w, h |
| `test_runs` | time, board_model, model_version, folder, metrics JSON, results JSON |
| `alarms`, `users` | — |

The schema is created and changed only by the numbered migrations in `aoi/data/migrations/`, which
`aoi/data/migrate.py` applies at start-up and records in `schema_version` with a checksum (ADR 0004). The
connection runs in write-ahead-log mode with a full sync on every commit, and a v0.1 workspace (no
`schema_version` table) is refused rather than upgraded.
Records that can leave the station (`users`, `samples`, `models`, `recipes`, `inspections`) carry a `uuid`
beside their integer key; every stored time is ISO 8601 UTC with an offset and is shown in local time
(`aoi/data/times.py`); image, overlay and model paths inside the workspace are stored relative to it and resolved
by `aoi/data/paths.py`, so a workspace folder can move (REQ-SET-017, REQ-SET-001).
Every file the app writes (images, overlays, AI models, exports, settings) goes through `aoi/data/atomic.py`:
a temporary name in the same folder, flush and fsync, then an atomic rename, and an inspection's row and defects
commit in one transaction, so a crash leaves a whole result or none (REQ-INSP-008).

`inspections` already carries everything Stage 4 uploads (lot/model/result/timestamp + images); a `lot_id` column is
the only addition expected.

---

## 7. Requirement traceability (Stage 1)

The requirement register is `docs/requirements/stage1.md`; `tools/trace_matrix.py` generates the trace matrix
from it on every CI run (the `trace-matrix` artifact). The table below is the v0.1 draft's informal check against
the source specifications and stays as history.

| Requirement | Where | Status |
|---|---|---|
| Image upload PNG/JPG | Training, Inspection | Done (also BMP/TIFF) |
| Offline AI inference engine | `core/anomaly.py`, `core/inspector.py` | Done |
| Defect overlay + confidence scores | Inspection, Compare, overlays | Done |
| Batch test tool | AI Model Test | Done |
| Export annotated images + CSV | Logs & Export, auto-saved overlays | Done |
| Model deliverable `.pt` | Training → Export Model | Done |
| Accuracy / Precision / Recall / False Call Rate | AI Model Test | Done |
| Results stored in local DB | `test_runs`, `inspections` | Done |
| Recipe ROIs, types, parameters, revisions | Recipe Editor | Done (height/volume stored for Stage 2) |
| Roles Operator / Engineer / Admin | header + nav gating | Done (local users) |
| < 1 s per image | measured ~0.4–0.6 s on CPU, 640×480 | Met on test data |
| Auto-archive logs > 30 days | `Database.archive_old` | Done |
| Defect type naming per DCT | ROI mapping; NG labels | Partial: supervised classifier is the next AI step |
| PDF report | AI Model Test → Export Report | Done (basic) |
| 8-hour stability, mock-up match | — | To verify with customer images |

## 8. Stages 2–4 hooks

| Stage | Plug-in point | Work |
|---|---|---|
| 2 Cameras & lighting | `hal.Camera` (`GigEVisionCamera` stub), `hal.LightingController` | GenICam/vendor SDK driver; live feed into the Inspection view (already a generic image view); per-view (Top/Side/Bottom) recipes; 3D height maps fill the 3D Profile page and the Height/Volume ROI parameters |
| 3 Robot | `hal.RobotController` (load, move_to_inspect, unload, emergency_stop) | Cycle runner: Load → grab views → `Inspector.inspect` → Unload(result); trigger sync; e-stop surfaces in the alarm log |
| 4 MES/ERP | `hal.MesClient` (upload_result, authenticate) | REST/OPC UA client fed from `log_result`; MES login replaces local user switch; optional PostgreSQL backend |

## 9. Known limits of this draft

* Validated only on **synthetic** boards (`tools/make_synthetic_dataset.py`), where it scores 100 % on a 31-image
  test set. Real T-Box images (reflections, connectors, shield cans) will need threshold tuning and probably a
  higher input size or tiled inference for fine solder defects.
* Defect **type** is inferred from ROIs, not classified by the model yet.
* Side-view and 3D checks in the mandatory set (Shield Can Gap, Pin Height, Coplanarity, Solder Volume) need Stage 2
  hardware.
* No Windows installer yet; runs from source.
