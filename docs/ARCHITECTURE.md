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
| Language / UI | **Python 3.11 / PySide6 (Qt 6)** | GUI §6 allows ".NET / C# or Python (PyQt / Tkinter)". PySide6 is the official, LGPL-licensed Qt binding (PyQt is GPL/commercial), which matters for selling 50–200+ licenses (RM §3–4); it is installed as `PySide6-Essentials`, without the Addons' GPL-only modules such as Qt Charts (ADR 0003). Qt also gives a native Windows 10/11 look, high-DPI, and 1920×1080 layouts. |
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
│          re_evaluate (a stored result under other thresholds, Engineer)      │
│  jobs    the thread pool every slow call runs on (REQ-SET-021)               │
├──────────────────────────────────────────────────────────────────────────────┤
│ Inspection engine  (aoi/core)                                                │
│  imaging.py   checked I/O (type, caps, Unicode paths), align, heatmaps       │
│  anomaly.py   self-training conv. autoencoder + calibration (.pt)            │
│  compare.py   golden-sample diff (shift-tolerant Lab ΔE), SSIM, blobs        │
│  inspector.py pipeline → Checks (decision variables) + Defects + verdict     │
│  explain.py   a verdict in plain words, one sentence per failing check       │
│  views.py     Compare's heat views: the board under a difference or AI map   │
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
segments are skipped as libjpeg skips them, a TIFF size tag of any integer type counts, classic or BigTIFF, a TIFF that
gives a size tag twice is refused with `AOI-INSP-006` since libtiff reads the first entry (#169), a bitmap is known by
its header size), so no file measures small here and decodes large; `tests/test_image_input.py` holds the
crafted files and files from Pillow and tifffile. The limits are the two `max_image_*` values in `settings.json`, in the
default workspace folder (50 MP and 200 MB, that is 200,000,000 bytes, both proposed, since a 50 MP 24-bit BMP is
150 MB); `Settings.load` refuses a file it cannot read (not JSON, not UTF-8, not an object) with `AOI-SET-010`, and a
value of the wrong type, a limit, log retention, input size or epoch count below 1, or a workspace that is not a full
path (empty, blank or relative), with `AOI-SET-008`, before the app starts; the Settings page checks its own values
the same way before it saves. The page does not show the limits yet (an Admin edits the file): the app writes only the
keys it changes over `settings.json` as it is on disk (`Settings.save_keys`, #170), so the edit stays, for the next
start to read. `map_retention_days_ok` (7, not below 0) is the third: the map files of OK results older than that go
at start-up (`_sweep_ok_maps`, audited as `maps.sweep`; NG and WARN maps stay, REQ-INSP-012). Every page and service reads an image
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
thread every 50 ms through each page's 5 MP action and fails on a gap over 2 s. No slot and no job function holds its
own worker or the worker's signals (#132): Qt keeps a slot as long as the signals, which the worker holds, so a worker
its slot held would stay, with its job and the job's result, for as long as the app runs; and signals a job held would
be deleted with the job, on whichever thread let go of it last, where Qt forbids deleting an object of another thread.
The slots hold the worker by weak reference and a job function reports through a bound emit (`w.signals.progress.emit`,
bound once the worker is built), which does not keep the signals; `tests/test_background_results.py` checks that a
result is freed once the page shows another, and that a board that fails lets go of its worker's signals with the
worker. One call starts a thread of its own: `maps.load_maps`, run by a job, decodes a stored result's AI map on a
helper thread while the job decodes the difference map, and waits for it before it returns.

A control an operator uses by key and by touch is one `QAction` (`Page.action`, since S24): a window shortcut owned by
the page, so the key works wherever the focus is on the page and only while the page is shown, behind an
`action_button` whose label carries the key ("Next Board  F8") and whose enabled state follows the action's, so the
button and the key never disagree (REQ-INSP-005). The Inspection page answers within the action itself: the banner is
repainted grey with "Inspecting…" before the pool thread starts, and the verdict is painted before the image and the
defect table are built from the result (REQ-INSP-002); the first board's engine is built on the pool thread and kept
for the rest of the queue unless the page dropped it meanwhile (a board model change or a revisit raises a generation
counter, so a stale engine is never kept), and one worker runs at a time per page (#120).
`tests/test_run_controls.py` measures both budgets.

Compare shows each view within 300 ms at 5 MP (REQ-CMP-002, since S27b). `aoi/core/views.py` draws the two heat views,
the board under its difference map or its AI score map, and `heat_overlay` blends the colours in with OpenCV
(`cv2.blendLinear`): about 25 ms at 5 MP against 130 ms for the NumPy blend before, on the 4-core cloud VM the tests run
on (not the reference PC). The page keeps the views it drew for the result shown, one per view and pixel difference, so
switching back only shows the picture again, and drops them when another result is shown; `tests/test_compare_views.py`
times each view until both panes are painted, the median of five openings of a stored 5 MP result.

Colours, point sizes and size classes are tokens in `aoi/ui/theme.py` (REQ-SET-004, since S18): the stylesheet is
built from them with `theme.stylesheet()`, so another theme is a set of overrides (REQ-SET-008); a page never writes a
colour or a point size of its own, nothing is below 14 pt, and `tests/test_screen_rules.py` scans aoi/ui for a
literal and checks that every page sits in the one frame (REQ-SET-018). A verdict is shown as its colour with a shape and the word
(`theme.verdict_label`: ✓ OK, ✗ NG, ▲ WARN; REQ-INSP-002), each page has one blue `primary` button, and a button that
removes data is a red `danger` button, last in its row and never the default. Every empty page, list and
image area shows an `EmptyState` (`aoi/ui/widgets/empty_state.py`): what is missing, what to do next and one link
button to the page where it is done; `Page.empty_step` turns "do this on <page>" into that link, or into "Ask an
Engineer …" for a role that cannot open the page (REQ-SET-019, since S18c). The block is as wide as its text would
like within the area and as tall as its text wraps to at that width; a word wider than the area runs past the edge,
and every line shows while the area is tall enough (since S27a-2).

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
AOI_Workspace/                 (default ~/AOI_Workspace, set in Settings, used from the next start, or AOI_WORKSPACE)
  aoi.sqlite                   database
  logs/aoi-YYYY-MM-DD.jsonl    JSON-lines log, one file per UTC day (REQ-LOG-004)
  settings.json
  images/<board>/<OK|NG>/      uploaded training samples (copied in, so source folders can move)
  models/<board>/<board>_vX.Y.pt            trained model + calibration: tensors and plain values only, loaded with
                                            torch.load(weights_only=True) after its zip CRC-32s check; a file that
                                            is cut short, changed or unusable, has an entry flagged as a folder, or
                                            holds another AI model than the UUID its registry row names is refused,
                                            AOI-TRN-001 (REQ-TRN-014)
  models/<board>/<board>_vX.Y_golden.png    learned golden template
  results/<date>/*.png         overlay per inspected board, with its *_diff.png and *_ai2.png maps (REQ-INSP-012;
                               *_ai.png before S28a)
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
An AI model the loader would refuse, such as one with an image threshold of 0 from OK images that are copies of one
photo, is refused at step 5 with AOI-TRN-004: nothing is saved, registered or audited, and the active version stays.
The reference image an Engineer sets (Set Reference) must be an OK sample (AOI-TRN-006): inspections compare against it
at once, and step 1 aligns to it. While a sample is the reference, it cannot be relabelled NG or removed (AOI-TRN-007).

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
| Alignment inliers (shown as "Alignment points") | Compare | info; WARN if < 12 | Confidence that the board was registered correctly |
| AI anomaly score | AI | NG if ≥ model threshold | 99.9th percentile of the anomaly map (σ above normal variation) |
| ROI *name* [type] | ROI | NG if ≥ ROI AI Score | Strongest anomaly inside the ROI, as a multiple of the model threshold |
| Inspection time | System | spec < 1 s | GUI §11 acceptance criterion |

The Compare page's "why" box explains the verdict in plain words (`aoi/core/explain.py`, REQ-CMP-004): under the heading
"Why this board is NG:", a bulleted sentence per NG check, then per WARN check, naming the check, its value and its
threshold with their unit (an ROI's value as a multiple, ×, of the AI model's threshold); with no failing check, that
every check that decides the verdict is inside its threshold, or that defects above Minor severity make the board a
WARN; then one sentence per check that did not run, with what to do, which the Inspection page shows under its summary
too. Each sentence is an English template with named values, which a screen translates under the context "Explain"
before filling it in, so the engine stays free of Qt and a translation can put the values in its own order.

Verdict: **NG** if any check is NG; else **WARN** if any check is within the warning band (default 80 % of a
threshold) or a non-minor defect region exists; else **OK**. Colours follow GUI §4.1: green OK, red NG, yellow WARN.
A board is never OK on no evidence (#169): a check value that is no number (NaN, infinite) grades NG; a board no check
judged, inspected or judged again (no Golden board and no AI model, or the recipe turns off what could run) gets no
verdict but `AOI-INSP-010`, naming why each check did not run; a Golden board the database names whose file is gone or
cannot be read refuses the board with `AOI-INSP-009` in `AppContext.inspector`, where it was once dropped as if none
were set; and the engine refuses a board image or Golden board with a side under 11 px (`MIN_SIDE` in
`aoi/core/compare.py`: a 7 px SSIM window, and 3 px of difference map inside its 4 px border) with `AOI-INSP-011` before
any work. A stored OK with no check, from before, is explained as "the stored checks do not show why".

A result is judged again with other thresholds without aligning, comparing or running the AI model (REQ-CMP-005, the
engine since S28a): `Inspector.judge` grades the evidence a result holds, a board's just inspected or a stored one's,
and `inspector.re_grade` finds the difference regions again on the result's difference map, reads the AI defects from
its AI map and takes each ROI's peak from the ROI check it was judged with (an ROI added, moved or renamed since is read
from the AI map), with the AI score and the AI model's calibration given as `AiEvidence`. On the evidence a board was
inspected with, the thresholds it was judged by give back its checks, defects and verdict, and other thresholds what
inspecting it with them gives. A check the recipe turns on that did not run on the board is not judged, with a note
saying so. A stored result holds that evidence in its record and its two map files (`aoi/core/maps.py`, format 2 since
S28a, [ADR 0005](adr/0005-stored-ai-map-format-2.md)): the difference map exactly, and the AI map within one step (0.001
σ up to 32.767 σ, then 1/8192 of the value, up to 1789 σ) with each pixel on the side of the AI model's pixel threshold
it was judged on; a map file that is there but cannot be read raises AOI-CMP-003. So a stored result is judged again as
the live one would be, but for what is read from its AI map, within one step over the AI threshold: an AI defect's
score, so two AI defects of equal area whose peaks are that close may swap numbers or, where they overlap, keep the
other one, and the value of an ROI added, moved or renamed since, which that close to its threshold may grade the other
way. AI maps stored before S28a (format 1) are clipped at 65.535 σ and not kept on their side of the pixel threshold. An
Engineer judges a stored result again through `AppContext.re_evaluate(result_uuid, thresholds)` ([ADR
0006](adr/0006-judging-a-stored-result-again.md)): it reads only the maps the thresholds use, the AI score from the
result's stored AI check and the AI model's calibration from the model registry row the result names by UUID; it refuses
with AOI-CMP-004 a result whose map or AI model calibration is gone when a check the thresholds use needs it, and with
AOI-CMP-005 thresholds of another board model; it stores nothing, and takes about 130 ms at 5 MP on the 4-core cloud
VM the tests run on. `tests/test_re_evaluate.py` checks this.

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
| `_sweep_ok_maps` | system, at start-up; no page calls it | `maps.sweep` (days, swept, skipped): the map files of OK results past `map_retention_days_ok` are deleted and forgotten, NG and WARN maps stay; audited, unlike the start-up archive, because it deletes evidence. A file that cannot be deleted, or lies outside results/, is skipped with a warning and kept for the next start |
| `add_user` | Admin | `user.change` (role); object = user UUID. The last Admin keeps the role: `AOI-USR-002`, nothing written |

Reads, inspections (`inspect_file`, `log_result`), alarms and error reports need no role: an Operator inspects boards.
One call that writes nothing needs a role: `re_evaluate`, judging a stored result with other thresholds (REQ-CMP-005),
is for an Engineer, through the same check; it stores nothing, so it writes no audit entry.
Until sign-in ships (REQ-USR-002, 1.0) the user is the one picked in the header, so an entry names who was picked.

User switching is a local picker for the PoC; Stage 4 replaces it with MES authentication (`MesClient.authenticate`).

### Pages

| Page | Main functions | Spec |
|---|---|---|
| **Home** | Six step cards (Upload → Self-train → Tune recipe → Validate → Inspect → Export) with live status for the selected board model | RM Stage 1 flow |
| **Inspection** | Load images/folder (Stage 1 "camera"); Top/Side/Bottom view tag; **Start / Stop / Next Board / Save Image…**; image with defect boxes coloured by severity; defect list **No, Type, Score, Side, X, Y** (click to zoom); big OK/NG/WARN banner; alarm log with time, level, code and message, kept across restarts; every result saved with its evidence on the pool thread, before the next board (REQ-INSP-008, REQ-SET-021; a failed save stops the run with AOI-INSP-008) | GUI §4.1 |
| **Compare** (optional) | Golden reference and test board **side by side** with **synchronised zoom/pan**; views: side-by-side, difference heatmap, AI anomaly heatmap, boxes only; **decision table** (check, source, value, threshold, rule, result) with failing rows highlighted, from the **stored result** when the page opens on a record (row for row the stored checks, never a new inspection: REQ-CMP-003; one click from Inspection, REQ-INSP-009) beside the golden board it was judged against, which Re-evaluate keeps (not shown, with the reason and Re-evaluate as the next step, when that file has changed, cannot be read or is gone, or none was recorded), with a note naming the versions that judged it and what changed since; plain-word "why" box, one sentence per failing check, NG first (REQ-CMP-004); **what-if thresholds** with Re-evaluate and Save to Recipe; pick any reference image instead of the golden template | Jay's request |
| **Training** | **+OK / +NG upload** (NG labelled with DCT category, type and view), import folder with `ok/` `ng/` sub-folders; dataset table with relabel / set reference / remove; preview; epochs, input size, device; Start/Stop with progress and log; **model version registry** with activate and export `.pt` | GUI §4.3, Stage 1, §6 model version control |
| **AI Model Test** | Select labelled folder; Run Test / Run Test Again; **Accuracy, Precision, Recall, False Call Rate** tiles; confusion counts; results table **Image, GT, AI Result, Score, Pass/Fail** with failures in red; preview; **Export CSV / Export Report (PDF)**; runs stored in DB | GUI §4.3 |
| **Recipe Editor** | Draw ROIs on the golden board (zoom/pan); ROI types **Presence, Polarity, Solder Bridge, Height, Anomaly**; parameters **AI Score, Height Min/Max, Volume Min/Max**; yellow = selected, green = saved; global thresholds; **mandatory AOI set** checklist (DCT §4) marking checks that need Stage 2 3D/side cameras; Test Run; Save Recipe → revision with user + timestamp | GUI §4.2, DCT §4 |
| **3D Profile** | Layout placeholder (height map, defect details, Accept/Reject) until Stage 2 3D data exists | GUI §4.5 |
| **Logs & Export** | Filter by date, model, operator; sortable table; overlay preview; Export CSV (two files, UTF-8 with BOM: the records, with their columns as before and the record, model and recipe UUIDs appended, and `<name>_checks.csv` with one row per check: region, metric, source, value, threshold, rule, result and the model and recipe UUIDs, its header written even when no record has checks; REQ-INSP-012) / overlay images with confirmation; auto-archive > 30 days (on start and on demand) | GUI §4.4 |
| **Settings** | Workspace, AI device (auto/CPU/CUDA), defaults, retention, language (en/ko placeholder for 2H 2027 localisation); users & roles; hardware interface status per stage | GUI §6, §8, RM 2H 2027 |

---

## 6. Database schema (SQLite)

| Table | Key columns |
|---|---|
| `board_models` | name (a new name that differs from an existing one only in case is refused, AOI-TRN-005: Windows would give both the same model and golden board files), reference_image (golden) |
| `samples` | board_model, path, label OK/NG, defect_type (DCT), side |
| `models` | board_model, version, uuid (also in the `.pt` file's metadata, written there before the file is saved, so an exported file names its record), path (.pt), metrics JSON (thresholds, scores, timing), active |
| `recipes` | board_model, revision (1 is the default recipe, stored when the board model is created, so every result names a stored revision), uuid, body JSON, user, created_at |
| `inspections` | time, board_model, model_version, model_uuid, recipe_rev, recipe_uuid, image/overlay paths, diff_map_path and ai_map_path (the difference and AI score maps as PNG files beside the overlay, 8-bit exact, and 16-bit within one step: `_ai2.png` since S28a, 0.001 σ steps to 32.767 σ, then 1/8192 of the value to 1789 σ, or `_ai.png` before, 0.001 σ steps to 65.535 σ; NULL for rows from before migration 0007, and for OK results once the retention sweep deleted them), reference_path and reference_sha256 (the golden board file the result was judged against and the SHA-256 of its bytes; NULL for rows from before migration 0008 and for results judged without a golden board), view (Top, Side or Bottom; NULL for rows from before migration 0005), result, score, metrics JSON, result_json (the whole result as `InspectionResult.to_dict` writes it, read back by `from_dict` without the images; NULL before migration 0006), operator, archived |
| `defects` | inspection_id, no, type, score, side, x, y, w, h |
| `checks` | inspection_id, no, region (Board, or the ROI's name and box), metric, source, value, threshold, rule, result, explain: one row per decision variable of a result (REQ-INSP-012; none for rows from before migration 0006) |
| `test_runs` | uuid, time, board_model, model_version, model_uuid (NULL for runs from before migration 0009), folder, metrics JSON, results JSON (one row per image; its `image` path stored like `folder`); the AI Model Test CSV and report name the run and the AI model by UUID |
| `alarms` | uuid, time, level NG/WARN/ERROR, code AOI-<AREA>-<NNN>, message; the newest 1,000 are shown and survive a restart |
| `users` | — |
| `audit` | uuid, at_utc, user_uuid, role, action, object_type, object_uuid, before_json, after_json, reason; append only (triggers refuse UPDATE and DELETE) |
| `schema_version` | number, name, applied_at, checksum (migration runner) |

The schema is created and changed only by the numbered migrations in `aoi/data/migrations/`, which
`aoi/data/migrate.py` applies at start-up and records in `schema_version` with a checksum (ADR 0004). The
connection runs in write-ahead-log mode with a full sync on every commit, and a v0.1 workspace (no
`schema_version` table) is refused rather than upgraded.
Before it applies pending migrations to a database that already has some, the runner copies the database beside itself
with SQLite's online backup as `aoi.sqlite.bak-<from>-to-<to>-<UTC time>`, for example
`aoi.sqlite.bak-0004-to-0009-20261002T051500Z` (the last migration applied, the last this build ships, ISO 8601 basic
time), written under a temporary name and renamed once whole; a copy that fails stops the start with `AOI-SET-009`,
nothing migrated, and a brand-new database gets no copy (Engineering, "Upgrade and rollback"). Rolling back is one step
with the app closed: copy that file over `aoi.sqlite`, deleting `aoi.sqlite-wal` and `aoi.sqlite-shm` if a crash left
them (they belong to the replaced file), then start the version upgraded from; results recorded since the upgrade are
only in the replaced file. The app never deletes the copies (nothing is deleted without an Admin action); a one-click
restore belongs to the installer. A refused workspace (`AOI-SET-001`, `-002`, `-003`, `-005`, and `-011` for a folder
that cannot be created or a database file SQLite cannot open) is reported before any window opens, so `open_workspace`
in `aoi/ui/errors.py` follows the message with a folder picker: the folder chosen is saved to `settings.json` as the
Settings page saves it and opened, and Cancel closes the app (REQ-SET-016). An error at start-up without a code shows
`AOI-SET-007`, and its trace goes to the log in the default workspace folder (event `app.start_failed`), since the
excepthook is installed only once the window exists (REQ-SET-019).
Records that can leave the station (`users`, `samples`, `models`, `recipes`, `inspections`, and since migration 0009
`test_runs` and `alarms`) carry a `uuid` beside their integer key; `defects` and `checks` are rows of one inspection and
are named by its UUID and their `no`. The dataset record, with its UUID, arrives with frozen dataset versions (stage
S35, REQ-TRN-005). Every stored time is ISO 8601 UTC with an offset and is shown in local time
(`aoi/times.py`); image, overlay, map, golden board, model and validation folder paths inside the workspace are stored
relative to it and resolved by `aoi/data/paths.py`, so a workspace folder can move (REQ-SET-017, REQ-SET-001). A path
outside the workspace (a validation folder on a USB drive) is stored absolute and read as written, as are the paths of
validation runs stored before migration 0009.
Every file the app writes (images, overlays, AI models, exports, settings) goes through `aoi/data/atomic.py`:
a temporary name in the same folder, flush and fsync, then an atomic rename, and an inspection's row, checks and
defects commit in one transaction, so a crash leaves a whole result or none (REQ-INSP-008). Every error a user can see is
an `AoiError` from the catalogue in `aoi/errors.py`, with a code `AOI-<AREA>-<NNN>`, what happened and what to do;
`docs/error-codes.md` is generated from it (REQ-LOG-004, REQ-SET-019). `aoi/logging_setup.py` writes the JSON-lines
log in `<workspace>/logs/`, one file per UTC day, with time, level, module, event, ids and the app version, and never
an image or a password; a caller's extra never replaces one of those fixed fields (one of the same name is written as
`extra_<name>`, #171). Alarms (an NG verdict, a missing AI model, every error shown) are stored in `alarms` with
their code through `AppContext.alarm`, and `AppContext.report_error` is the one path for an error a user sees: it
logs the stack trace with the build version, stores an ERROR alarm and returns the plain report that
`aoi/ui/errors.py` shows (code, title, what happened, what to do), also for unhandled errors through
`sys.excepthook`; it never raises, so the dialog shows even when the database refuses the alarm (logged as
`alarm.not_stored`, #171). The page in use is kept in `settings.json` and reopened at start-up (REQ-INSP-006, REQ-LOG-005);
a page change writes that key alone. A workspace saved on Settings goes to `settings.json` only: the running app keeps
its database, log and folders on the open workspace until the restart (REQ-SET-001, #170).
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

Speed (REQ-INSP-007): the CI job "Performance (base vs head)" times `Inspector.inspect` on the regression set's 40
boards at 0.3 MP and 5 MP for the base commit and the head on one runner (`tools/perf_compare.py`) and fails when the
head's median or 95th percentile at either size is over 1.10 times the base's; `tests/perf/test_timing.py` checks a
developer machine against its own `baseline.json` entry. Neither is the product's speed (`tests/perf/README.md`).

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
