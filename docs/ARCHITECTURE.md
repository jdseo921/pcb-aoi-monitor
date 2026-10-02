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
│  Workers: Worker wraps a core Job; its callbacks arrive as signals on the UI │
├──────────────────────────────────────────────────────────────────────────────┤
│ Application services  (aoi/core/services.py → AppContext): the only door     │
│  reads   board_models · samples · models · recipe · inspections · users      │
│  writes  import_samples · train · save_recipe · set_reference · add_user     │
│  engine  inspector · inspect · inspect_file · log_result · batch_test        │
│  jobs    the thread pool every slow call runs on (REQ-SET-021)               │
├──────────────────────────────────────────────────────────────────────────────┤
│ Inspection engine  (aoi/core)                                                │
│  imaging.py   checked I/O (type, caps, Unicode paths), align, heatmaps       │
│  anomaly.py   self-training conv. autoencoder + calibration (.pt)            │
│  compare.py   golden-sample diff (shift-tolerant Lab ΔE), SSIM, blobs        │
│  inspector.py pipeline → Checks (decision variables) + Defects + verdict     │
│  recipe.py    ROIs + thresholds per board model                              │
│  jobs.py      background jobs: progress, cancel, finished callbacks; no Qt   │
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
(tests, a future CLI, the Stage 3 robot cycle, or a Stage 4 MES service). `tests/test_layers.py` enforces both:
no Qt import under `aoi/core` or `aoi/data`, and under `aoi/ui` no `sqlite3` or `aoi.data` import, no `.db`, no SQL,
no `Inspector` built by a page (REQ-USR-001, since S15) and no image read outside `AppContext.load_image` (since S23c). `aoi/times.py`, `aoi/errors.py`, `aoi/config.py` and
`aoi/defects.py` are shared by every layer.

Types (Code style, since S22): mypy runs strict on `aoi/core`, `aoi/data` and `aoi/times.py`, and since S22a on `aoi/ui`
and `aoi/hal` too, with no flag relaxed (`pyproject.toml`). PySide6 enums are written in full
(`Qt.AlignmentFlag.AlignCenter`), pages take `QT_TRANSLATE_NOOP` from `aoi/ui/pages/base.py` (Qt's is typed as returning
object), and no widget attribute carries a QWidget method's name: `size`, `pos` and `render` hid `QWidget.size()`,
`pos()` and `render()` on three pages until S22a, and `tests/test_screen_rules.py` now fails on one. Since S22b every
page is typed and no module is exempt, and ruff's annotation rules (all but ANN401) require a type hint on every
function argument and return value across the repository, `tools/`, `main.py` and `tests/` included; mypy does not run
there, so those hints are present, not verified.

An image file from outside is checked before it is decoded (REQ-INSP-001, since S23): `aoi/core/imaging.load_image` reads
the format and the size from the file's bytes, never from its name, and refuses a file over the byte limit or an image
over the pixel limit with `AOI-INSP-005` before a pixel is decoded, an image with a side over 1,048,576 px, the decoder's
own limit, with `AOI-INSP-007`, a file that holds no PNG, JPG, BMP or TIFF image with `AOI-INSP-004`, and a recognised
format whose header gives no size, or that the decoder rejects (cut short, damaged, a variant OpenCV does not read), with
`AOI-INSP-006`. Wherever a file can be read in two ways the header readers follow the decoders (stray bytes between JPEG
segments are skipped as libjpeg skips them, a TIFF size tag of any integer type counts, classic or BigTIFF, a bitmap is
known by its header size), so no file measures small here and decodes large; `tests/test_image_input.py` holds the
crafted files and files from Pillow and tifffile. The limits are the two `max_image_*` values in `settings.json`, in the
default workspace folder (50 MP and 200 MB, that is 200,000,000 bytes, both proposed, since a 50 MP 24-bit BMP is
150 MB); `Settings.load` refuses a value of the wrong type, or a limit not above 0, with `AOI-SET-008` before the app
starts, and the Settings page does not show them yet (an Admin edits the file). Every page and service reads an image
through `AppContext.load_image`, which applies them; `FolderCamera` takes them when the inspection cycle wires a camera
(Stage 2); `tests/test_layers.py` fails a page that imports `load_image` or calls it on anything but the context; and
`import_samples` still copies sample files without a check (threat model, page 2).

The view an inspection was taken from (REQ-INSP-010, since S23b) travels with its result: `InspectionResult.view` is set
by the engine from the view it inspected under, and every defect's side is taken from it, so a change of the Inspection
page's View box during a run cannot relabel a board already inspected or its defects. It is stored in `inspections.view`
(migration 0005; NULL for rows from before it, never guessed) and shows in the Logs & Export table's View column, after
Operator as the S02 sketch places it (`docs/sketches/logs-history.md`, PR #79), and in its CSV export after
`board_model`. The headless `AppContext.inspect_file` takes the view as `side` and records Top by default.

Slow work never runs on the UI thread (REQ-SET-021, since S17): a page wraps it in a `Worker` (`aoi/ui/workers.py`),
which runs it as a `Job` on the pool `AppContext.jobs` owns (`aoi/core/jobs.py`: progress, cancel and finished callbacks,
no Qt, so the same jobs run headless) and turns the callbacks into signals; the slots run on the UI thread, the only
place a widget changes. A job function takes plain values in and returns plain values out, never a widget. A page runs
its background action through `Page.run_in_background` (the newest call wins) under a `BusyOverlay` where the result
will appear (after 1 s the time so far; after 10 s progress, time left, Cancel); `tests/test_no_freeze.py` ticks the UI
thread every 50 ms through each page's 5 MP action and fails on a gap over 2 s.

A control an operator uses by key and by touch is one `QAction` (`Page.action`, since S24): a window shortcut owned by
the page, so the key works wherever the focus is on the page and only while the page is shown, behind an
`action_button` whose label carries the key ("Next Board  F8") and whose enabled state follows the action's, so the
button and the key never disagree (REQ-INSP-005). The Inspection page answers within the action itself: the banner is
repainted grey with "Inspecting…" before the pool thread starts, and the verdict is painted before the image and the
defect table are built from the result (REQ-INSP-002); the first board's engine is built on the pool thread and kept
for the rest of the queue unless the page dropped it meanwhile (a board model change or a revisit raises a generation
counter, so a stale engine is never kept), and one worker runs at a time per page (#120).
`tests/test_run_controls.py` measures both budgets.

Colours, point sizes and size classes are tokens in `aoi/ui/theme.py` (REQ-SET-004, since S18): the stylesheet is
built from them with `theme.stylesheet()`, so another theme is a set of overrides (REQ-SET-008); a page never writes a
colour or a point size of its own, nothing is below 14 pt, and `tests/test_screen_rules.py` scans aoi/ui for a
literal and checks that every page sits in the one frame (REQ-SET-018). A verdict is shown as its colour with a shape and the word
(`theme.verdict_label`: ✓ OK, ✗ NG, ▲ WARN; REQ-INSP-002), each page has one blue `primary` button, and a button that
removes data is a red `danger` button, last in its row and never the default. Every empty page, list and
image area shows an `EmptyState` (`aoi/ui/widgets/empty_state.py`): what is missing, what to do next and one link
button to the page where it is done; `Page.empty_step` turns "do this on <page>" into that link, or into "Ask an
Engineer …" for a role that cannot open the page (REQ-SET-019, since S18c).

Every page is rendered offscreen for every role that may open it and compared with an approved image (REQ-SET-004,
since S21): `tools/render_screens.py` builds the synthetic workspace with pinned ids, times, inspection time and fonts
(DejaVu Sans without hinting on Linux) and inspects with a pixel-based stand-in for the trained model (`PinnedModel`: the
seeded training's float rounding differs by CPU type, so a trained model's verdict and boxes differ between machines; the
stand-in's quantised 8-bit difference from the golden board, with wide margins to its thresholds, shows the same verdict,
boxes and scores everywhere, and only SSIM and inlier digits from the float alignment still move, far under the
tolerance), and `tests/screens/test_screens.py` compares the 1920×1080 renders with
`tests/screens/approved/` on Linux; a page fails when more than 0.5 % of its pixels move by more than 40 levels, and
the new images with a diff per failing page stay in `tests/screens/actual/`, which CI uploads. An intended screen
change is approved with `python tools/render_screens.py --approve`; the images are generated files that Jay approves by
merging. On Linux, CI also renders every page at 1366×768 and at 3840×2160 with 150 % and 200 % scaling into the
`screens-review` artifact of the run (kept 30 days), which is how the layouts are checked at the standard's other sizes
(#104 records that the pages do not yet fit 1366×768). `tests/screens/test_sizes_and_contrast.py` walks the same pages on Linux and Windows and measures every visible
widget against the standard's "Sizes": 14 pt text (QGraphics text on an image takes `label_font()`), 120×40 buttons whose
text fits, 48 px operator targets (sidebar entries, header controls, defect and history rows), 56 px run controls, and
WCAG 2.1 contrast of 4.5:1 between a widget's pixels and its background (3:1 for bold or 18 pt text; disabled controls
exempt). On Windows, CI points `QT_QPA_FONTDIR` at the system font folder: Qt's offscreen platform ships no fonts
there, and without fonts every text is a box that reads as -0.8 pt, so the walk asserts first that fonts loaded.
A control's size class is set with `size_class(widget, "T")` (48 px) or `"T+"` (56 px), which the stylesheet sizes
through `[sizeClass=…]` rules; `setMinimumHeight()` on a styled widget is undone when the stylesheet is applied.

### Workspace on disk

```
AOI_Workspace/                 (default ~/AOI_Workspace, set in Settings or AOI_WORKSPACE env var)
  aoi.sqlite                   database
  logs/aoi-YYYY-MM-DD.jsonl    JSON-lines log, one file per UTC day (REQ-LOG-004)
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

Since S16 the check lives in the service layer (ADR 0002, decision 5): every `AppContext` write is decorated with
`@requires(role, what)` in `aoi/core/services.py` and raises `AOI-USR-001` when the current user's role is lower, so
hiding a page or disabling a button is only a convenience. Every write also appends an audit entry (REQ-LOG-004):

| Write | Role | Audit action and object (before → after) |
|---|---|---|
| `ensure_board_model`, `set_reference`, `import_samples` | Engineer | `board_model.create`, `board_model.reference` (reference path), `sample.import`; object = board model name |
| `update_sample`, `delete_sample` | Engineer | `sample.update` (label, defect type), `sample.delete`; object = sample UUID |
| `train`, `activate_model` | Engineer | `model.train`, `model.activate` (active version; an older one is a rollback); object = model UUID |
| `save_recipe` | Engineer | `recipe.save` (recipe body); object = recipe UUID |
| `batch_test` | Engineer | `test.run` (folder, model version, metrics); object = board model name |
| `export_model`, `export_overlays`, `export_csv` | Engineer | `export.model`, `export.overlays`, `export.csv` (destination, counts) |
| `archive_old` | Engineer | `inspection.archive` (days, count); the retention run at start-up is a system action: logged, not audited |
| `add_user` | Admin | `user.change` (role); object = user UUID |

Reads, inspections (`inspect_file`, `log_result`), alarms and error reports need no role: an Operator inspects boards.
Until sign-in ships (REQ-USR-002, 1.0) the user is the one picked in the header, so an entry names who was picked.

User switching is a local picker for the PoC; Stage 4 replaces it with MES authentication (`MesClient.authenticate`).

### Pages

| Page | Main functions | Spec |
|---|---|---|
| **Home** | Six step cards (Upload → Self-train → Tune recipe → Validate → Inspect → Export) with live status for the selected board model | RM Stage 1 flow |
| **Inspection** | Load images/folder (Stage 1 "camera"); Top/Side/Bottom view tag; **Start / Stop / Next Board / Save Result**; image with defect boxes coloured by severity; defect list **No, Type, Score, Side, X, Y** (click to zoom); big OK/NG/WARN banner; alarm log with time, level, code and message, kept across restarts; auto-save each board | GUI §4.1 |
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
| `recipes` | board_model, revision (1 is the default recipe, stored when the board model is created, so every result names a stored revision), uuid, body JSON, user, created_at |
| `inspections` | time, board_model, model_version, model_uuid, recipe_rev, recipe_uuid, image/overlay paths, view (Top, Side or Bottom; NULL for rows from before migration 0005), result, score, metrics JSON, result_json (the whole result as `InspectionResult.to_dict` writes it, read back by `from_dict` without the images; NULL before migration 0006), operator, archived |
| `defects` | inspection_id, no, type, score, side, x, y, w, h |
| `checks` | inspection_id, no, region (Board, or the ROI's name and box), metric, source, value, threshold, rule, result, explain: one row per decision variable of a result (REQ-INSP-012; none for rows from before migration 0006) |
| `test_runs` | time, board_model, model_version, folder, metrics JSON, results JSON |
| `alarms` | time, level NG/WARN/ERROR, code AOI-<AREA>-<NNN>, message; the newest 1,000 are shown and survive a restart |
| `users` | — |
| `audit` | uuid, at_utc, user_uuid, role, action, object_type, object_uuid, before_json, after_json, reason; append only (triggers refuse UPDATE and DELETE) |
| `schema_version` | number, name, applied_at, checksum (migration runner) |

The schema is created and changed only by the numbered migrations in `aoi/data/migrations/`, which
`aoi/data/migrate.py` applies at start-up and records in `schema_version` with a checksum (ADR 0004). The
connection runs in write-ahead-log mode with a full sync on every commit, and a v0.1 workspace (no
`schema_version` table) is refused rather than upgraded.
Records that can leave the station (`users`, `samples`, `models`, `recipes`, `inspections`) carry a `uuid`
beside their integer key; every stored time is ISO 8601 UTC with an offset and is shown in local time
(`aoi/times.py`); image, overlay and model paths inside the workspace are stored relative to it and resolved
by `aoi/data/paths.py`, so a workspace folder can move (REQ-SET-017, REQ-SET-001).
Every file the app writes (images, overlays, AI models, exports, settings) goes through `aoi/data/atomic.py`:
a temporary name in the same folder, flush and fsync, then an atomic rename, and an inspection's row, checks and
defects commit in one transaction, so a crash leaves a whole result or none (REQ-INSP-008). Every error a user can see is
an `AoiError` from the catalogue in `aoi/errors.py`, with a code `AOI-<AREA>-<NNN>`, what happened and what to do;
`docs/error-codes.md` is generated from it (REQ-LOG-004, REQ-SET-019). `aoi/logging_setup.py` writes the JSON-lines
log in `<workspace>/logs/`, one file per UTC day, with time, level, module, event, ids and the app version, and never
an image or a password. Alarms (an NG verdict, a missing AI model, every error shown) are stored in `alarms` with
their code through `AppContext.alarm`, and `AppContext.report_error` is the one path for an error a user sees: it
logs the stack trace with the build version, stores an ERROR alarm and returns the plain report that
`aoi/ui/errors.py` shows (code, title, what happened, what to do), also for unhandled errors through
`sys.excepthook`. The page in use is kept in `settings.json` and reopened at start-up (REQ-INSP-006, REQ-LOG-005).
Every visible string goes through `self.tr()` in a page class (REQ-SET-005, since S19). PySide takes the
most-derived class name as the context of `self.tr()`, while `pyside6-lupdate` files a string under the class that
contains the call, so the base `Page` uses `QCoreApplication.translate("Page", …)`, page titles are marked
`QT_TRANSLATE_NOOP("Page", …)` and shown through `page_text()` (the English title stays the navigation key), and
role names go through `role_text()` and camera views through `view_text()` (the combo keeps the English name as
item data, the key the engine stores). Names the engine stores with a result (check names, sources, rules) stay
English; Compare shows them through its `CHECK_NAMES`, `SOURCES` and `RULES` maps, and the Show combo's modes are
chosen by index, so a translation cannot change behaviour. A subtitle that carries a value (Settings shows the
version) overrides `Page.subtitle_text()`; the "No board model yet" empty state every page shows comes from
`Page.no_board_model()`. A sentence is never glued from pieces: placeholders are named, `{count}`, and filled with
`.format()` after translation, never with an f-string. `tests/test_i18n.py` scans `aoi/ui` and `main.py` with `ast`
and fails on a string literal passed to a Qt text setter, a text widget, a dialog, a table header or one of this code's
helpers outside `tr()`, and on an unmarked page title; `ALLOWED_LITERALS` there names the few literals that stay, each
with its reason (device names, the base class's placeholder title). `aoi/i18n/aoi_ko.ts` is
generated by
`python tools/update_translations.py` (pyside6-lupdate over `aoi/`) and a test fails when it is stale; Korean
translations are filled in later with Qt Linguist and compiled with `pyside6-lrelease`.

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
