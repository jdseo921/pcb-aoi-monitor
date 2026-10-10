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
| Packaging | PyInstaller one folder in an Inno Setup installer (`installer/aoi.iss`), built, installed, self-tested and uninstalled by CI (ADR 0007); unsigned and internal until code signing (J6) | Single-folder deploy for PoC stations, per machine into Program Files, with Start menu and Demo shortcuts and an uninstaller that keeps the workspace (`docs/install/install.md`). `main.py --self-test` (`aoi/selftest.py`) inspects one synthetic board with no window, so CI checks that the windowed .exe inspects, before and after it is installed (`tools/check_installer.py`). |

---

## 2. Layered architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ UI layer  (aoi/ui)                     PySide6                               │
│  MainWindow: header (board model, user/role) · sidebar nav · page stack      │
│  Pages: Home · Inspection · Compare · Training · AI Model Test ·             │
│         Recipe Editor · 3D Profile · Logs & Export · Settings                │
│  Widgets: ImageView (zoom/pan, overlays, ROI drawing, linked views)          │
│           BoxEditor (an ImageView with an NG image's defect boxes)           │
│           RoiEditor (the same, with a recipe's ROIs on the Golden board)     │
│  Workers: Worker wraps a core Job; its callbacks arrive as signals on the UI │
├──────────────────────────────────────────────────────────────────────────────┤
│ Application services  (aoi/core/services.py → AppContext): the only door     │
│  reads   board_models · samples · models · recipe · inspections · users      │
│          recipe_revisions (each with its changes and its reason)             │
│  writes  import_samples · train · save_recipe · set_reference · set_scale    │
│          add_user                                                            │
│          set_label · set_boxes (a label and its defect boxes, with history)  │
│          check_label · draw_ok_checks (a second user's check of labels)      │
│          make_calibration_set · label_blind · run_agreement_check            │
│          freeze_dataset (a frozen dataset version and its manifest)          │
│          lock_validation_set (a version's locked validation set)             │
│          create_store · restore_store_key · move_in · shred_store (Admin)    │
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
│  tuning.py    trains the comparison's two thresholds from labelled boards    │
│  jobs.py      background jobs: progress, cancel, finished callbacks; no Qt   │
│  run_progress.py a training run's percent and time left; no Qt               │
│  defects.py   DCT taxonomy, severities, mandatory AOI set                    │
│  crypto.py    file format 1: a dataset store's files, AES-256-GCM (ADR 0010) │
│  stores.py    the store a workspace file is in, its files and their headers  │
├──────────────────────────────────────────────────────────────────────────────┤
│ Data  (aoi/data/db.py)  SQLite: samples · models · recipes · inspections ·   │
│                         defects · test_runs · alarms · users · board_models  │
│  credentials.py  each dataset store's key: Windows Credential Manager        │
├──────────────────────────────────────────────────────────────────────────────┤
│ HAL  (aoi/hal)  Camera · LightingController · RobotController · MesClient    │
│   Stage 1: FolderCamera (images)   Stage 2–4: GigE/USB3, serial, RS-485, OPC │
└──────────────────────────────────────────────────────────────────────────────┘
```

Rules: pages call **only** `AppContext`; the engine has **no Qt imports**, so the same code runs headless
(tests, a future CLI, the Stage 3 robot cycle, or a Stage 4 MES service). `tests/test_layers.py` enforces both:
no Qt import under `aoi/core` or `aoi/data`, and under `aoi/ui` no `sqlite3` or `aoi.data` import, no `.db`, no SQL,
no `Inspector` built by a page (REQ-USR-001, since S15) and no image read outside `AppContext.load_image` (since S23c),
whatever module a name comes through, `Database` and the readers that services imports included, and a second test
fails a screen module that holds one of them once imported (#202). `aoi/times.py`, `aoi/errors.py`, `aoi/config.py` and
`aoi/defects.py` are shared by every layer.

Types (Code style, since S22): mypy runs strict on `aoi/core`, `aoi/data` and `aoi/times.py`, and since S22a on `aoi/ui`
and `aoi/hal` too, and since S56 on `aoi/selftest.py`, with no flag relaxed (`pyproject.toml`). PySide6 enums are
written in full (`Qt.AlignmentFlag.AlignCenter`), pages take `QT_TRANSLATE_NOOP` from `aoi/ui/pages/base.py` (Qt's is
typed as returning object; it is the one of `aoi/errors.py`, which returns a `Phrase`, a `str` subclass, so every page
title and role name is one), and no widget attribute carries a QWidget method's name: `size`, `pos` and `render` hid
`QWidget.size()`, `pos()` and `render()` on three pages until S22a, and `tests/test_screen_rules.py` now fails on one.
Since S22b every page is typed and no module is exempt, and ruff's annotation rules (all but ANN401) require a type hint
on every function argument and return value across the repository, `tools/`, `main.py` and `tests/` included; mypy does
not run there, so those hints are present, not verified.

An image file from outside is checked before it is decoded (REQ-INSP-001, since S23): `aoi/core/imaging.load_image` reads
the format and the size from the file's bytes, never from its name, and refuses a file over the byte limit or an image
over the pixel limit with `AOI-INSP-005` before a pixel is decoded, an image with a side over 1,048,576 px, the decoder's
own limit, with `AOI-INSP-007`, a file that holds no PNG, JPG, BMP or TIFF image with `AOI-INSP-004`, and a recognised
format whose header gives no size, or that the decoder rejects (cut short, damaged, a variant OpenCV does not read), with
`AOI-INSP-006`. Wherever a file can be read in two ways the header readers follow the decoders (stray bytes between JPEG
segments are skipped as libjpeg skips them, a TIFF size tag of any integer type counts, classic or BigTIFF (in a classic
file the 8 bytes of a LONG8 or SLONG8 are read where its entry points, as libtiff reads them), a TIFF that gives a size
tag twice is refused with `AOI-INSP-006` since libtiff reads the first entry (#169), a bitmap is known by its header
size), so the size measured is the size of the image the decoder returns. That bounds the image, not the decoder's work,
which three more checks bound before decoding, each refusing with `AOI-INSP-006` (#242): a JPEG with more than 100 scans
(`JPEG_MAX_SCANS`, libtiff's default for a JPEG inside a TIFF; libjpeg decodes every scan, each a pass over the image,
and its progression writes 10 for a colour image), counted as libjpeg reaches them, from marker to marker up to the
first end-of-image marker, so that no scan libjpeg decodes is missed while the scans of an EXIF thumbnail inside a
segment and the bytes after the image (where a phone's motion photo keeps its video) do not count; a TIFF whose tile
or strip, by which OpenCV allocates its buffer up to 1 GiB, holds more pixels than the larger of 1024 × 1024 and the
image with each side rounded up to a multiple of 16 (TIFF 6.0 makes tile sides multiples of 16, so a 64 × 64 image with
256 × 256 tiles opens), or that gives RowsPerStrip, TileWidth or TileLength twice; and a TIFF whose strips or tiles
share bytes of the file, or whose byte counts add up to more than the file holds. libtiff fills a whole tile, so a
64 × 64 TIFF declaring one 16000 × 16000 tile took about 1 GB of memory; of a strip it fills only the image's rows, so
for a strip the bound limits what OpenCV allocates (about 1 GB of address space for a 64 × 4,000,000 strip) rather than
the memory in use, which stayed near 56 MB on Linux. A RowsPerStrip of 0 or 4,294,967,295 reads as the image height, as
OpenCV reads it. The strip bound also refuses a short image whose RowsPerStrip is a constant well above its height, such
as 2,048 rows per strip for 640 × 480 px (a buffer of about 5 MB), although it decodes cheaply; no TIFF that Pillow,
tifffile or OpenCV wrote in testing was refused, and whether such a file must open is for Jay to decide. libtiff reads
and decodes each strip or tile from its own offset and byte count, whatever its compression, so strips that point at
the same bytes cost them once per strip: a 49 MP TIFF of 8 MB whose 1,048,576 one-row strips all pointed at one JPEG
stream of 99 scans held the decode about 69 s (the #242 review), and one-row strips sharing a 1 MB block about 70 s
uncompressed, as long with Deflate and far longer with PackBits. A TIFF of more strips or tiles than 4,194,304
(`TIFF_MAX_BLOCKS`: one-row strips of the tallest image in four planes), counted from the image as libtiff counts them
(tiles times ImageDepth over TileDepth, and times SamplesPerPixel when the planes are stored apart), is refused before a
list is read, since reading every value a list gives took the check 3.7 GB on a crafted 200 MB TIFF (the #242 stack
review); only that many offsets and byte counts are read, as libtiff reads them (StripOffsets and TileOffsets fill one
list, the one listed last counting, and libtiff pads the shorter list with 0), so values past them are ignored, as
libtiff ignores them, and the check holds about 40 MB at most; a MemoryError in it refuses the file too. A Compression
given once per sample (TIFF before 5.0) counts as compressed, so its byte counts are checked, and an uncompressed TIFF
of more than two strips whose first two byte counts differ is not checked, since libtiff then ignores its byte counts
and reads each strip at its size. Within the three bounds the decoder's work still grows with the file: the costliest
crafted file found, a 199 MB TIFF of one-row JPEG strips of 99 scans each, each in its own bytes, took about 10 s in
`load_image` on a busy 4-core VM, while one of 16,000,000 tiles of 1 × 1 px (192 MB, about 12 s) is now refused at once.
The checks run in `_decoder_work` before `cv2.imdecode` is called, and `tests/test_image_input.py` holds the
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
(Stage 2); `tests/test_layers.py` fails a page that imports `load_image` or `load_image_sha256` from any module,
calls one by its bare name or on anything but the context, or calls `cv2.imread` or `cv2.imdecode` (#202); and
`import_samples` copies a sample only once `imaging.checked_bytes` has made these checks and decoded the very bytes it
hashes (REQ-TRN-001, S31; the codes are Inspection's, decision Q30), and takes only a view of `aoi.hal.VIEWS`, as
written there (AOI-TRN-017), and a label of `LABELS`, OK or NG (AOI-TRN-018): a dataset version names its folders by
view, and the copy's folder is images/<board model>/<label>/, which must lie inside images/. A new board model's name,
from `ensure_board_model`, a first import, `set_reference` or `train`, is one folder name on Windows as on Linux
(`aoi/data/paths.py` `one_folder_name`, AOI-TRN-019); a name the workspace already holds is kept, and `train` writes
only inside models/. A source lost between its check and its copy is that file's AOI-INSP-001.
`import_files` imports a batch one `import_samples` call per file, each `ImportFile` with its own label, defect type
and view (`aoi/core/sample_import.py`), and returns an `ImportReport`: the files added, each file refused or skipped
with its `AoiError` (a code in `REFUSED`: Inspection's checks, AOI-TRN-013 to -018), the file another error stopped it
at, and the files left by that error or Cancel.

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
will appear (after 1 s the time so far; after 10 s a bar and Cancel, with progress and the time left only for a job
that reports steps: Training's sample import and the two Logs exports; Compare, the AI Model Test
preview and Recipe Test Run inspect one board, report no steps and show the seconds so far, #194; Compare's Re-evaluate
on a stored result, whose "Would be" shows within 300 ms of the key at 5 MP and can take over a second at 20 MP, has its
own over the decision table and the "why" box, where the checks tried appear, whose Cancel brings back the stored
checks, and Re-evaluate is off while it runs). Cancel drops the result and hands `on_cancel` what the job returned, so a
job that checks `should_stop()` says what it kept (the sample copies and Export Image Overlays:
`AppContext.import_samples` and `export_overlays` take `progress` and `should_stop` and audit `cancelled`).
`tests/test_no_freeze.py` ticks the UI thread every 50 ms through each page's 5 MP action (for
the Logs exports and the sample copies, enough 5 MP files to take over 2 s on the UI thread) and fails on a gap over
2 s; its `heavy_calls` helper wraps `AppContext.load_image`, `inspector`, `inspect`, `inspect_file`, `log_result`,
`import_samples`, `checks_for_many`, `export_csv_files`, `export_overlays`, `re_evaluate` and `Inspector.inspect`,
fails a page whose work reached none of them or ran one on the UI thread, and stalls the first engine inspection (or
sample import, or export) 2.5 s, so such work fails the gap budget too, on any PC (#208). A page job runs as the user
who started it, as every job does (#177), so a Switch User while an export or a
sample copy runs changes neither its role checks nor its audit entries, and `Page.update_actions()` runs as a job
starts and ends: Logs turns its two exports off, Training its three imports, its empty table's Import Folder… link
and Start Training, and Training's import slots return while one runs, so a second action cannot stop the first; an
`EmptyState` shown while a job runs (a refresh, Filter) raises a shown `BusyOverlay` of its host back above itself, so
"Importing…"/"Exporting…" and Cancel stay on top (#194, `tests/test_page_jobs.py`). No slot and no job function holds its own worker or the worker's signals (#132): Qt keeps a slot as long as the signals, which the worker holds, so a worker
its slot held would stay, with its job and the job's result, for as long as the app runs; and signals a job held would
be deleted with the job, on whichever thread let go of it last, where Qt forbids deleting an object of another thread.
The slots hold the worker by weak reference and a job function reports through a bound emit (`w.signals.progress.emit`,
bound once the worker is built), which does not keep the signals; `tests/test_background_results.py` checks that a
result is freed once the page shows another, and that a board that fails lets go of its worker's signals with the
worker. One call starts a thread of its own: `maps.load_maps`, run by a job, decodes a stored result's AI map on a
helper thread while the job decodes the difference map, and waits for it before it returns.
Python's cycle collector runs on the UI thread only (REQ-INSP-011): `main.py` calls `workers.collect_on_ui_thread`,
which turns the interpreter's automatic collection off and runs each collection that comes due, by the interpreter's
own thresholds, from a 200 ms timer on the UI thread. The interpreter starts a collection on whichever thread is
allocating when one comes due, and one started on a pool thread frees every reference cycle there, Qt objects of the
UI thread included, where Qt forbids deleting them: on Windows CI a pass that started while a job loaded the AI model
ended the process with an access violation (2026-10-09). The timer cannot see the interpreter's count of long-lived
objects, so it runs a full pass whenever its count is due (35 to 52 ms with the app's modules loaded), at most once a
tick. `tests/conftest.py` sets up the same for the suite, with a pass over the young generations after each test, and
`tests/test_collector.py` holds a job's cycles to the UI thread.
Closing the window stops the background work (#171): while a job runs `MainWindow.closeEvent` asks first (No keeps the
window open), then `AppContext.close` cancels every job, waits for it and closes the database and the log, and the slots
the jobs queued are dropped unrun, and the workers that waited for them let go (`workers.drop_queued`); `main.py` closes
the context again after the event loop (a no-op). A cancelled training run saves nothing (REQ-TRN-008), and the Training
page says so; an AI model test has no stop yet, so it finishes its folder first.

A control an operator uses by key and by touch is one `QAction` (`Page.action`, since S24): a window shortcut owned by
the page, so the key works wherever the focus is on the page and only while the page is shown, behind an
`action_button` whose label carries the key ("Next Board  F8") and whose enabled state follows the action's, so the
button and the key never disagree (REQ-INSP-005). The Inspection page answers within the action itself: the banner is
repainted grey with "Inspecting…" before the pool thread starts, and the verdict is painted before the image and the
defect table are built from the result (REQ-INSP-002); the engine is built on the pool thread and kept for the next
boards only while it is current: before each board the job asks `AppContext.engine_is_current`, a database read that
compares `Inspector.inputs` (the AI model's UUID, the recipe revision's UUID, the Golden board's path, the scale) with
the active AI model, the latest recipe, the Golden board and the board model's scale, and builds it again when a
training run, an activation, a saved recipe, a scale or a Golden board set made it stale (S29), so a board that starts
after such a change is judged with what is active; the board in
hand keeps the engine it started with, and a run in progress moves at its next board, with a line under the banner (the
status bar keeps the next board's busy line) and a WARN alarm AOI-INSP-013 (#243). Whether a run moved is decided on
`Inspector.judging_inputs`, which leave the AI model out while the recipe turns the AI check off: an activation during
such a run rebuilds the engine, so the boards after it name the version now active, but raises no AOI-INSP-013, as no AI
model judged them, and the line of such a run that moved says the AI check was off in place of an AI model (#246); they
leave the scale out while the recipe holds no size in mm, which is all a scale sizes (S29). A new
queue, a board model change or a revisit drops the engine (a generation counter, so an engine a board is building
meanwhile is never kept), and one worker runs at a time per page (#120). A board model with no AI model gets its WARN
alarm AOI-TRN-003 once per page visit and board model, not for each engine a new queue builds. AI Model Test asks
`engine_is_current` the same of the `JudgedBy` that `AppContext.batch_test` returns with a run (the recipe revision,
Golden board and scale that judged it, the AI model version active then and, in `use_ai`, whether the recipe ran the AI
check), so
both pages agree on when a result is current (#250); for a run whose recipe turned the AI check off, the page then
compares its recipe revision, Golden board and scale alone, as no AI model judged it (#246), and it passes over a scale
set since for a recipe that holds no size in mm (S29). `tests/test_run_controls.py`
measures both budgets.

Compare shows each view within 300 ms at 5 MP (REQ-CMP-002, since S27b). `aoi/core/views.py` draws the two heat views,
the board under its difference map or its AI score map, and `heat_overlay` blends the colours in with OpenCV
(`cv2.blendLinear`): about 25 ms at 5 MP against 130 ms for the NumPy blend before, on the 4-core cloud VM the tests run
on (not the reference PC). The page keeps the views it drew for the result shown, one per view and pixel difference, so
switching back only shows the picture again, and drops them when another result is shown; `tests/test_compare_views.py`
times each view until both panes are painted, the median of five openings of a stored 5 MP result.

Colours, point sizes and size classes are tokens in `aoi/ui/theme.py` (REQ-SET-004, since S18): the stylesheet is
built from the tokens in use (the presenter theme's below, REQ-SET-008) with `theme.stylesheet()`; a page never writes a
colour or a point size of its own, nothing is below 14 pt, and `tests/test_screen_rules.py` scans aoi/ui for a
literal (a hex, rgb(), hsv() or hsl() colour or a colour name in a string, in any case as Qt reads them; a
`Qt.GlobalColor` member in any spelling; a QColor, QBrush or QPen, `setNamedColor()` or a `QColor.from…()` factory
built from a constant; a self-test lists each spelling, #203) and checks that every page sits in the one frame
(REQ-SET-018). A verdict is shown as its colour with a shape and the word
(`theme.verdict_label`: ✓ OK, ✗ NG, ▲ WARN; REQ-INSP-002), each page has one blue `primary` button, and a button that
removes data is a red `danger` button, last in its row and never the default; a question that removes or overwrites
data passes its buttons with No as the default, so Enter keeps the data (#182). A disabled button of every kind greys out
to `BG_RAISED` and `TEXT_DISABLED` (`QPushButton#primary:disabled` and its siblings outrank the coloured ID rules), and
a selected row, selected text and a combo box's highlighted entry are white on `BG_SELECTED` (the `selection-*`
properties on `*`), never the platform's highlight (#203). The list a drop-down opens, the calendar of a date field
and every menu (the calendar's month list, a text field's right-click menu) are themed too: `TEXT` on `BG_DEEP` or
`BG_RAISED`, never the platform's light background; the days outside the shown month are `TEXT_MUTED`, and Logs &
Export sets its weekend days to `TEXT` instead of Qt's red (#239). The calendar's navigation bar stays on `BG_SELECTED`
with the month and year in `ON_DARK` (5.7:1), on `BG_BUTTON_HOVER` under the pointer or while the month list is open
(8.4:1): Qt draws the previous and next month arrows dark, and they read at 3.4:1 on `BG_SELECTED` but 1.5:1 on
`BG_RAISED`, below the 3:1 a control's graphic needs (WCAG 1.4.11) (#239). The sidebar's section headings are `TEXT_MUTED`; a
page entry the role may not open is greyed to `TEXT_DISABLED` by `MainWindow.set_user` on the item itself, because a
stylesheet rule for disabled items would grey the headings, which have no item flags either (#239). A board that could not be judged shows
`Page.not_inspected` on its banner (· Not inspected, in the neutral colour) with its picture and verdict table cleared,
never the verdict of the board before (#182), and its empty state (Inspection, Compare's test pane) names the board, the
error's code and what happened, translated through `phrase_text()` (#198); `run_in_background(on_error=…)` lets a
page clear what the job was to replace before the coded dialog opens (an error in `on_error` itself is reported, and the
dialog still opens). The error of a run the user cancelled, or a newer call replaced, opens no dialog but still goes
through `report_error` (an `error.shown` line with the trace, an ERROR alarm), as does the error a stopped folder import
returns to `on_cancel` (#206). Every empty page, list and
image area shows an `EmptyState` (`aoi/ui/widgets/empty_state.py`): what is missing, what to do next and one link
button to the page where it is done; `Page.empty_step` turns "do this on <page>" into that link, or into "Ask an
Engineer …" for a role that cannot open the page (REQ-SET-019, since S18c). With no board model the header list is
empty, so `Page.no_board_model()` gives Home, Inspection, Training, AI Model Test and Recipe Editor one next step by
role: "+ New board model" for an Engineer or Admin, "Ask an Engineer to create one." for an Operator (#200).
Inspection's Start and Next Board (F5, F8) stay grey with no board model, even with images queued, and
`on_board_model_changed` sets them again on every change, so they come on once the first board model is created; an
action that needs a board model and finds none (`Page.need_board_model()`: Training, AI Model Test, Recipe Editor, and
as the backstop of a direct call Inspection and Compare's Save to Recipe, whose buttons stay grey with no board model,
S28d) shows AOI-SET-014, whose step every role can take (#244). Logs &
Export's "No records match" offers Reset Filters only when its last-7-days filter would show rows; when every record is
older or archived, Show All Records sets the dates around every record and Include archived instead (#200). The block is as wide as its text would
like within the area and as tall as its text wraps to at that width; a word wider than the area runs past the edge,
and every line shows while the area is tall enough (since S27a-2).

The light presenter theme (REQ-SET-008, since S54) is `theme.PRESENTER`, overrides of the tokens: a #FAFAFA page,
text 18 pt or more (`FONT_PT` 18), the verdict at 48 pt, the same verdict colours and shapes, and every text colour at
4.5:1 or more on its surface, bold and large text included, with black (`ON_DARK`) on the green, red and blue fills
(Q53) and `ACCENT_TEXT` for the Home card numbers. `settings.json` holds it as `presenter_theme`; an Admin switches it
with Settings' Presenter theme tick and leaves it with the header's Exit presenter theme, both through
`MainWindow.save_presenter_theme` and so through `AppContext.save_settings` (Admin, audited as `settings.change`; Q49).
`theme.use()` puts the tokens in place: before anything is drawn when `MainWindow` is built with it saved on, or at once
in `MainWindow.apply_theme`, which applies `theme.stylesheet()` to the application and draws again what the pages drew
with the tokens: verdict labels (`theme.verdict_styles()` maps each verdict stylesheet to its maker), coloured table
rows (`restyle_table`: fill, text colour, bold font at the new size, columns resized), the background, hint and box
labels of every `ImageView` (`restyle`; the box editors draw their boxes again), and each page's own `Page.restyle`
(Home's card headings, AI Model Test's tiles, Logs & Export's weekend days). The sidebar then hides the Admin pages and
3D Profile (Roles, below). `tools/render_screens.py` pins the font by patching `theme.FONT_FAMILY`, so a theme switched
on during a render keeps it, and renders three presenter shots (`PRESENTER_SHOTS`: `presenter-<page>-<role>.png`);
`tests/screens/test_sizes_and_contrast.py` walks every page the presenter theme shows, for every role, with large text
held to 4.5:1 too, and reads a widget's rounded corners as its fill.

Every page is rendered offscreen for every role that may open it and compared with an approved image (REQ-SET-004,
since S21): `tools/render_screens.py` builds the synthetic workspace with pinned ids, times, inspection time and fonts
(DejaVu Sans without hinting on Linux) and inspects with a pixel-based stand-in for the trained model (`PinnedModel`: the
seeded training's float rounding differs by CPU type, so a trained model's verdict and boxes differ between machines; the
stand-in's quantised 8-bit difference from the golden board, with wide margins to its thresholds, shows the same verdict,
boxes and scores everywhere, and the similarity (SSIM) and alignment points that the float alignment still moves
are pinned too, `FIXED_SSIM` and `FIXED_INLIERS`), and `tests/screens/test_screens.py` compares the 1920×1080 renders
with `tests/screens/approved/` on Linux. A pixel differs when a channel moves by more than 40 levels, and a page fails
when more than 4 differing pixels touch (since #175; before, only when 0.5 % of the page differed, which a changed
word or number never reached): one changed digit at 14 pt makes a cluster of 10 px or more, while what moves between renders
does not (nothing on one machine; single pixels of the board picture with OpenCV and NumPy held to SSE3). The new
images with a diff per failing page stay in `tests/screens/actual/`, which CI uploads. An intended screen
change is approved with `python tools/render_screens.py --approve`; the images are generated files that Jay approves by
merging. On Linux, CI also renders every page at 1366×768 and at 3840×2160 with 150 % and 200 % scaling into the
`screens-review` artifact of the run (kept 30 days), which is how the layouts are checked at the standard's other sizes
(#104 records that the pages do not yet fit 1366×768). `tests/screens/test_sizes_and_contrast.py` walks the same pages on Linux and Windows and measures every visible
widget against the standard's "Sizes": 14 pt text (QGraphics text on an image takes `label_font()`), 120×40 buttons whose
text fits, 48 px operator targets (sidebar entries, header controls, defect and history rows, the Inspection source
bar), 56 px run controls, and every visible control of size class T, T+ or F, named or not, to its class (#240), and
WCAG 2.1 contrast of 4.5:1 between a widget's pixels and its background (3:1 for bold or 18 pt text; disabled controls
exempt, but a disabled button must show the disabled fill), a progress bar's centred percentage included. A label is
measured as a whole, line by line and, for rich text, in each colour its HTML sets at that text's own size and weight
(on the text's own background where the HTML sets one, and in the label's own colour on a background the HTML sets
alone), so a second colour beside a stronger one is read too. Text drawn on an image is measured in its own colour
against the pixels under its glyphs, found by drawing it in two far-apart colours, so text in its ground's own colour
is found too: its dark backing, or the board where none is drawn; the 10th percentile of those pixels' ratios decides,
so a label partly over a bright part of a board is read there (#240). The prepared
states hold a selected defect row on Inspection and a bar at 100 % on Training, so both are measured (#203), and
Training's import sheet open on the synthetic dataset's train folder (S31). Every list
item with text is measured, the sidebar's section headings too; only a sidebar entry of a page the role may not open is
exempt, as a disabled control. The walk opens every drop-down list and every date field's calendar on the page, with
the calendar's month menu, and one text field's right-click menu, and measures each entry, day, weekday name and the
month and year, these also under the pointer (Qt's `WA_UnderMouse`, which drives `:hover`): they are windows of their
own, so the page grab does not hold them. The calendar's previous and next month arrows, which carry no text, must read
at 3:1 on their ground, at rest and under the pointer (#239). On
Windows, CI points `QT_QPA_FONTDIR` at the system font folder: Qt's offscreen platform ships no fonts
there, and without fonts every text is a box that reads as -0.8 pt, so the walk asserts first that fonts loaded.
A control's size class is set with `size_class(widget, "T")` (48 px), `"T+"` (56 px) or `"F"` (40 px, the AI score
threshold's tick, as tall as the fields), which the stylesheet sizes through `[sizeClass=…]` rules; `setMinimumHeight()`
on a styled widget is undone when the stylesheet is applied. A radio button of class T is drawn as a segment (the
import sheet's View and Label for all, S31): no indicator, the checked one filled with the selection colour.

### Workspace on disk

```
AOI_Workspace/                 (default ~/AOI_Workspace, set in Settings, used from the next start, or AOI_WORKSPACE)
  aoi.sqlite                   database
  logs/aoi-YYYY-MM-DD.jsonl    JSON-lines log, one file per UTC day (REQ-LOG-004)
  settings.json
  images/<board>/<OK|NG>/      uploaded training samples (copied in, so source folders can move), each named
                               <stem>_<sample UUID>.<ext>; a copy whose path the system refuses as too long stops
                               the import with AOI-TRN-011 (#245). Once an Admin moves the board model into a
                               customer's dataset store, each file is in file format 1, encrypted under the store's
                               key, and opens only in the app (REQ-TRN-017, ADR 0010)
  models/<board>/<board>_vX.Y.pt            trained model + calibration: tensors and plain values only, loaded with
                                            torch.load(weights_only=True) after its zip CRC-32s check; a file that
                                            is cut short, changed or unusable, has an entry flagged as a folder, or
                                            holds another AI model than the UUID its registry row names is refused,
                                            AOI-TRN-001 (REQ-TRN-014)
  models/<board>/<board>_vX.Y_golden.png    learned golden template
  results/<date>/*.png         overlay per inspected board, <stem>_<record UUID>_<verdict>.png, with its
                               *_diff.png and *_ai2.png maps (REQ-INSP-012; *_ai.png before S28a). <stem> is the
                               first 40 characters (STEM_CHARS) of the board's file name without its extension, so
                               every name, the temporary one included, is at most 225 bytes; the UUID is the record's,
                               as its uuid column and the CSV export give it, so no two records share a file. A save
                               never replaces a file (a name already taken refuses it), and a path the system still
                               refuses as too long is AOI-INSP-014 (#245; before: 6 random hex digits, whole stem)
  exports/                     CSV / PDF / overlay exports
  datasets/<name>/manifest.json  a frozen dataset version's manifest (REQ-TRN-005): each file's path, relative to
                               the workspace, SHA-256, label and boxes; the files stay where images/ holds them.
                               Encrypted as they are, in its board model's store (REQ-TRN-017)
```

### Demo workspace (REQ-SET-007, REQ-SET-009; S53)

The build runs `tools/make_demo_bundle.py`, which makes `demo-bundle/` and fails unless its boards get the verdicts the
demo needs; PyInstaller ships it beside the app (`aoi/core/demo.py` `bundle_dir()`; `AOI_DEMO_BUNDLE` overrides it). It
holds `bundle.json` (format, app version, board model DEMO-TBOX-A1, the ten boards in run order with their verdicts,
and the SHA-256 of every other file), `store-key.json` (the key of the demo's dataset store: synthetic boards, ADR 0010)
and `workspace/`, a workspace as the app leaves it with an AI model, its card and Golden board, and `demo-boards/`.

Settings › Demo (Admin) loads it in one click into `<workspace>-Demo`, a folder beside the station's workspace and never
inside it, marked by `demo.json`; a folder of that name that holds files and no `demo.json` is refused (AOI-SET-016),
and a bundle whose files do not match its manifest is refused before anything is written (AOI-SET-015). The window
then switches workspace (`MainWindow.switch_workspace`): the station's context closes, `config.use_workspace()` makes
the demo folder the default workspace, so its own `settings.json` is read and written, and a new window opens on the
same page as a user of the same role, with a Demo badge in the header. The store's key goes to the station's key store
at each load and reset, never into a workspace. Reset Demo (red, confirmed) closes the demo, deletes every file in it
but `settings.json` and `demo.json`, copies the bundle's workspace back (under 10 s; AOI-SET-017 for a file another
program holds) and audits `demo.reset` in the demo's database; Leave Demo Workspace opens the station's again.
`main.py --demo` starts in the demo, loading it first, so a presenter whose app crashed is back in it in seconds.

The demo's boards wait on Inspection as a scripted run (`InspectionPage.play`) at `demo_pace_s` seconds per board (1
to 10, default 3; Settings › Demo's slider), through the normal path: each board inspected, saved and alarmed. The run
pauses at an NG board, so Compare can show why, and Start goes on. A queue the user loads has no pace.

---

## 3. How the app "trains itself" (Stage 1 AI)

Customers usually have many good boards and very few defective ones, and most of the 33 DCT defect types will
have no examples at PoC start. So the default model learns **what a good board looks like** and flags deviations,
instead of needing labelled examples of every defect.

```
Upload OK images (+ optional NG), label, freeze a version, lock its validation set      Training page
        │
        ▼
0. Check the version from its rows: locked, ≥ 20 OK in its training set, one customer's store, an allowed use
1. Register each training image onto one reference board (ORB features + RANSAC homography), one at a time
2. Golden template  = per-pixel median of the aligned OK boards, a band of rows at a time → *_golden.png
3. Autoencoder      = learns to reconstruct OK boards at the input size (lighting jitter augmentation)
4. Normal variation = per-pixel mean/std of reconstruction error on OK boards (summed in float64)
5. Calibration      = threshold from held-out OK scores (mean+3σ, ≥1.05×max OK);
                      if labelled NG exist and separate cleanly → midpoint between OK and NG
6. Register version vX.Y in the model registry, inactive, with its card     → *.pt, *.card.md, *.card.json
```

Re-training after more uploads creates a new version; older versions stay selectable (model version control, GUI §6).
A frozen version holds each sample's label at its freeze (`labels`, since S32): the OK and NG images; an image labelled
UNSURE is in neither, so it is left out of training and of the OK images held back for calibration in step 5, its
validation part, and `AppContext.unsure_samples` lists it for the customer's quality engineer (REQ-TRN-002).
A second user checks labels (REQ-TRN-004, S34): `check_label` records the user acting against the current label row,
never its labeller, so a relabel needs a new check; `draw_ok_checks` draws OK labels at random with a recorded seed;
`labels_ready_to_freeze(board_model, view)` is True once every NG label and drawn OK labels numbering 10 % of the OK
labels, rounded up, are checked, and never with no OK or NG label. A view other than `aoi.hal.VIEWS` is refused.
Until sign-in ships at 1.0, the second user is a second name picked under ADR 0002, not a proven person; the
validation report (S48) says so. Training's samples table names each image's labeller and checker, Draw OK Labels to
Check and Check Label call these two, and Show › Unchecked lists what `label_check_status` still counts against a
freeze (Datasets stage, 1 of 4).
Two labellers agree before a customer validation (REQ-TRN-016, S34): `make_calibration_set` fixes 100 images
(proposed) labelled OK or NG, each labeller records a blind label of every image (`label_blind`, kept apart from
`labels`), and `run_agreement_check` stores the counts: OK/NG agreement against 98 % and defect-type agreement on the
images both labelled NG against 90 % (proposed), compared in whole numbers (`labels.agreement`). The check is stored
on its own, keyed by its calibration set and board model; the newest one whose set holds images of a view decides
whether a version of that view is frozen, and the version names it (S35). `propose_calibration_set` draws a set to
make, at random with a seed: 30 NG images, or every one when fewer, the rest OK, more NG where the OK images run short,
in a random order (`labels.draw_calibration`); `blind_labelled` names the images each user has labelled blind, never
the labels (Datasets stage, 2 of 4). Training's Datasets tab does all of it on screen: New Set, Label Blind…, whose
panel shows each image with nothing that names its label, and Run Agreement Check (section 5, Training).
`freeze_dataset` (REQ-TRN-005, S35) is refused while `labels_ready_to_freeze` is False (AOI-TRN-020, -021), with no
customer (AOI-TRN-024), a view outside `aoi.hal.VIEWS` (AOI-TRN-038), a board model whose name has no Latin letter or
digit (AOI-TRN-039) or gives the letters and digits another board model's versions are named with (AOI-TRN-040), and
while the newest agreement check of the board model whose set holds images of the view is missing or short of its
targets (AOI-TRN-027); else it names the version `DS-<BOARDMODEL>-<REV>-<VIEW>-v<N>` (`aoi/core/datasets.py`). The
refusals that need no file come first, so a freeze they refuse reads no image file first; then it hashes the files and
works out their stored paths with no lock held, `progress(done, total)` following each file, and once `should_stop()`
is true it hashes no other and returns None, nothing written. `freeze_gate` gives what Freeze Dataset… shows before a
freeze, writing nothing: the name it would make, its files, the label checks, the newest agreement check, the store and
the refusal those same checks would raise now. Then, holding the database lock, one transaction finds N, checks the
gate again, reads the labels and, in one query, the boxes, stores the version and its files with the manifest's SHA-256
and the audit entry, and moves `datasets/<name>/manifest.json` (each OK and NG file's relative path, SHA-256, label row,
boxes, labeller and checker; the agreement check; the OK draws) into place just before the commit (`atomic.staged`); a
failed commit puts back the manifest it replaced before the lock is released (`Database.locked`), so no other freeze
comes between. A freeze that dies before the move leaves no manifest; one that dies between the move and the commit
leaves a manifest that no `datasets` row names, which is how such a leftover is known (`verify_dataset` reads only the
manifest a row names), and the next freeze of that name replaces it. Every other database call waits while the lock is
held, for those reads, the manifest's write and fsync and one insert per file: about 0.3 s for 3,000 files on the
development VM, so some 2 s at 20,000. AOI-TRN-041 for a manifest not written, AOI-TRN-042 for a path too long. A
version's rows and manifest never change, and a later label change reaches only the next version. A version names the
workspace's image files rather than copying them, and the app changes one only to encrypt it where it is, to the same
plain bytes (`move_in`), and removes one only when its store is shredded (`delete_sample` keeps the file), so a file
changed or removed outside the app is what `verify_dataset` reports: it re-hashes the manifest and every file against
the stored SHA-256 and lists the files that match, changed or are missing, and writes nothing; it takes `progress` and
`should_stop` too, `left` counting the files a stop left unhashed. `dataset_counts(board_model)` counts each version's
OK and NG files, those of its locked validation set and whether it is split, in two queries, for the Datasets tab's
Versions table, and `datasets.mismatch` makes AOI-TRN-023 of what `verify_dataset` found (Datasets stage 4 of 4).
The old bytes of such a file cannot be recovered from the workspace, which therefore needs a backup. How labels,
checks, agreement checks and frozen versions are stored, and why, is
[ADR 0009](adr/0009-labels-checks-and-dataset-versions.md) (proposed). How each customer's dataset store is encrypted at
rest, with one key per store kept in Windows Credential Manager, is [ADR 0010](adr/0010-customer-dataset-encryption.md).

**Customer dataset stores** (REQ-TRN-017, S38). An Admin makes one store per customer at a time (`create_store`, a
customer's name in any case and spacing being one customer): a random 256-bit key, saved in this station's key store
(`aoi/data/credentials.py`: Windows Credential Manager as `AOI/dataset-store/<store UUID>`, memory on Linux) and never
in the workspace, and a `dataset_stores` row with its key id and check value. The call returns the recovery sheet once,
the key as 52 base32 characters, and `restore_store_key` takes it back on a new PC or Windows account once the check
value agrees. `move_in(board_model, store)` puts a board model in a store for good and encrypts each file under
images/<board model>/ and each of its manifests where it is, in file format 1 (`aoi/core/crypto.py`: a 34-byte header,
AES-256-GCM, the header, store UUID and workspace-relative path as associated data); each file is read back and
decrypted before it replaces the plain one, and calling it again finishes an interrupted move: `progress(done, total)`
follows each file, and once `should_stop()` is true the rest stay plain and the result counts them (`left`) until the
move is finished. From then on an import
writes its copy encrypted, and every read of a store's file (`_plain_bytes`: an image loaded, hashed for a freeze or a
verify, sized for a box, read for training) decrypts it in memory. A file that does not open is AOI-TRN-025 naming why
(no key, another key, not encrypted, another store's key, changed, moved or damaged), never read as plain. The plaintext
SHA-256 stays each file's identity. A board model in no store stays plain, and `freeze_dataset` refuses it, or one in
another customer's store than the version names (AOI-TRN-027), so a frozen version is one customer's, encrypted.
`shred_store` ends a store: it deletes the key first, records the shred (`store_shreds`, `store.shred`), then deletes
the board models' images, their versions' folders and their AI models and golden boards under models/. A file of it is
AOI-TRN-025 "it was shredded on <day>" from then on, and calling it again finishes a shred stopped part-way;
`store_contents(store)`, a read, names what it would delete now (the customer, the board models, and the file and AI
model counts, 0 once deleted), for Shred Store… to say before it does. Settings › Dataset stores
(`aoi/ui/pages/settings_stores.py`, Datasets stage 3 of 4) takes these steps on screen, Admin only, each an inline sheet
in the table's place: New Store… with the recovery sheet once and Print Sheet…, Restore Key…, Move Board Model In… on
the pool (Cancel stops it through `should_stop`) and Shred Store…. The rest of models/, results/ and `aoi.sqlite` stay
plain (ADR 0010, Consequences).

`lock_validation_set(dataset_uuid, seed)` (REQ-TRN-006, S36) splits a frozen version once into its training set and
its locked validation set, with the seed drawn and recorded when none is given (`datasets.split`): at least 50 OK files
and 30 % of its NG files, rounded up, the NG spread over their defect types (an NG file's type, else its boxes' types)
in proportion where the files allow. A file whose SHA-256 an earlier split locked is locked again, and counts towards
those numbers; files an earlier split put in training are drawn last, so a later version keeps its validation set.
It is refused with AOI-TRN-022, writing nothing, for a version the workspace does not hold, one split already and one
of under 50 OK files. The split and the part each file is in are stored with the audit entry (`dataset.lock`: seed and
counts) in one transaction, and their rows refuse to change or go, so a new split needs a new version. Training
refuses to start with AOI-TRN-043, before step 1 and saving nothing, while any file of the version's training set is, by
its frozen SHA-256, in any locked validation set, whatever its path or board model.

**Training from a frozen version** (REQ-TRN-007, REQ-TRN-017, S39). `train(dataset_uuid, epochs, image_size, progress,
should_stop, use="own")` trains from one version's training set; its validation set is never read. Step 0 refuses,
from the rows alone and before any image is read, saving nothing, for the first of these: no such version
(AOI-TRN-045); a board model name the rule for a new one refuses (AOI-TRN-019, AOI-TRN-005); the board model in no
customer's dataset store, in a shredded one or in another customer's than the version names, or a use the version does
not allow (AOI-TRN-046, audited as `training.refused` in a transaction of its own); no locked validation set, or fewer
than 20 OK files (`datasets.TRAIN_OK`) in its training set (AOI-TRN-045); a training file whose SHA-256 any split
locked (AOI-TRN-043, above). A name the workspace held before names were checked passes the name rule, but one that is
not one folder's name, such as TBOX., whose folder Windows names images/TBOX, never reaches a store (`move_in` refuses
it with AOI-TRN-019), so it does not train. A split locks at least 50 OK files, so a version trains only with 70 OK
files or more.
Each file is then read through its store and its SHA-256, of the bytes read, checked against the one frozen: another
file in its place stops the run with AOI-TRN-045 naming it. The OK files make the Golden board; three quarters of them
train the AI model and the rest are held back for step 5, which the NG files only calibrate. The AI model's metadata
and its `model.train` entry name the version (`dataset`, `dataset_uuid`) and the use. `training_version(board_model)`
is the newest version with a locked validation set, which Training picks first in its "Dataset version" list of the
board model's versions, newest first; Start Training trains the one picked.
A run holds one image at the camera's resolution at a time. Step 1 reads an OK file, registers and warps it, and keeps
its homography, its tensor at the input size (`anomaly.prepare`) and its rows of the first band of the median
(`golden.Median`: at most `golden.BAND_BYTES`, 1 GiB, for every OK image together), then drops it; each later band
reads the OK files again and warps them with the homography kept, to the same bits as aligning them afresh. Steps 3 to
5 work from the tensors, and step 5 makes one anomaly map at a time and keeps only its largest values for the pixel
threshold (`anomaly.top_percentile`, numpy's percentile to the bit). Memory therefore does not grow with the number of
images ([measurement](tests/2026-10-09-training-memory.md)).
An AI model the loader would refuse, such as one with an image threshold of 0 from OK images that are copies of one
photo, is refused at step 5 with AOI-TRN-004: nothing is saved, registered or audited, and the active version stays.
Step 6 writes the version's model card (`aoi/core/model_card.py`, REQ-TRN-011) and registers the version inactive with
`model.train` in one transaction: if it fails, the run's four files are removed. The Engineer activates it
(`activate_model`), or rolls back to the version active before (`rollback_model`): either switches the AI model and its
Golden board together, audited, and refuses a version without a card (AOI-TRN-049) or whose Golden board cannot be read
(AOI-TRN-048) (REQ-TRN-010). A version
never takes a name whose `.pt` or `_golden.png` is on disk, so a golden board a result names is never written over (#178).
The reference image an Engineer sets (Set Reference) must be an OK sample (AOI-TRN-006): inspections compare against it
at once, and step 1 aligns to it. While a sample is the reference, it cannot be relabelled NG or removed (AOI-TRN-007).

**Training as a job** (REQ-TRN-008, S40). `start_training(dataset_uuid, epochs, image_size, use, listen)` runs `train`
as a `Job` on the context's pool, not a page's: `AppContext.training` holds the run started last and `training_progress`
its latest report, so the run goes on whatever page is shown, and a second run while one goes on is refused with
AOI-TRN-047 before anything is read. `listen(job)` registers listeners before the job is submitted; Training follows the
job through `Worker.of(job)`, a worker around a job already made, kept by `workers.keep`. `train` reports a
`RunProgress` (`aoi/core/run_progress.py`: the percent of the time gone, never falling, the seconds left, a phrase
naming what the run does now and a line for the log) after every image read (the reference board, each OK and NG image,
and each OK image again for each later band of the Golden board), every step of a band's median (`golden.Median` works a
band out `golden.STEP_BYTES`, 64 MiB of rows of every image, at a time: about 0.85 s for 50 images at 20 MP on a 4-core
cloud VM, where a whole band of 1 GiB took 15 s), every training step and every calibration map, so no two reports are
further apart than the longest such step. The time left counts the steps of each kind still to do at that kind's mean
time so far; a step of the median, a training step and a map are timed first on the first image read (`Median.probe` on
noise, `anomaly.probe` on a throwaway network, its second step, as the first in a process also starts PyTorch's
threads), so it is known from the second report on and "estimating…" shows only before it. `should_stop()` is asked
after each report, so Cancel stops the run after the step in hand, raising `JobCancelled` with nothing saved, registered
or audited; it is asked for the last time once the AI model's files are written, which a cancelled run then removes, so
only the registering transaction cannot be cancelled. MainWindow reads both every second (a `QTimer`): the header shows
"Training 38 % · about 6 min left" on every page, a click opening Training, and Home's Self-train card "Training running
38 % · about 6 min left"; both hide once the run ends. `tests/test_training_job.py` runs 20 OK boards on a fake clock,
each step taking over twice what it took at 20 MP on that VM, through every phase, cancels in each, starts a second run
during one and changes page during one. With 50 OK and 3 NG synthetic boards on that VM, reports came at most 4.1 s
apart at 20 MP and 3.5 s at 5 MP, the longest being the first, over the reference board's read and the probes, and the
time left read at most 54 s over at 20 MP, while the images were aligned
([measurement](tests/2026-10-09-training-progress.md)).

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
| Difference regions | Compare | NG if > 0 | Number of difference blobs ≥ *Min defect area* (40 px; at a scale, the area of a round defect *Minimum defect size* mm wide) |
| Alignment inliers (shown as "Alignment points") | Compare | info; WARN if < 12 | Confidence that the board was registered correctly |
| AI anomaly score | AI | NG if ≥ AI score threshold (the recipe's override, else the AI model's calibrated value) | 99.9th percentile of the anomaly map (σ above normal variation) |
| ROI *name* [type] | ROI | NG if ≥ ROI AI Score | Strongest anomaly inside the ROI, as a multiple of the AI score threshold the AI check used |
| Inspection time | System | spec < 1 s | GUI §11 acceptance criterion |

The AI score threshold is the AI model's calibrated value (section 3, step 5) unless the board model's recipe overrides
it (REQ-TRN-015, `Recipe.anomaly_threshold`; none, or 0, is no override). The Recipe Editor and Compare name the
calibrated value from the AI model registry (`AppContext.calibrated_threshold`), where training stores it from the AI
model file's metadata in the same run, and the engine applies the file's. With no override, a newly trained or activated
AI model's value judges the next board; an override judges on Inspection, Compare, Re-evaluate and AI Model Test alike,
since each judges by the board model's recipe (Compare and Re-evaluate by the thresholds its form holds, loaded from it,
the override as the recipe holds it until it is edited). Re-evaluate keeps the calibration of the AI model that judged
the stored result (ADR 0006 decision 2), and Compare's field names that value while it shows a result that AI model
judged, and the active AI model's on any other board, a stored result judged with the AI check off included (#246). A
registry row without a usable calibration (an AI score threshold and a pixel threshold, both above 0, as Re-evaluate
needs them; only a row changed by hand lacks one) is AOI-TRN-012 wherever the value is shown: in the note under the
field's tick with what to do, and in Training's Threshold column, which reads its rows with `AppContext.calibration_of`;
an override can still be set and saved. Setting, changing and clearing the override are audited as `recipe.ai_threshold`
(section 5).

The Compare page's "why" box explains the verdict in plain words (`aoi/core/explain.py`, REQ-CMP-004): under the heading
"Why this board is NG:", a bulleted sentence per NG check, then per WARN check, naming the check, its value and its
threshold with their unit (an ROI's value as a multiple, ×, of the AI score threshold: the recipe's when an Engineer
sets one, otherwise the AI model's, as the Recipe Editor's ROI field says; a stored result does not record which, so the
sentence names neither, #248); with no failing check, that every check that decides the verdict is inside its threshold,
or that defects above Minor severity make the board a WARN; then one sentence per check that did not run, with what to
do, which the Inspection page shows under its summary too; a result judged with the AI check turned off in the recipe
says so (`AI_OFF_NOTE`, #246), since its record still names the AI model version active then; for a board they inspect,
both pages say what is set today. On a stored result, which "Compare with Golden board ›" and Use Last Inspected open
even right after an inspection, Compare asks for them with `explain(res, stored=True)`, which says what was set when the
board was inspected ("No AI model was trained for this board model when the board was inspected", "The recipe turned the
AI check off when the board was inspected"), since an Engineer may have trained one, or turned the AI check on, since
then. Each sentence is an English template with named values, which a screen translates under the context "Explain"
before filling it in, so the engine stays free of Qt and a translation can put the values in its own order.
On what other thresholds give a stored result (Compare's Re-evaluate), `explain(res, stored=True, tried=True)` says that
defects which make a WARN would be marked by those thresholds and that the boxes on the board are the stored result's,
as the stored board picture has them drawn in, and that their recipe turns the AI check off as "The recipe turns the AI
check off, so these thresholds judge the board without it", true whether or not it ran when the board was inspected,
since `re_grade` notes it from that recipe (#246).

Sizes in mm (REQ-RCP-006, since S29): a board model may have a scale, `board_models.px_per_mm` (migration 0012), which
an Engineer sets from a known length on its Golden board (`AppContext.set_scale`). A recipe then holds its minimum
defect size in mm (`Recipe.min_defect_mm`, the width of a round defect) and each ROI's place and size in mm (`ROI.mm`),
and the engine applies them in px at the board model's scale (`Recipe.in_px`, in the `Inspector`): the minimum defect
area becomes the area of a round defect that wide, rounded up so that a defect of exactly that size is kept
(`disc_area`; 1.67 mm at 4.27 px/mm is the default 40 px), and an ROI's box is its mm times the scale, to the nearest
px. A size the recipe holds in px, and every size without a scale, judges exactly as before, and a recipe with no size
in mm is stored without the new keys. Each result keeps the scale it was judged at (`InspectionResult.px_per_mm`, in
`result_json`; `from_dict` refuses one that is not a number above 0 with ValueError, as a damaged time, which
`AppContext.inspection_result` raises as AOI-CMP-002, so that Compare and Re-evaluate say to inspect the board again);
`re_evaluate` applies the thresholds' sizes in mm at that scale, or at the board model's now for a result judged without
one (which the result it returns keeps), so a scale set later does not change how a stored result is judged again, and
`engine_is_current` counts the scale, so Inspection judges the next board at a new one.
`set_scale` refuses a scale outside 2 to 100000 px/mm (AOI-RCP-008): from 2 px/mm no ROI of an image up to 20000 px wide
is over 10000 mm (a 4 px defect is then 2 mm, far coarser than any AOI camera), and up to 100000 px/mm no size in mm
overflows in px. `save_recipe` refuses a size in mm the engine cannot apply (no number above 0, one above 10000 mm, or
an ROI's x or y below 0) with AOI-RCP-011; a stored scale that is no number above 0 (its CHECK turned off by hand) is
AOI-RCP-012 wherever it is read, so nothing is judged or saved with it, until Set Scale replaces it (Compare shows sizes
without it meanwhile). The scale is a number an Engineer sets, not one read from the images: a Golden board of another
size (a new camera) keeps it, so after a camera change the scale is calibrated again on the new Golden board before
boards are judged, and until then sizes in mm keep their px (nothing compares the Golden board's size with the
calibration image yet; open with Jay). The compare step's 5 × 5 blur, ±2 px shift tolerance and noise clean-up stay in
px: on the synthetic regression set at twice its size, the scale set to twice its own, the size in mm keeps 38 of the 40
verdicts, and two NG boards that the default recipe misses at 1x by a few px are found
(`tests/regression/test_resize_verdicts.py`; with the size left in px, seven change).

Minimum defect size under 4 px (REQ-INSP-014, since S29): a minimum defect size that spans under `RESOLVED_PX` (4 px)
at the board model's scale, or without one an area under 13 px, gets AOI-RCP-007 (`Recipe.size_notice`), which names
the size, the px it spans and the least size to give. Computed from the size the engine applies, it shows in amber:
on the Recipe Editor under the size field, the code, the title and what to do (the px it spans are beside the size,
with a ✓ from 4 px), and on Compare in one line, the code, the title and the least size, at the top of the "why" box
while Try other thresholds shows (`DefectSizeField.noticeChanged`, `ComparePage._show_why`), so it takes no row of the
panel, which has none to give at 1600 x 900, and the decision table shows as many rows whole as without it.
`save_recipe` saves the recipe all the same, with the code in its audit entry's reason. The Recipe Editor's Thresholds
tab is a scroll area (`scrolled()` in `aoi/ui/pages/base.py`, as wide as the tab): where the window is too short for
its rows, it scrolls rather than squeeze one, as at 1600 x 900 with Windows' fonts, taller than DejaVu Sans, while the
notice and the AI score threshold's note show (597 of the 615 px they need); a field taking the focus, by Tab or a
click, shows whole.

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
saying so, and the AI check it turns off gets `AI_OFF_NOTE`, as inspecting with it does (#246). A stored result
holds that evidence in its record and its two map files (`aoi/core/maps.py`, format 2 since
S28a, [ADR 0005](adr/0005-stored-ai-map-format-2.md)): the difference map exactly, and the AI map within one step (0.001
σ up to 32.767 σ, then 1/8192 of the value, up to 1789 σ) with each pixel on the side of the AI model's pixel threshold
it was judged on; a map file that is there but cannot be read raises AOI-CMP-003, and so does one that decodes but is
not the map written (not one channel of its bit depth at the size of the board picture, whose PNG header `load_maps`
reads), as damaged, for `re_evaluate` and for Compare alike (#249). So a stored result is judged again as
the live one would be, but for what is read from its AI map, within one step over the AI threshold: an AI defect's
score, so two AI defects of equal area whose peaks are that close may swap numbers or, where they overlap, keep the
other one, and the value of an ROI added, moved or renamed since, which that close to its threshold may grade the other
way. AI maps stored before S28a (format 1) are clipped at 65.535 σ and not kept on their side of the pixel threshold. An
Engineer judges a stored result again through `AppContext.re_evaluate(result_uuid, thresholds)` ([ADR
0006](adr/0006-judging-a-stored-result-again.md)): it reads only the maps the thresholds use, the AI score from the
result's stored AI check and the AI model's calibration from the model registry row the result names by UUID; it refuses
with AOI-CMP-004 a result whose map or AI model calibration is gone when a check the thresholds use needs it, and with
AOI-CMP-005 thresholds of another board model; it stores nothing, and takes about 70 ms at 5 MP on the 4-core cloud
VM the tests run on, about 90 ms with thresholds that leave thousands of difference regions (Pixel difference 10 and
Minimum defect area 1 leave about 5,600 on the 5 MP test board). Four things keep it there (#249):
`inspector.merge_regions`, which merges the regions into defects for every inspection too, tests a region only against
the defects kept in the 64 px cells it covers (testing every one kept took 1.5 s); `compare.regions_from_mask` reads the
peaks of regions up to 8 px a side together; `load_maps` decodes the AI map on its own thread while the difference
regions are found (`on_diff`); and both maps are written at zlib level 1 with deflate's default strategy and PNG's Up
filter (`maps.PNG_SETTINGS`) where OpenCV's own settings take the run-length strategy and the Sub filter, so on the
test board they read back in about two thirds of the time (maps written before still read, at the old speed).
`tests/test_re_evaluate.py` checks both cases against 300 ms.
Compare's Re-evaluate calls `AppContext.re_evaluate` on the pool thread once the load of a stored result's pictures
and maps has ended, and "Would be" shows within 300 ms of the key at 5 MP (`tests/test_compare_reevaluate.py`).

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
  the page for each step; AI Model Test row preview feeds "Use Last Inspected" on Compare (only a preview judged by
  what judged its run, #250).
* **Roles** (GUI §8). Disabled entries show a tooltip naming the required role. In the presenter theme
  (REQ-SET-008) the pages for the Admin alone (`roles == ("Admin",)`: Settings) and those marked
  `in_presenter_theme = False` (3D Profile) leave the sidebar for every role, with a section heading left over none
  (`MainWindow.hidden`, `_sync_nav`); `navigate()` refuses them with a status line, and the page shown when the theme
  is switched on goes to Home. Exit presenter theme shows in the header to an Admin only (Q49).

| Page | Operator | Engineer | Admin |
|---|:-:|:-:|:-:|
| Home, Inspection, Compare, Logs (view) | ✓ | ✓ | ✓ |
| Logs export / archive | | ✓ | ✓ |
| Logs → Delete Records…, Training → Remove (REQ-LOG-003) | | | ✓ |
| Training, AI Model Test, Recipe Editor, 3D Profile | | ✓ | ✓ |
| Compare → Try other thresholds (thresholds, Re-evaluate, Save to Recipe) | | ✓ | ✓ |
| Settings (users, workspace, device, dataset stores, hardware) | | | ✓ |

Since S16 the check lives in the service layer (ADR 0002, decision 5): every `AppContext` write is decorated with
`@requires(role, what)` in `aoi/core/services.py` and raises `AOI-USR-001` when the current user's role is lower, so
hiding a page or disabling a button is only a convenience. Every write also appends an audit entry (REQ-LOG-004), in
the same transaction as its rows (`Database.transaction()`, `@transactional`): both are stored or neither, on an error
or a crash (#178). A file cannot join it, so file writes come first and are removed when what records them fails: an
import's copies, a training run's files, an export whose entry cannot be written (never its own source). An import is all
or nothing (AOI-TRN-008, or AOI-TRN-011 for a copy whose path the system refuses as too long, #245); a folder import,
one file per call, stops at such a file with AOI-TRN-009 naming how many were imported, and at any other error after a
file went in with AOI-TRN-010 and the same count (#206), which names AOI-TRN-011 as the reason for a copy refused as too
long (with none imported yet, AOI-TRN-011 itself, counting the whole folder); an overlay export that stops part-way
records the files that left (AOI-LOG-001).
The writes, their roles and entries:

| Write | Role | Audit action and object (before → after) |
|---|---|---|
| `ensure_board_model`, `set_reference`, `import_samples`, `import_files` | Engineer | `board_model.create`, `board_model.reference` (reference path), `sample.import` (one per `import_files` file, with `skipped`); object = board model name |
| `set_scale` | Engineer | `board_model.scale` (px per mm before → after, with the length in px, the distance in mm and the Golden board file it was measured on; S29, REQ-RCP-006); object = board model name. A length or distance that is not a number above 0, a scale outside 2 to 100000 px/mm, or an unknown board model, is `AOI-RCP-008`, nothing written; a stored scale that cannot be read (`AOI-RCP-012`) is replaced |
| `update_sample`, `delete_sample` | Engineer; `delete_sample` Admin (REQ-LOG-003) | `sample.update` (label, defect type: a label of `LABELS`, else AOI-TRN-018, and for NG one of the 33 types, else AOI-TRN-013; none for OK; the relabel adds a label row and keeps the one before; a sample a labeller labelled so already gets neither, and one carried over with no labeller is labelled again), `sample.delete`; object = sample UUID |
| `set_label`, `set_boxes` | Engineer | `label.set` (the label before and after: its label row's UUID, label, defect type and boxes, each with x, y, w, h, type and severity); object = sample UUID (REQ-TRN-002, REQ-TRN-003) |
| `check_label`, `draw_ok_checks` | Engineer | `label.check` (check UUID, label row, label; object = sample UUID), `label.draw` (the draw: seed, OK labels, samples drawn; object = board model name) (REQ-TRN-004) |
| `make_calibration_set`, `label_blind`, `run_agreement_check` | Engineer | `calibration.make` (board model, samples), `label.blind` (sample, label, defect type), `agreement.check` (the stored check); object = calibration set UUID (REQ-TRN-016) |
| `freeze_dataset` | Engineer | `dataset.freeze` (name, customer, allowed uses, agreement check, file count, manifest SHA-256); object = dataset UUID (REQ-TRN-005) |
| `lock_validation_set` | Engineer | `dataset.lock` (split UUID, seed, OK and NG counts of each part, the validation set's NG count by defect type); object = dataset UUID (REQ-TRN-006) |
| `create_store`, `restore_store_key` | Admin | `store.create` (customer, key id), `store.restore` (key id); object = store UUID; never the key or its sheet. The key is saved after the row and the entry, in their transaction, so an entry that cannot be written leaves no key, and a key store that refuses the key is `AOI-TRN-044` with nothing written (REQ-TRN-017) |
| `move_in` | Admin | `store.move_in` (board model, files to move, resumed); object = store UUID. The row and the entry are written before any file is encrypted, so a move that stops is finished by calling it again, audited again (REQ-TRN-017) |
| `shred_store` | Admin | `store.shred` (customer, key id, board models, file and AI model counts, resumed); object = store UUID. The key is deleted before the row and the entry are written, and the files after them; a shred that stops is finished by calling it again, audited again (REQ-TRN-017) |
| `train`, `activate_model` | Engineer | `model.train`, `model.activate` (active version; an older one is a rollback; `model.train` also the Golden board before, and its metrics name the dataset version, its UUID and the use, S39); object = model UUID. A run refused for its customer's store or its use writes `training.refused` (use, customer, code, and why as the entry's reason; object = dataset version UUID) in a transaction of its own, then raises AOI-TRN-046 (REQ-TRN-017) |
| `save_recipe` | Engineer | `recipe.save` (the latest revision's body before, the new one after, and the reason typed on Save Recipe's sheet, REQ-RCP-004 and REQ-RCP-005); object = recipe UUID. A revision that sets, changes or clears the AI score threshold's override is also audited as `recipe.ai_threshold` (revision, override, the threshold that judges, the active AI model's version and calibrated value); object = board model name (REQ-TRN-015). A size in mm the engine cannot apply is `AOI-RCP-011`, and any recipe while the board model's scale cannot be read `AOI-RCP-012`, nothing written (S29) |
| `batch_test` | Engineer | `test.run` (folder, model version, metrics); object = board model name |
| `export_model`, `export_overlays`, `export_csv` | Engineer | `export.model`, `export.overlays`, `export.csv` (destination, relative to the workspace when inside it, else in full (#196); counts; Logs & Export's overlays also the `filter` that listed the records, REQ-LOG-002). Q58 of the Logs sketch gives exports to the Admin alone: open, since AI Model Test's and Training's Export CSV reach `export_csv_files` as an Engineer |
| `export_csv_files` | Engineer | `export.csv` once per file (destination, stored as above, and row count; with `listed`, the `HistoryFilter` that listed the records, also `filter` and the record count `records`, REQ-LOG-002); object type = what the rows are. Logs & Export's records and checks: the files are written all or none (`atomic.write_all`), a file that cannot be written is `AOI-LOG-002` naming it, the entries go in one transaction, and the files are removed when the entries cannot be written (#195) |
| `export_report` | Engineer | `export.report` (destination, stored as for the exports above, board model, run UUID, AI model version, bytes); object = test run UUID. The page renders the PDF in memory and the service writes it through `atomic.py`; an export that cannot be written is `AOI-LOG-002`, as for `export_csv` (#180) |
| `export_board_image` | Operator | `export.image` (destination, stored as for the exports above, board model, the board's file name, verdict); object type `inspection`, object = the record's UUID, none for a result that was not saved. Save Image… (F9) on Inspection, run on the pool as the user who pressed it: the picture with its defect boxes is encoded first (a name with no image format is `AOI-INSP-002`), written beside the destination under a temporary name (`atomic.staged`; a file that cannot be written is `AOI-LOG-002`), and moved into place in the transaction that writes its entry: when the entry cannot be written, the move fails or the commit fails, the destination is left exactly as it was, a file of that name unchanged and a folder made for it removed (#178, #241). The record is read before the write, so a read that fails leaves no picture. The page reads the result, the record and the board model when F9 is pressed, before the file dialog, whose event loop lets a run go on, so the entry always names the record whose picture it saved. Operator is the lowest role, so every role keeps F9 (REQ-INSP-005); the page enables F9 for the role in `REQUIRED_ROLE`, so whether #151 takes it from Operators is one word |
| `archive_old` | Engineer | `inspection.archive` (days, count); the retention run at start-up is a system action: logged, not audited |
| `delete_inspections` | Admin | `inspection.delete` (before: the records' UUIDs; after: the `HistoryFilter` that listed them, `records` and `files`; the typed reason; a blank one is `AOI-LOG-003`, nothing deleted); no object UUID. The rows (defects and checks by cascade) and the entry commit together, then the overlay and map files under results/ are deleted; one that will not go is logged as `records.evidence_left` and reported as `AOI-LOG-004` (REQ-LOG-003) |
| `_sweep_ok_maps` | system, at start-up; no page calls it | `maps.sweep` (days, swept, skipped): the map files of OK results past `map_retention_days_ok` are deleted and forgotten, NG and WARN maps stay; audited, unlike the start-up archive, because it deletes evidence. A file that cannot be deleted, or lies outside results/, is skipped with a warning and kept for the next start |
| `add_user` | Admin | `user.change` (role); object = user UUID. The last Admin keeps the role: `AOI-USR-002`, nothing written |
| `save_settings` | Admin | `settings.change` (the Settings page's values: what settings.json held before → what it holds now); object type `settings`, no object UUID (#197). Two system writes to settings.json go past the check, unaudited, since no user asks for them: the page in use (`last_page`, `MainWindow._on_nav`) and the folder chosen after a refused workspace at start-up (`workspace`, `aoi/ui/errors.py`) |

Reads, inspections (`inspect_file`, `log_result`), alarms and error reports need no role: an Operator inspects boards.
A picture leaves through Save Image… only by `export_board_image`, the one write an Operator makes through the check;
`tests/test_layers.py` fails a page that imports or calls `save_image` or `QImageWriter`, or calls `cv2.imwrite` or a
`.save(` with an argument, as a QImage's or a QPixmap's (#241).
One call that writes nothing needs a role: `re_evaluate`, judging a stored result with other thresholds (REQ-CMP-005),
is for an Engineer, through the same check; it stores nothing, so it writes no audit entry.
`tests/test_roles_and_audit.py` keeps the Role column above (and `re_evaluate`: Engineer) as a table of its own,
fails when a `@requires` names another role, and calls each of them with every role below its own (#181).
Until sign-in ships (REQ-USR-002, 1.0) the user is the one picked in the header, so an entry names who was picked.
The user is one immutable `Actor` (name, role, UUID) that `set_user` replaces whole. Work acts as the user who started
it (#177): `@requires` checks the user acting (`AppContext.actor`) and holds it in a context variable for the whole
call, and `AppContext.jobs` gives every job, as it is submitted, a copy of the submitter's context with that user, so
training, an AI model test, a folder import and the board being inspected name the user who started them in their audit
entries and records, and are not refused part-way, whoever signs in with Switch User while they run. An inspection run
submits each board once the one before is saved, so it stops there when the user signed in is no longer the one who
pressed Start (`InspectionPage.run_actor`): the user now signed in presses Start to go on, so no board is recorded under
a user who did not start it.

The role is always the one the users table holds for that user (`AppContext.set_user(name)`; a name it does not hold
is refused with `AOI-USR-003`), so the check and the entries never name a role the table contradicts (#197). A start
signs in the first stored Admin while the workspace has no board model, to set the station up, and `operator`
otherwise, each with the stored role (`AppContext.start_user`).

User switching is a local picker for the PoC; Stage 4 replaces it with MES authentication (`MesClient.authenticate`).
A switch leaves a page the new role may not open for Home, and shows any other page again (`on_show`), so its
role-gated buttons and links follow the new role at once (#174). Before that, `MainWindow.set_user` calls
`Page.on_user_changed` on every page, shown or not, so a page opened later never keeps what the user before left for
another role: Compare's hidden thresholds form goes back to the recipe's when an Operator signs in (REQ-CMP-005), and
any sign-in closes its Save to Recipe sheet, so a revision never carries the reason of a user it does not name.

### Pages

| Page | Main functions | Spec |
|---|---|---|
| **Home** | Six step cards (Upload → Self-train → Tune recipe → Validate → Inspect → Export) with live status for the selected board model | RM Stage 1 flow |
| **Inspection** | Load images/folder (Stage 1 "camera"); Top/Side/Bottom view tag; **Start / Stop / Next Board / Save Image…** (Save Image… writes through `export_board_image` on the pool, audited as `export.image`, #241); image with defect boxes coloured by severity; defect list **No, Type, Score, Side, X, Y** (click to zoom); big OK/NG/WARN banner; alarm log with time, level, code and message, kept across restarts; every result saved with its evidence on the pool thread, before the next board (REQ-INSP-008, REQ-SET-021; a failed save stops the run with AOI-INSP-008, or AOI-INSP-014 when the system refuses an evidence file's path as too long, #245); a run is tied to the board model it started under: a board model change in the header stops it after the board in hand, which keeps the run's board model, with AOI-INSP-012 in the status bar and the alarm log, and the last board inspected is forgotten, so Compare never opens it as the new board model's (#172); a board in hand whose result arrives after the change, by Start or Next Board, is saved under its own board model and cleared like the board shown, with a line under the banner naming it, its verdict and that board model (in a run with boards left, also how to carry on with Start), and "Compare with Golden board ›" is enabled only while there is a record or a file to open (#243); every board is judged with the AI model, recipe, scale and Golden board active when it starts (the recipe says whether the AI check runs), and a run that moves to a new one says so with AOI-INSP-013, an AI model activated while the recipe turns the AI check off excepted (#243, #246); a Switch User to another user stops a run after the board in hand too, with a status line and no alarm (the last board inspected stays shown for Compare), so each record names the user who pressed Start (#177) | GUI §4.1 |
| **Compare** (optional) | Golden reference and test board **side by side** with **synchronised zoom/pan**; views under Show: Side by side (the Golden board with a dashed box per defect beside the test board with its labelled boxes), Difference heatmap and AI score heatmap (the test board under its map), Defect boxes only (the Golden board pane hidden and the test board with its boxes fitted to the width of both; any other view brings the pane back and fits the board to its half again, and so do "Compare with Golden board ›", Use Last Inspected, Golden Board and Reference…, which ask for a Golden board and switch Defect boxes only to Side by side, while Test Image… and Re-evaluate keep the view; the hidden pane moves no zoom of the shown one, #248); **decision table** (check, source, value, threshold, rule, result) with failing rows highlighted, from the **stored result** when the page opens on a record (row for row the stored checks, never a new inspection: REQ-CMP-003; one click from Inspection, REQ-INSP-009) beside the golden board it was judged against, which inspecting the board again on Compare keeps until Golden Board is pressed (not shown, with the reason and Re-evaluate › as the next step, when that file has changed, cannot be read or is gone, or none was recorded), with a note naming the AI model version active when the board was judged and the recipe revision that judged it (which says whether the AI check ran; the "why" box says so when it was off, #246) and what changed since (for a result judged at another scale than the board model's now, both scales: Re-evaluate applies sizes in mm at the one it was judged at, the form shows them at the board model's, S29); plain-word "why" box, one sentence per failing check, NG first (REQ-CMP-004), under AOI-RCP-007 in amber in one line while Try other thresholds shows a minimum defect size under 4 px (REQ-INSP-014, S29); **Try other thresholds** (the minimum defect size in mm when the board model has a scale; Save to Recipe keeps one left untouched as the recipe holds it) for Engineer and Admin, under the images and the panel and as wide as the page (three columns of fields, a label going over its field before the window widens, and Re-evaluate and Save to Recipe on a row under them, the save sheet in its place, its changes beside the reason and its buttons), so the decision table keeps its rows, up to `theme.DECISION_ROWS` (seven), in view at 1920 x 1080 and at 1600 x 900, the "why" box giving way first (`_hold_rows`; Jay's choice of layout, 2026-10-08: beside the images it left five of seven rows at 1920 x 1080 and one at 1600 x 900) (hidden for an Operator, whose boards Compare judges by the recipe: when an Operator signs in, on any page (`on_user_changed`), the form goes back to the recipe's thresholds, read once then, and a board inspected with another recipe than that one (`judged_by`, in px at the board model's scale then: the form's thresholds not saved, a revision saved since, or a scale set since that gives a size in mm other px, S29; values that did not judge the board are not counted, `_judging`: the AI score threshold, and an ROI's AI score and name, when its AI check did not run, the AI check off or no AI model active, the Golden board comparison's own thresholds, Minimum defect area aside, which also sizes the AI model's defects, when the comparison did not run, and a disabled ROI and an ROI's Stage 2 heights, volumes and side, which nothing reads yet; a board still worked out is held by the recipe's switches) is cleared, a run of it still going stopped, and inspected again by the recipe once Compare is shown, one cancelled left so) with Re-evaluate (Ctrl+R) and Save to Recipe, the AI score threshold an `AiThresholdField` as on the Recipe Editor, but with its sketch's label, "Override the AI model's value 3.063", in a row of its own under the field (beside the field it widened the window to 1779 px), its note on the row of Re-evaluate and Save to Recipe, that names, on a stored result, the calibrated value of the AI model that judged it, which Re-evaluate applies (AOI-TRN-012 naming the version the result gives when the registry no longer holds that AI model), and else the active AI model's, a stored result judged with the AI check off included (REQ-TRN-015, #246); with no value to name, the tick, "Set my own value", goes back beside the field, so that tick and note never both take a row (Tab reaches the tick in reading order wherever it sits, and a tick with the focus keeps it as it moves): on a stored result Re-evaluate judges it again from its stored maps on the pool thread, without the AI model (`AppContext.re_evaluate`, REQ-CMP-005), under "Re-evaluating…" over the decision table and the "why" box once it takes a second, which goes with the answer or a refusal's dialog, not at the job's end, Re-evaluate off meanwhile and the focus, when it was on it or on another control the run turns off, in the "why" box, one Tab before Cancel once that shows, so a second Space presses nothing, and back on Re-evaluate at the end unless moved to a control other than Cancel, and on it after Cancel, pressed by key or click, and when the run ends or is stopped while Cancel has the focus, as Cancel hides then, or in the "why" box when an Operator's sign-in hides the panel, as is a focus left in the panel then, run or not; Re-evaluate is off too while a stored result's pictures and maps load, another result shown at a run's end or by Inspection's "Compare with Golden board ›" (which shows Compare with the focus it last had there), and a focus on it waits in the "why" box then as well and goes back once they have loaded, never on to Save to Recipe (one rule where Re-evaluate is turned on and off, `_sync_roles`; the window's `focusWidget()` is read, which holds the focus while another window is in front, when no control `hasFocus()`; REQ-SET-021, review, verification), and shows "Would be: <verdict>" beside it (bold, beside a bar of the verdict's colour, `theme.verdict_mark_style`, so it never reads as a third button) while the banner keeps the stored verdict, the decision table and the "why" box showing the checks those thresholds give (the board keeps the stored boxes, which the "why" box says when defects make the WARN) until a threshold or the recipe changes, another run or result shows, the board model changes or an Operator signs in on any page (a re-evaluation still running is then stopped); on any other board it inspects again; the thresholds are loaded again from the recipe once another revision is saved or the scale changed, so Save to Recipe never reverts one; Save to Recipe (Ctrl+S, the page's one blue primary, on only for a role `save_recipe`'s @requires allows, `REQUIRED_ROLE` #241, while a threshold of the form differs from the recipe as the engine reads them, an AI score threshold of 0 being none, one that did not judge the board shown included, such as the AI score threshold with the AI check off, which an Operator's sign-in does not count, `_judging`, and off while a re-evaluation runs, so no key opens the sheet over it) opens an inline sheet in place of the panel, never a dialog, that lists each threshold that changes, before → after (no override as "the AI model's calibrated value" while `calibrated_threshold` reads one for the board model's active AI model as the sheet opens, else "none", as the save's audit entry then names no threshold; never the AI model the panel names, which may be a stored result's; with a scale, the minimum defect size in mm, as its field shows it, `min_defect_mm` in `THRESHOLDS`, S29), names the revision the save makes and asks for a reason, without which Save Revision (a plain button) is off; Save Revision, or Enter in the reason, stores the next revision through `AppContext.save_recipe(recipe, reason)`, audited as `recipe.save` with the recipe before and after, the user, the time and the reason, and the stored result keeps its verdict, while Inspection (at its next board) and the Recipe Editor (when shown again) take the revision up as they do one it saves; Cancel, Esc, any sign-in, any board opened, the one shown included (`show_stored`, once the record is read, so one that cannot be read leaves the page as it was, and `set_test`), a board model change, a revision saved elsewhere meanwhile (AOI-RCP-004, logged and alarmed, once Compare shows again or at Save Revision, which checks the latest revision first: `_take_up_revision`) and a scale set meanwhile (AOI-RCP-010, likewise; S29) close the sheet with nothing stored, the focus going back to the panel only from inside the sheet, as at a run's end, or to the "why" box while Save to Recipe and Re-evaluate are both off, a stored result still loading, and on to Re-evaluate when the load ends if it is still there (`_refocus`, `_sync_roles`; S28d); a record's board is judged again only under its own board model (Re-evaluate under another is refused with AOI-CMP-005, and a board model change drops it); Cancel on the busy overlay leaves no verdict under the name of the board cancelled (#172); pick any reference image instead of the golden template; the file names over the two pictures, in the note (AOI-CMP-001 included) and in the messages on a picture's pane, and the board model Save to Recipe's sheet names, may break after each _ and - (`breakable`, a zero width space; `breakable_names` for the file an error names in the note or on a pane), so a long name, such as a sample's ending in its UUID, wraps there instead of widening the window past the screen or running past a pane's edge; a part of a name with no _ or - in it stays whole, as do the folders of a Windows path between two _ or - (Qt never breaks after a `\`) (#245) | Jay's request |
| **Training** | Two tabs, **Samples** (the import sheet, the dataset table and the label editor below) and **Datasets** (the Working set panel, the Labeller agreement panel and the Versions table, Datasets stage 2 and 4 of 4) in a tab bar on the title row over a `QStackedWidget`, as the sketches draw them, so the page is no taller than before them and fits a 1600 × 900 screen, the training panel beside both; every key below is the Samples tab's: `TrainingPage.action` adds each action to the tab's widget, not the page, so none acts while the Datasets tab or the blind panel is shown. **Add OK Images… / Add NG Images… / Import Folder…** (Ctrl+O, Ctrl+N, Ctrl+Shift+O) open the import sheet inline above the samples table (`aoi/ui/pages/training_import.py`, REQ-TRN-001, S31) for the header's board model, which its title names and its import keeps (another one picked in the header closes it before it imports; once it has imported, or while it imports, it stays with its list, its Import off and a line naming its board model until the header shows that one again; a sign-in closes it, or once its import ends while one runs, `on_user_changed`; the error that stops that import opens its dialog only for the user who pressed Import, and for anyone signed in since it is logged and alarmed with the status line pointing at the alarm list, as for a cancelled import, #206): the files picked or found under `ok/` and `ng/` (`ng/<defect type>/` pre-fills the type), View and Label for all, a type of the 33 for the NG files, each row's own label, type and view, Import (Enter, the page's one blue primary while the sheet is open, Start Training in its place while that line shows; off until every NG file has a type) running `AppContext.import_files` on the pool with copies of the rows, each file's outcome with its code, the current row's coded line in a muted line under the table, and Copy List, Cancel (Esc) keeping what went in; dataset table (its Defect type the types of an image's boxes, each once with its count, "Solder Bridge ×2, Missing Component", read with the table on the UI thread, one `AppContext.boxes` per NG row, as AppContext has no read of a board model's boxes at once (1000 NG images of three boxes refresh in 0.15 to 0.24 s against 0.11 to 0.13 s before S33, within REQ-SET-021's 2 s), and set at once when a box is stored, else the type given at import; its Labelled and Checked columns name the image's labeller and the second user who checked its current label, "—" for none, REQ-TRN-004, Datasets stage 1 of 4, and a box stored makes the label the user's own with no check, which the row, the checks line and Check Label follow at once) with Mark OK, Mark NG, Mark UNSURE and Check Label (Enter: each selected image's label the user signed in can check, through `AppContext.check_label` on the editor's pool thread, the others left as they are with their count and the first one's reason in the status line; off, its tooltip saying why for the topmost selected image, such as "You labelled this image"; plain, not the sketch's blue, as Start Training stays the page's one blue primary) / set reference / Draw OK Labels to Check (`AppContext.draw_ok_checks` for each view with an OK label, as the page's pool job, off while an import runs, the filter then showing Unchecked) / remove, under Show (All, OK, NG, UNSURE, or Unchecked: each view's NG labels and drawn OK labels not yet checked, as `label_check_status` gives them), a line with the sample counts and the reference image's name, cut at its end to the line's width with the whole line as its tooltip, so a long file name never widens the window past the screen, a line counting the checks a freeze needs, every view together ("0 of 3 NG labels checked · 0 of 2 OK labels checked (10 % of 20, none drawn yet)", with ✓ once every view is ready), and under 20 OK samples the tip that training needs 20 OK images or more in a dataset version's training set on a line of its own (#245); **label editor** beside the table (REQ-TRN-003, S33; `aoi/ui/pages/training_labels.py`, `aoi/ui/widgets/box_editor.py`): the selected image (the topmost row selected) under its file name, label and view, with its defect boxes on it and in the Boxes list under it, a row selected there, or a press on the box, selecting it (yellow with a 16 px handle at each corner, `theme.HANDLE_PX`, the others green) and showing its type in the Type list; a drag on a box moves it and a drag on a handle of the selected box resizes it, by mouse or finger (Qt turns a touch the view does not take into mouse events), never past the image's edge and never under 4 px a side, the box following the pointer and stored once, at the drag's end; a selected box under two handles across on screen (a 40 px box of a 20 MP image at fit is 2 or 3 px) has its handles just outside its corners, so a press inside it moves it, and a second tap on a box is a press, never a fit; a refresh during a drag waits for its end, and a drag whose release never comes (the pointer leaving the editor, or the focus going) ends there, stored; a box's label that the pane's right edge would cut ends at the box's right edge instead, or at the pane's left edge when that would cut it; on an NG image Draw Box (on, it takes `theme.BG_ON` with white text and border, by the stylesheet's `QPushButton:checked` rule, which gives Recipe Editor's Draw ROI the same on look) and a drag add a box of the type in the Type list (the 33 types of `aoi/defects.py` by category, never Anomaly), whose severity the defect table gives, shown beside the list, cut to the image and at least 4 px a side, and another type picked (a choice in the open list, or Enter on the type the arrow keys or a letter show; the wheel turns the list only while it has the focus, and leaving it shows the selected box's type again; `TypeList`) gives the selected box that type and its severity; each change is stored at once through `AppContext.set_boxes` (a label row and a `label.set` audit entry, the boxes before kept), and a refusal shows its coded dialog and the stored boxes again; the image and its boxes are read, and each change stored, on a pool thread (`aoi/ui/workers.py`), one store at a time: until it ends, a press that would change a box or a type picked is refused with a line in the status bar, a sample selected meanwhile is shown after it, and a `BusyOverlay` over the image says "Opening the image…" or "Storing the change…" after a second; Delete Box (red, the last in its row) and the Delete key, one `Page.action`, delete the selected box at once with no question, the box kept in history, and Undo beside it and Ctrl+Z (`QKeySequence.StandardKey.Undo`), one action, on only while there is something to undo, put back what the last change stored replaced, one change per press, on whichever image it was (its label, defect type and boxes again through `AppContext.set_label`), whose row is then selected and shown (an Undo that an error stops shows the images it put back before it, then the coded dialog; `_restore`); Switch User and another board model empty that list, and a store that ends after them adds nothing to it (`LabelEditor.forgotten`, read as the store starts); Mark OK, Mark NG and Mark UNSURE in a row under the table and the keys O, N and U, one `Page.action` each, relabel the selected images not already so labelled through `AppContext.set_label` (each image's label read as stored, on the pool thread, so one that a box just stored gave a labeller is not stored again) (S32's call, which takes UNSURE and an NG with no type until its boxes are drawn; `update_sample` keeps the import's rule, S31), on the editor's pool thread, with no question and no defect type (a label carried over with no labeller is labelled again with its own type, which Undo leaves, so it can be checked; a type an earlier version stored that is not one of the 33, which AOI-TRN-030 refuses, goes, so Mark NG labels such an image NG with none and its boxes can be drawn, and Undo puts back none either), the reference staying OK and named once (AOI-TRN-007), and Undo puts back a mark too (each image's label, defect type and boxes); a batch that any other error stops, such as a database another program holds past the busy timeout, keeps the images it stored, which the table shows and Undo puts back, before the coded dialog (`_each`, which Remove shares); Mark NG then puts the focus on the image; a letter, digit or sign typed while a drop-down list, a text field, a table or list that a typed key edits (its edit triggers include `AnyKeyPressed`, as the import sheet's do) or any control of S31's import sheet has the focus goes to it, never to the page's keys O, N, U, D, Z, +, - and 0 (a spin box's or a text field's own line edit accepts its `ShortcutOverride`; for the others the page, an event filter on the window, accepts it, `TrainingPage._takes_keys`), and Enter typed in a spin box, a text field or a drop-down list is the field's, never Check Label's (the event filter accepts its `ShortcutOverride` too), so a key typed in a row's Label or Defect type cell of the sheet opens its drop-down on the value it starts; the samples table and the Boxes list, whose rows start with a number and which a typed key does not edit, leave the letters to the marks; the table keeps its selection across a refresh, the editor following once; PgDn and PgUp select the row after or before the topmost one selected, in the table's sort order; D, a `Page.action` on only while Draw Box is, presses Draw Box and in Draw mode puts the focus on the image, and Esc, on only in Draw mode, leaves it, but with the focus in the import sheet closes the sheet, Draw mode staying on (the sheet accepts the `ShortcutOverride` of its Esc and its Enter and takes them in `keyPressEvent`, so they never meet Leave Draw Mode's Esc or Check Label's Enter as an ambiguous shortcut, which Qt would log and act on neither of); on the image with the focus, Enter in Draw mode places a box of the Type list's type 64 px a side on screen at any zoom (`KEY_SIDE_PX`) at the middle of the image shown, and the arrows move the selected box 1 px, 10 px with Shift, or with Ctrl its bottom right corner, a burst of them or a key held down stored once, half a second after the last key (`BURST_MS`); the image and the Type list accept the `ShortcutOverride` of the keys they act on (the arrows with a box selected, Enter), so a page key on the same key never takes them; for a hand with no wheel, Zoom In and Zoom Out under the image and Fit beside Draw Box (size class B; three in a row under the image left the training panel too narrow for its buttons with S31's import sheet open) share their `Page.action`s with the keys +, - and 0, 1.25 a step about the view's middle (`ZOOM_STEP`, `BoxEditor.zoom`), and Z fills the view with the selected box (`BoxEditor.zoom_to_box`); the splitter gives the table the width its line of counts needs to show a 28-character file name whole at 1920 px and the editor the most of the rest that leaves the training panel its buttons whole (`split.setSizes([650, 500])` in the Samples tab, `setSizes([1150, 460])` for the tabs and the training panel: the table 646 px, the editor 503 px and the training panel 457 px wide at 1920 × 1080, and 742, 407 and 457 px with S31's import sheet open); an OK or UNSURE image takes no box, so Draw Box is off there; an image whose file cannot be read shows its coded line under the heading and none of its boxes, which stay listed, the list and the Type list off; **Labeller agreement** on the Datasets tab (REQ-TRN-016, Datasets stage 2 of 4; `aoi/ui/pages/training_agreement.py`, the labels sketch's panel, sketch decision Q60): the board model's calibration sets, newest first, with who made each and when; New Set (off below 100 images labelled OK or NG, its tooltip giving the count) makes a set of what `propose_calibration_set` draws and picks it; a muted line naming who has labelled how many of its images blind (`blind_labelled`); Labellers, two lists of the users who have labelled every image; Label Blind… (off once the user has labelled every image, saying so) shows the **blind panel** in the tabs' place, the stack's third page with the tab bar hidden (`BlindPanel`): "Image 12 of 100", never a file name, label, box or history line, the image read on the pool thread under "Opening the image…", Label OK (O), Type (the 33 types, none picked for each image) and Label NG (N, off until a type is picked) storing the user's own label through `label_blind` and showing the next image the user has not labelled, and Stop (Esc) back to the Datasets tab, the labels made kept and the focus on Label Blind…; the panel's keys are its own actions, active only while it is shown, and a sign-in or another board model closes it, so the next user never labels as the one before; an image that cannot be read shows its coded line and cannot be labelled; Run Agreement Check (off, saying why, until two different users who have labelled every image are picked) stores the check, and the newest check of the set shows as "OK/NG agreement 98 of 100 (98 %) ✓ target 98 %" and "Defect type 18 of 20 (90 %) ✓ target 90 %", the percent rounded down, with who was compared, when and by whom; **Working set** over the agreement (REQ-TRN-005, Datasets stage 4 of 4; `aoi/ui/pages/training_versions.py`): each view's OK, NG and UNSURE images and the checks a freeze needs, as `label_check_status` counts them, ✓ once the view can be frozen, the customer whose dataset store holds the board model (`store_of`) and the allowed uses (their own AI models ticked by default); Freeze Dataset… (Ctrl+F; plain, not the sketch's blue, as Start Training stays the page's one blue primary) shows the **Freeze sheet** in the agreement's place, `TrainingPage.show_sheet` hiding the agreement first so the page keeps the height a 1600 × 900 screen gives it, one sheet of the tab at a time (`sheet_open`): View, Board revision, the name `freeze_gate` gives and a line for each thing a freeze needs, ✓ or ✗ with the fix, and the refusal no line names; Freeze (Enter in the revision; off until every line is ✓ and a use is ticked) runs `freeze_dataset` on the pool with the busy overlay's progress and Cancel, the sheet's Cancel or Esc stopping it, nothing written and the sheet kept, and a sign-in or another board model meanwhile keeps the sheet until the freeze ends, as the user who pressed Freeze; **Versions** under them (REQ-TRN-005, REQ-TRN-006): the board model's versions newest first, Version, Frozen in local time, By, OK, NG, Validation OK / NG ("50 / 6", or "not locked"; `dataset_counts`), Customer, Uses and Manifest, the version picked kept across a refresh and one Freeze makes picked once listed, with the sketch's empty state and its Freeze Dataset… link; Split and Lock Validation Set… (off for a version split already, saying why, and while a sheet is open) shows the **Split sheet** in the agreement's place for the version picked: its OK and NG files against the 50 OK and 30 % of the NG a validation set takes, its NG by defect type (`datasets.stratum`) and a seed drawn as `lock_validation_set` draws one, which the user can change; Lock (Enter in the seed) runs `lock_validation_set` on the pool under the sheet's busy overlay, the sheet closing and the status line counting both sets once the version is locked; a Cancel before the lock began writes nothing and keeps the sheet, one after it began comes too late (the lock checks none), and a sign-in, another board model or another version picked closes the sheet; Verify Manifest runs `verify_dataset` on the version picked on the pool, with progress over the table and Cancel, the Manifest cell then "✓ 100/100" or "✗ 1 changed, 1 missing" for the session and under the table AOI-TRN-023 (`datasets.mismatch`) with the first five files named and a count of the rest; Export Manifest… asks first, naming the file count, then writes the version through `export_csv` ("dataset manifest": path, sha256, label, defect_type, boxes, labelled_by and checked_by by name, and part, "train", "validation" or blank); Open Version, the sketch's read-only view, is not built yet; **Dataset version** (REQ-TRN-007, S39): the board model's frozen versions, newest first, the newest with a locked validation set picked and the Engineer's pick kept across a refresh, with a line under it counting the version's validation set and training set ("Validation set locked ✓ 1 OK / 1 NG · training set 21 OK, 2 NG · NG used for calibration only"), or saying that its validation set is not locked or that there is no version, Start Training off while none is listed and training the one picked; epochs, input size, device; Start Training and Cancel (REQ-TRN-008, S40) with the bar, a line naming what the run does now with its percent and time left ("Training epoch 23 of 60 · 38 % · about 6 min left") and the log, the run going on whatever page is shown (section 3, Training as a job); **model version registry** with activate and export `.pt`, each version's Threshold its calibrated AI score threshold as `AppContext.calibrated_threshold` reads it, through `AppContext.calibration_of` over the one registry read of the table (AOI-TRN-012, with the error's text as the row's tooltip and in a muted line under the table, when its registry row holds none usable, REQ-TRN-015), and its OK/NG sample counts, empty where the row's metrics cannot be read | GUI §4.3, Stage 1, §6 model version control |
| **AI Model Test** | Select labelled folder; Run Test / Run Test Again; **Accuracy, Precision, Recall, False Call Rate** tiles; confusion counts; results table **Image, Label, Verdict, AI score, Matches label?** (GUI §4.3's GT, AI Result, Score and Pass/Fail in the Charter's words: Matches label, Differs from label in red, or No label for an image outside `ok/` and `ng/`, #207); preview; **Export CSV / Export Report (PDF)**, the report naming the folder and board model the shown results came from, and saying when the recipe turned the AI check off, so the AI model it names did not judge the images (#246); a run's results are shown only under its board model: changing the header's board model clears them, and a run that ends after such a change is stored, not shown (#180); the results are also tied to the AI model, recipe revision, Golden board and scale that judged them (the scale only while the recipe holds a size in mm, S29; a run judged with the AI check off to its recipe revision, Golden board and scale alone, so an activation leaves its rows previewed, and the note and AOI-TST-001 name "no AI model (the AI check off)" in place of an AI model, #246): once another is in use (a training run ended, a version activated, a recipe saved, a scale or a Golden board set), a selected row is not inspected again but shows AOI-TST-001 in the preview pane with Run Test Again for the run's folder, leaving Use Last Inspected as it was, and a line above the table, refreshed when the page is shown or a row selected, names what judged the run and what is in use now, while on show a row still selected is refused in place of its earlier preview, and previewed again once what judged the run is in use again; a new run drops a preview still being inspected and starts with no row selected; the rows, tiles and exports stay, as they describe the stored run (#250); the file names AOI-TST-001 gives in the preview pane (the row's and the Golden boards') may break after each _ and - (`breakable`, on the pane's copy of the error only; the line above the table keeps them as they are), so a long one wraps there instead of running past the pane's edge (#245); runs stored in DB | GUI §4.3 |
| **Recipe Editor** | Draw ROIs on the golden board (D draws, Esc leaves) and move and resize them there (`RoiEditor`, `aoi/ui/widgets/box_editor.py`, REQ-RCP-001): a click selects an ROI, a drag inside it or the arrows move it (1 px, 10 px with Shift), a drag on one of its eight 16 px handles or Ctrl+arrows resizes it, never under 4 px a side; the wheel zooms at the pointer, a middle-button drag or a drag with Space held pans, and Home fits the board again; ROI types **Presence, Polarity, Solder Bridge, Height, Anomaly**; parameters **AI Score** (× the AI score threshold: the recipe's, else the AI model's, #248), **Height Min/Max, Volume Min/Max** (each 0 or more, min not above max, "—" for unset; AOI-RCP-002 otherwise); Apply edits the selected ROI only and is off while none is selected (Delete clears the selection); Delete, the key or the button, removes the selected ROI with no question, as Ctrl+Z (Undo) undoes each draw, move, resize, Apply and delete back to the revision loaded and Ctrl+Y (Redo) does them again; yellow = selected, green = saved, yellow dashed = changed and not saved yet; global thresholds, the AI score threshold an `AiThresholdField` (`aoi/ui/widgets/ai_threshold.py`, REQ-TRN-015): a tick, "Override 3.063", names the active AI model's calibrated value, which the greyed field beside it shows until the tick is set; ticked, the field starts from that value to every decimal, named again as the tick is set (`ticking`), so an AI model trained or activated while the page stays shown gives it, and holds the override, given back as the recipe holds it until it is edited (more decimals than 3, or outside 0 to 10000; 0 is none), and clearing the tick restores the calibrated value; with none to name, the tick reads "Set my own value" and a note under it, a row as wide as the form, says why (no AI model trained, none active, or AOI-TRN-012 with what to do), and ticked, the field starts from 0, no override until a value is typed, never from a value shown for another board model; **AOI checks** tab (REQ-RCP-005, `aoi/core/checklist.py`): each of the 10 mandatory checks (DCT §4) marked by how the recipe as edited covers it, ✓ by its enabled ROIs of the check's type (Missing Component, Polarity Error, Solder Bridge), • by the whole board while the AI check or the Golden board comparison is on, ○ not covered, or ◌ needs Stage 2 3D/side cameras; **Try Recipe…** (Ctrl+T, REQ-RCP-003) offers the board last inspected under the board model first (`AppContext.last_board`, Q23), judges it off the UI thread with the recipe as edited, ROIs not saved included, draws its defects on it and lists its checks under the verdict as Compare's decision table names them (`check_rows`, `aoi/ui/pages/compare.py`; five rows before it scrolls), and stores nothing; cancelled with its verdict and checks cleared when the board model changes; **Save Recipe** (Ctrl+S, REQ-RCP-004) opens a sheet under the tabs (`SaveSheet`, `aoi/ui/pages/recipe_save.py`) that names revision n+1 and lists what it changes from the latest one, before → after (`recipe.changes`), Save Revision off while nothing changes; a Stage 1 check left uncovered needs a reason, kept in the save's audit entry (REQ-RCP-005); an edit made while it is open shows it again before anything is saved; Esc or Cancel closes it; Save Revision stores revision n+1 through `AppContext.save_recipe`, which never overwrites one; the **Revisions** tab lists each revision (`AppContext.recipe_revisions`) with user, time, its changes from the one before and its reason; Open shows the one picked read-only beside the recipe as edited, its settings, its ROIs and what the edits change from it (`RevisionPane`), and Restore as New Revision opens the sheet for a copy of it as the next revision (Q24), asking first when the copy would replace unsaved changes; **Calibrate Scale…**, an inline sheet (two points clicked on the Golden board, or a length typed, and the distance between them in mm; Set Scale stores the board model's px per mm through `AppContext.set_scale`, and refuses with AOI-RCP-008 on a Golden board replaced while the page is shown, as at a training run's end; Cancel, Esc in the sheet or on the image while it picks points, another board model, the Golden board replaced, another user signed in or Try Recipe… closes it with its points, and it opens on the Golden board, a Try's verdict gone; closed from inside, it gives the focus back to Calibrate Scale…, or to the image view while that is off; the status bar then names the scale, with AOI-RCP-007 when the minimum defect size spans under 4 px at it and AOI-RCP-009 while the latest revision holds sizes in px); at the board model's scale (REQ-RCP-006) the ROI table and the minimum defect size are in mm, the size with the px it spans beside it (`aoi/ui/widgets/scale.py`, shared with Compare), and Save Recipe stores them in mm (`Recipe.in_mm`: the same sizes, so a recipe saved untouched judges as before), and until then AOI-RCP-009 in amber under the scale says that the latest revision still holds sizes in px, which keep their px when the scale is calibrated again after a camera change, and that Save Recipe stores them in mm (`held_in_px`; word-wrapped, with what to do in view, as touch and keys reach no tooltip); without one they are in px, with AOI-RCP-005 in amber on a row of its own under Calibrate Scale… (Q21; beside it, it made the window 1601 px wide); a minimum defect size under 4 px shows AOI-RCP-007 under its field (REQ-INSP-014). A revision saved after the editor loaded its own (Compare's Save to Recipe) is shown when the editor opens again, after asking when it holds unsaved changes; kept changes cannot be saved over it (AOI-RCP-001) | GUI §4.2, DCT §4 |
| **3D Profile** | Until Stage 2 3D data exists, one card (`Stage2Card`, the empty-state pattern, sketch profile3d-card.md, REQ-P3D-001): "Coming in Stage 2", what the page will show (the height map, the four AOI checks that need height data, Accept / Reject per height defect), that height and volume thresholds are entered per ROI in the Recipe Editor until then, and Open Recipe Editor › (Enter, the page's primary) and Back to Home (Esc); no table, image area, field or disabled control. The sidebar entry keeps a "Stage 2" badge (`Page.badge`), shown to the roles that open the page | GUI §4.5 |
| **Logs & Export** | Filter by date (2000-01-01 to 2100-12-31), model, operator and result (All, OK, NG, WARN; S51), combined; the sketch's columns, Time, Board model, AI model, Result (its cell alone in the verdict's colour), Defects, Operator, View, Recipe rev and Image, each record's ID kept with its row (`fill_table` keys, `row_key`); every column sorts; the records are read on the pool thread when the page is shown (`LogsPage.list_records`, REQ-SET-020, S55: at 100,000 records, before migration 0022's indexes, the read held the switch to the page for 6.2 s), under "Loading records…" from 1 s on, the exports and Delete Records… off until they are shown, and dropped when Filter lists newer ones or another page is shown first; Filter, Reset Filters, Show All Records, Archive and a delete list at once; filling the table runs on the UI thread, about 0.9 s for 7,000 rows on a 4-core cloud VM; under the table the listed records by verdict and the archived count, and Open in Compare › (also Enter or a double-click on a row), which opens the selected record on Compare as it was decided (`MainWindow.open_stored`, #130); overlay preview of the selected record (the placeholder when it has none, and after Filter); Export CSV (two files, UTF-8 with BOM: the records, with their columns as before and the record, model and recipe UUIDs and `ai_check` appended, and `<name>_checks.csv` with one row per check: region, metric, source, value, threshold, rule, result, the model and recipe UUIDs and `ai_check`, its header written even when no record has checks; REQ-INSP-012; `ai_check` says whether the AI check ran on the record, RAN, OFF or NO_AI_MODEL, empty for a record stored without its result or whose stored result cannot be read, which is logged as `export.result_not_read` and stops no export, #246) / overlay images with confirmation; auto-archive older than the log retention, 30 days by default (on start, and on demand by the day count the button shows); Delete Records… (Admin only, red, last in its row): the listed records, their defects and checks and their evidence files under results/, after a question naming the count (No the default) and a typed reason (REQ-LOG-003) | GUI §4.4 |
| **Settings** | Workspace, AI device (auto/CPU/CUDA), defaults, retention, language (en/ko placeholder for 2H 2027 localisation); the Presenter theme tick, in its own group (REQ-SET-008); users & roles; **Dataset stores** under System (REQ-TRN-017, Datasets stage 3 of 4; `aoi/ui/pages/settings_stores.py`): the customers' stores, oldest first (customer, key id, created, board models, shredded), and New Store… (the recovery sheet once, its key not selectable, Close after "I have printed it…" is ticked, Print Sheet…), Restore Key… (the 52 characters counted as typed), Move Board Model In… (on the pool, Cancel leaving the rest for Finish Moving In) and Shred Store… (red, last, Shred once the customer's name is typed), each an inline sheet in the table's place, shown only once the table is hidden so the window keeps 900 px, and closed by a sign-in; hardware interface status per stage | GUI §6, §8, RM 2H 2027 |

---

## 6. Database schema (SQLite)

| Table | Key columns |
|---|---|
| `board_models` | name (a new name that differs from an existing one only in case is refused, AOI-TRN-005: Windows would give both the same model and golden board files), reference_image (golden), px_per_mm (the scale its recipe's sizes in mm are applied at, a finite REAL above 0, which a CHECK holds; NULL until an Engineer sets one, and for rows from before migration 0012) |
| `samples` | board_model, path, label OK/NG and defect_type (DCT; one of the 33 for NG, else the import refuses it with AOI-TRN-013, S31) as the import gave them (not changed since migration 0014: the current label is in `labels`; an import gives OK or NG only, and UNSURE is a labeller's), side, sha256 (the source file's, as checked before the copy and found again in the source and the copy after it, else AOI-TRN-014; NULL for rows from before the sample SHA-256 migration; an import skips an image whose SHA-256 the board model has, decision Q31) |
| `labels` | uuid, sample_uuid, label OK/NG/UNSURE, defect_type, labelled_by (a user's UUID, for a sample's first row the user the import ran as; NULL for the label migration 0014 carried over for each sample stored before it, at the time the sample was added), at_utc, superseded_by (the label row that replaced it; NULL for the one current label of a sample, a partial unique index). A relabel or a new box set adds a row and marks the current one superseded in one transaction (`Database.add_label`); triggers refuse any other UPDATE and every DELETE, so history is never rewritten (REQ-TRN-002, REQ-TRN-003). `Database.samples` and `sample` give each sample its current label, so training, the counts and the Training table read it; UNSURE is in none of the OK or NG lists training reads |
| `defect_boxes` | uuid, sample_uuid, label_uuid (the label row it was drawn with), x, y, w, h (whole pixels of the image as decoded and shown, turned by its EXIF Orientation, and inside it, by the size `imaging.file_header` reads without decoding: from the first MiB of most files, the whole of a TIFF or of a JPEG with large segments before its frame header, and a PNG's chunk headers across the file (each chunk's data skipped, up to 65,536 chunks), before the database lock is taken), dct_type (one of the 33, never Anomaly), severity (the type's in `aoi/defects.py`, never the caller's), labelled_by, at_utc, superseded_by (as the label row that replaced its own); append only, as `labels` |
| `label_checks` | uuid, label_uuid (the label row checked, one check each), sample_uuid, checked_by (a user's UUID, never the row's labelled_by), at_utc; append only |
| `ok_check_draws` | uuid, board_model, side, seed, ok_labels (when drawn), sample_uuids (JSON, the samples drawn), drawn_by, at_utc; append only |
| `calibration_sets` | uuid, board_model, sample_uuids (JSON, 100 proposed), made_by, at_utc; append only |
| `blind_labels` | uuid, set_uuid, sample_uuid, label OK/NG, defect_type, labelled_by (one per image and user), at_utc; append only |
| `agreement_checks` | uuid, set_uuid, board_model, labeller_a, labeller_b, images, ok_ng_agree, both_ng, type_agree, ok_ng_target, type_target (percent), agreed (both reached), run_by, at_utc; append only |
| `datasets` | uuid, name (unique), board_model, revision, view, version (unique per board model and view), customer, allowed_uses (JSON), agreement_check_uuid, manifest_path (relative), manifest_sha256, frozen_by, frozen_at; append only (REQ-TRN-005) |
| `dataset_items` | uuid, dataset_uuid, path (relative), sha256, sample_uuid, label_uuid, label OK/NG, defect_type, boxes (JSON), labelled_by, checked_by: a frozen version's files as its manifest lists them; append only |
| `validation_splits` | uuid, dataset_uuid (one split per version), seed, locked_by, locked_at: a frozen version's split; never changed or deleted |
| `validation_split_items` | uuid, split_uuid, item_uuid (a `dataset_items` row, in one split only), sha256, part train/validation; never changed or deleted |
| `dataset_stores` | uuid, customer, key_id (hex of the 16 bytes each file's header names), check_value (an HMAC-SHA-256 of a fixed text under the key, which tells a wrong key), created_by, created_at: a customer's dataset store, never its key; never changed or deleted, shredded instead (REQ-TRN-017) |
| `board_model_stores` | uuid, board_model (in one store only), store_uuid, set_by, set_at; never changed or deleted |
| `store_shreds` | uuid, store_uuid (one shred per store), key_id, files (the count when the key was deleted), shredded_by, shredded_at; never changed or deleted |
| `models` | board_model, version, uuid (also in the `.pt` file's metadata, written there before the file is saved, so an exported file names its record), path (.pt), metrics JSON (thresholds, scores, timing), active (one version per board model, switched in one transaction, so no reader finds none active, #171) |
| `recipes` | board_model, revision (1 is the default recipe, stored when the board model is created, so every result names a stored revision), uuid, body JSON, user, created_at |
| `inspections` | time, board_model, model_version, model_uuid (the AI model version active when the board was judged; whether the AI check ran is the recipe revision's to say, and a result judged with it off carries `AI_OFF_NOTE`, #246), recipe_rev, recipe_uuid, image/overlay paths, diff_map_path and ai_map_path (the difference and AI score maps as PNG files beside the overlay, 8-bit exact, and 16-bit within one step: `_ai2.png` since S28a, 0.001 σ steps to 32.767 σ, then 1/8192 of the value to 1789 σ, or `_ai.png` before, 0.001 σ steps to 65.535 σ; NULL for rows from before migration 0007, and for OK results once the retention sweep deleted them), reference_path and reference_sha256 (the golden board file the result was judged against and the SHA-256 of its bytes; NULL for rows from before migration 0008 and for results judged without a golden board), view (Top, Side or Bottom; NULL for rows from before migration 0005), result, score, metrics JSON, result_json (the whole result as `InspectionResult.to_dict` writes it, read back by `from_dict` without the images, with the scale it was judged at, `px_per_mm`, when there was one; NULL before migration 0006), operator, archived |
| `defects` | inspection_id, no, type, score, side, x, y, w, h |
| `checks` | inspection_id, no, region (Board, or the ROI's name and box), metric, source, value, threshold, rule, result, explain: one row per decision variable of a result (REQ-INSP-012; none for rows from before migration 0006) |
| `test_runs` | uuid, time, board_model, model_version, model_uuid (NULL for runs from before migration 0009), folder, metrics JSON, results JSON (one row per image; its `image` path stored like `folder`, and `ai_check`, RAN, OFF or NO_AI_MODEL, since #246); the AI Model Test CSV and report name the run and the AI model active then by UUID, and say when the recipe turned the AI check off |, dataset_uuid (the frozen dataset version a validation ran on, since migration 0020; NULL for a folder), judged_by (JSON of what judged every row: recipe revision, Golden board relative to the workspace, scale, AI check on or off; since migration 0021); each result names its overlay under results/test_runs/<run>/, at most 1600 px on its longest side
| `alarms` | uuid, time, level NG/WARN/ERROR, code AOI-<AREA>-<NNN>, message (English), phrase (the message's template, translation context and values as JSON, shown in the UI language; NULL for rows from before migration 0011 and for an alarm a page wrote in the UI language of its moment, #198); the newest 1,000 are shown and survive a restart |
| `users` | — |
| `audit` | uuid, at_utc, user_uuid, role, action, object_type, object_uuid, before_json, after_json, reason; append only (triggers refuse UPDATE, DELETE and, since migration 0010, an INSERT OR REPLACE or REPLACE INTO that reuses an entry's id or uuid; the connection sets `recursive_triggers`). `audit_entries` gives every entry the same fields, `before` and `after` decoded or None, without the raw JSON columns |
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
restore belongs to the installer. A refused workspace (`AOI-SET-001`, `-002`, `-003`, `-005`, `-011` for a folder
that cannot be created or a database SQLite cannot open or write at start-up, `-012` for one another program holds
locked, and for a workspace another copy of the app has open; the database and the log closed first, #171, #204) is
reported before any window opens, so `open_workspace` in
`aoi/ui/errors.py` follows the message with a folder picker: the folder chosen is opened, then saved to `settings.json`
as the Settings page saves it (logged as `settings.save_failed` if it cannot be), and Cancel closes the app
(REQ-SET-016). An error at start-up without a code shows `AOI-SET-007`, and its trace goes to the log in the default
workspace folder (event `app.start_failed`), since the excepthook logs to an open workspace's log (REQ-SET-019). Once
the workspace is open, `build_window` in `aoi/ui/main_window.py` installs the excepthook before it builds the window,
so a slot that raises while the pages are built is logged and shown too, and again with the window as the dialog's
parent; an error raised out of building the window (a page that cannot read a damaged database) is shown as
`AOI-SET-007` with its trace in the workspace's log (`error.shown`, context `start-up`), and `main.py` closes the
workspace and ends with exit code 2 (#205).
Records that can leave the station (`users`, `samples`, `models`, `recipes`, `inspections`, since migration 0009
`test_runs` and `alarms`, since migration 0014 `labels` and `defect_boxes`, since 0015 `label_checks` and `ok_check_draws`, and since 0016 `calibration_sets`, `blind_labels` and
`agreement_checks`; since 0017 `datasets` and `dataset_items`; since 0018 `validation_splits` and `validation_split_items`; since 0019 `dataset_stores`, `board_model_stores` and `store_shreds`) carry a `uuid` beside their integer key; `defects` and `checks` are rows of one inspection and
are named by its UUID and their `no`. Every stored time is ISO 8601 UTC with an offset and is shown in local time
(`aoi/times.py`); image, overlay, map, golden board, model and validation folder paths inside the workspace are stored
relative to it and resolved by `aoi/data/paths.py`, so a workspace folder can move (REQ-SET-017, REQ-SET-001). A path
outside the workspace (a validation folder on a USB drive) is stored absolute and read as written, as are the paths of
validation runs stored before migration 0009. The Logs filter's local days become UTC bounds in `aoi/times.py`, where
a day the clock cannot convert is no bound on its side, never an error (#174).
Migration 0022 indexes `inspections` by time, and by board model, operator and result each followed by time, and
`defects` by inspection, so each filter reads only its own rows and each listed record's defect count one index entry
(REQ-LOG-001); the empty state and the summary line read the history's first and last time and its archived count
(`AppContext.history_span`), never every record.
Every file the app writes (images, overlays, AI models, exports, settings) goes through `aoi/data/atomic.py`:
a temporary name in the same folder, flush and fsync, then an atomic rename, and an inspection's row, checks and
defects commit in one transaction, so a crash leaves a whole result or none (REQ-INSP-008). A save that fails before its
row commits (the database refuses it, or a map write fails) removes the overlay and maps it wrote, so it leaves no file
that no record names; a crash between the files and the row still can (REQ-LOG-006; #246). The only other writers are
the log (appended line by line), the schema backup (SQLite's backup API to a temporary name, renamed whole) and the tool
that writes `docs/error-codes.md`. `tests/test_power_cut.py` holds this (#202): a scan of `aoi/` fails any other file
write by the calls it knows (opens for writing, gzip, tarfile and ZipFile too; Path, os, shutil, cv2, NumPy and torch
writers; any `.save(path)`, as a QImage's; a QFile's open, copy or rename; Qt writers such as QPdfWriter given a file
by position, not a QBuffer), a run checks that every file an inspection and a training run leave went through
`atomic.write_with`, a kill inside such a write leaves the target absent and a temporary file the next start removes,
and 20 random kills, each after a saved result, lose no finished result. The two files of the Logs & Export CSV go
through `atomic.write_all`: both are written under temporary names, then moved into place, the file each replaces kept
until both are in place and put back if the second cannot be, and the export is audited only then (#195). Save
Image's picture goes through `atomic.staged`: written under a temporary name, then moved into place inside the
transaction that writes its `export.image` entry, the file it replaces kept under a temporary name until the
commit and put back if the entry, the move or the commit fails (#241). A file the user named for an export or
Save Image that cannot be written (another program holds it open, a folder of that name) is `AOI-LOG-002`,
naming the file; a Save Image name with a suffix OpenCV cannot encode is `AOI-INSP-002`. One copy of the
app opens a workspace at a time: `AppContext` takes an exclusive operating-system lock on `<workspace>/.aoi.lock`
(`aoi/data/workspace_lock.py`: `fcntl.flock` on POSIX, `msvcrt.locking` on Windows, on a byte past the empty file's end
so a backup still reads it) before it opens the log or the database, and lets go in `close()` and on every refusal; a
second copy is refused with `AOI-SET-012` before it touches anything. The system drops the lock when the process ends,
so a crash or a power cut never blocks the next start. Holding it, the start-up sweep removes every temporary file the
writer names (`.<name>.<8 hex digits>.tmp`, `atomic.temp_path`, the migration backup's included) as a crash's leftover;
a file with another program's name is left alone, and one that cannot be deleted (read-only, held open) is logged as
`sweep.skipped` with its path relative to the workspace and kept, never a start-up failure (#204). Every error a user
can see is
an `AoiError` from the catalogue in `aoi/errors.py`, with a code `AOI-<AREA>-<NNN>`, what happened and what to do;
`docs/error-codes.md` is generated from it (REQ-LOG-004, REQ-SET-019). An error's title, what happened and what to do
are `Phrase`s (`aoi/errors.py`, no Qt), each catalogue text marked `QT_TRANSLATE_NOOP("Errors", …)` so it is in
`aoi_ko.ts` (a test checks every one): the English template with its translation context and the values that
fill it, a value being a phrase in turn where it is words (the action a role check names and the roles it needs, a
Recipe Editor quantity, the page an unexpected error stopped on, the reason the engine gives; a list of reasons is
joined by a phrase too, `joined()`). Their str is the English text the log keeps; a template not yet filled stays one
through copy, pickle, `dataclasses.asdict` and the alarm JSON. `phrase_text()` in `aoi/ui/errors.py` translates a template first and fills it after, for the dialog, Compare's
AOI-CMP-001 note, the Golden board pane and the alarm list (#198); a translation whose placeholders do not fit leaves
the English. A training run's progress lines (aligning, what it trains on, a stop, the calibrated thresholds and the
rule that set them) are phrases under the context `Training` too, which the Training log shows through `phrase_text()`;
the AI model file keeps the rule as plain English text (#199). `aoi/logging_setup.py` writes the JSON-lines
log in `<workspace>/logs/`, one file per UTC day, with time, level, module, event, ids and the app version, and never
an image or a password; a caller's extra never replaces one of those fixed fields (one of the same name is written as
`extra_<name>`, #171). An error code's personal values (`ErrorCode.personal`: AOI-USR-002's user name) reach the log
only as the user's UUID: `report_error` logs `AoiError.log_safe()`, the same error and trace with them replaced, and
its alarm line that text, while the dialog and the stored alarm keep the name (REQ-LOG-004, #195).
Alarms (an NG verdict, a missing AI model, every error shown but Compare's AOI-CMP-001 note and
the refusals a quiet Compare run says on its test pane) are stored in `alarms` with their code
through `AppContext.alarm` (an NG verdict's in its record's own transaction, `Database.add_inspection`, so a saved NG
board always has its alarm and a refused alarm saves neither, #179), and `AppContext.report_error` is the one path for
an error a dialog shows: it
logs the stack trace with the build version, stores an ERROR alarm and returns the plain report that
`aoi/ui/errors.py` shows (code, title, what happened, what to do), also for unhandled errors through
`sys.excepthook`; it never raises, so the dialog shows even when the database refuses the alarm (logged as
`alarm.not_stored`, #171). SQLite's refusal while another program holds the database's lock during work becomes
`AOI-SET-013` there, and the alarm of an error caused by that lock waits 200 ms for it, not SQLite's 5 s (#195). The
Inspection page's own alarms (no AI model yet, a run stopped by a board model change) and the Golden board alarm
(#195) wait the same 200 ms for that lock, not 5 s on the UI thread, and never raise either: one the database
refuses is logged as `alarm.not_stored`,
and the result, its AOI-INSP-008 or the stop goes on (#179, #195). A header change while the pool thread saves the
board in hand still waits for that save first, up to 5 s: `Database.add_inspection` holds the database's thread lock
through SQLite's wait, and the alarm and every read of the database on the UI thread wait for that lock.
Compare's AOI-CMP-001 note is shown in the page without a dialog or an alarm. A Golden board file that the Recipe
Editor or Compare cannot read is shown on its pane, with the code and what to do, without a dialog (the file's name
may break after each _ and -: `breakable_names`, #245);
`AppContext.golden_board_unreadable` logs `golden_board.unreadable` as a warning and stores an ERROR alarm with that
code once per board model, file and code while the app runs (it remembers each one it alarmed), so showing a pane
again, or the file going back to a state already alarmed, adds none (#195). Both pages
read the Golden board again when shown if the file, or which file it is, changed since their last read
(`Page.golden_board_stamp`); inspecting a board of
that board model is refused with AOI-INSP-009, which is alarmed; Compare then clears the verdict of the board
before, says on its test pane that the board was not inspected, and judges it when shown again once the Golden board
can be read (#176). A run Compare starts without being asked (shown again, or a header change) is quiet: when no
check can judge its test image (AOI-INSP-010) or the Golden board keeps it from being judged (AOI-INSP-009), the test
pane says so, the log keeps it as `compare.not_inspected` with the trace, and no dialog opens and no alarm is stored
for it. A run a user asks for (Re-evaluate, Test Image..., Reference..., Golden Board) logs and alarms its refusal on
the pool thread, so a run cancelled or replaced keeps it (#206), and shows the dialog unless it was left. A header
change stops a Compare run still going under the last board model (its result and dialog are dropped; a refusal it was
asked for is still logged and alarmed), takes Compare's verdict, table and picture away at once, and judges its test
image when Compare is shown (`MainWindow` calls `on_show` next when it is; a link that opens Compare on a record or a
file skips that judgement), never behind the page in use; "+ New" with the name of the board model in the header changes
nothing, so a stored result on Compare stays (#247). Compare's stored result clears both panes at once; a stored map
that cannot be read (AOI-CMP-003) takes away only the heat views, and a stored overlay that cannot be read (AOI-CMP-006)
only the picture: the pane shows the golden board as judged, the dialog names the file and the note under the verdict
keeps its code. Any other error (a database another program holds: AOI-SET-013) leaves both panes empty, each with the
dialog's code. Each is logged and alarmed on the pool thread, and nothing of a load shows once the page has moved on
(#247). The page in use is kept in `settings.json` and reopened at start-up (REQ-INSP-006, REQ-LOG-005);
a page change writes that key alone. A workspace saved on Settings goes to `settings.json` only: the running app keeps
its database, log and folders on the open workspace until the restart (REQ-SET-001, #170). The AI device, the
default epochs and input size and the log retention apply at once: `save_settings` resolves the AI device again and,
when it changes, logs `device.change` and drops the cached weights; the cache holds a model with the device it sits
on and is used only on the device in use, and a load running during the save is not cached, so the next inspection
loads the weights on the new device. A training run keeps the device read at its start; an Inspection run keeps its
engine, and so its device, until the page is shown again (`on_show` drops it), and takes the new device from its next
board. When shown, the Training page reads the device in use (the run's own while one goes on) and the saved default
epochs and input size (set in its
boxes only when they changed), and the Logs & Export archive button the retention in effect, archiving by the day
count it shows (REQ-SET-002, REQ-LOG-003, #201). The language is stored only: no translation is loaded until the
2H 2027 localisation, so the app shows English whatever is saved.
Every visible string goes through `self.tr()` in a page class (REQ-SET-005, since S19). PySide takes the
most-derived class name as the context of `self.tr()`, while `pyside6-lupdate` files a string under the class that
contains the call, so the base `Page` uses `QCoreApplication.translate("Page", …)`, page titles are marked
`QT_TRANSLATE_NOOP("Page", …)` and shown through `page_text()` (the English title stays the navigation key), and
role names go through `role_text()` and camera views through `view_text()` (the combo keeps the English name as
item data, the key the engine stores). Names the engine stores with a result (check names, sources, rules) stay
English; Compare shows them through its `CHECK_NAMES`, `SOURCES` and `RULES` maps, AI Model Test shows a row's
`pass_fail` key (PASS, FAIL, NO_LABEL) through `MATCHES` (#207), and the Show combo's modes are chosen by index, so a
translation cannot change behaviour. A subtitle that carries a value (Settings shows the
version) overrides `Page.subtitle_text()`; the "No board model yet" empty state every page shows comes from
`Page.no_board_model()`, Home's included. A sentence is never glued from pieces: placeholders are named, `{count}`, and filled with
`.format()` after translation, never with an f-string. `tests/test_i18n.py` scans `aoi/ui` and `main.py` with `ast`
and fails on a string literal passed to a Qt text setter, a text widget, a dialog, a table header or one of this code's
helpers (`fill_table` rows too) outside `tr()`, in a branch of a conditional, an operand, an `or` or a dict lookup as
well (#199), in a part or the literal separator of a `str.join()` or in what `+=` adds (#199 review), on a literal
value an `AoiError` fills its message with (#198), on an unmarked page title, and on a
literal that reaches `tr()`, `translate()` or `QT_TRANSLATE_NOOP()` other than as its literal argument (through a loop
variable, #173, or a name; a `QT_TRANSLATE_NOOP` whose text is not a literal at all, #199), since `pyside6-lupdate`
extracts a literal argument only. A name is followed to the items of the loop it runs over (the matching part of each
when the loop unpacks them, `enumerate` included), else to the literal its function assigned it, else to the module's
unless the function binds the name itself; `self.x` is followed to the literal the file assigns it, and `x += v` reads
like `x = x + v`; a dict lookup or `.get()` on a name reads that dict's values. So
`self.tr(cell)` over the module's rows lets through only cells marked with `QT_TRANSLATE_NOOP` (#199); a value no
literal reaches (a parameter, data from the engine) passes. It does not yet read `str("…")`, items added with
`list.append()` or `.format()` on a name assigned a literal, so Compare's note under the verdict (`" ".join(parts)`)
is not covered. `ALLOWED_LITERALS` there names the few literals that stay,
each with its reason (device names, the language names in their own language, the base class's placeholder title). A
second scan covers the rest of `aoi/`: a literal an engine error or a phrase's `fill()` takes as a value fails, and so
does one a function returns, alone or in a tuple, since a helper's reason reaches an error as a value
(`reason=_unusable(...)` in `aoi/core/anomaly.py`), unless `ENGINE_ALLOWED` names it with its reason (a number with a
unit symbol, a device or image format name, a user's name or log pseudonym, a key Compare words itself), and so does a
`QT_TRANSLATE_NOOP` whose text is not a literal. `aoi/i18n/aoi_ko.ts` is
generated by `python tools/update_translations.py` (pyside6-lupdate over `aoi/`) and a test fails when it is stale; Korean
translations are filled in later with Qt Linguist and compiled with `pyside6-lrelease`. Every source string of that
file and every title, what and action of the error catalogue use only the Charter's terms ("Words we use"):
`tests/test_charter_words.py` fails on a word of a "Not" column in any ending (failed, passing, limits) and on "model"
on its own, `{placeholders}` left out; `ALLOWED_WORDS` there keeps a word used in another sense (an operation that
failed, the image size limit, the folder chooser's window), each with its reason (#207).

`inspections` already carries everything Stage 4 uploads (lot/model/result/timestamp + images); a `lot_id` column is
the only addition expected.

---

## 7. Requirement traceability (Stage 1)

The requirement register is `docs/requirements/stage1.md`; `tools/trace_matrix.py` generates the trace matrix
from it on every CI run (the `trace-matrix` artifact). A pull request's run reads the pull request's own commits from
GitHub's merge of it into its base, and its number and title from the workflow, so a citation of an unknown ID shows
in that run (since #175). The table below is the v0.1 draft's informal check against
the source specifications and stays as history.

History at scale (REQ-LOG-001, S51): `tests/test_logs_history.py` writes 100,000 records into a workspace's database in
one transaction and holds a combined filter (dates, board model, operator, result), an archived month and the last 7
days to 1 s each, in the service and through Filter on the page, and checks from SQLite's query plan that each reads
through an index of migration 0022; it prints the machine, its CPU count and the Python version. Listing every one of
100,000 records at once is not held to it (about 15 s to fill the table on a 4-core VM): a known issue.

Speed (REQ-INSP-007): the CI job "Performance (base vs head)" times `Inspector.inspect` on the regression set's 40
boards at 0.3 MP and 5 MP for the base commit and the head on one runner (`tools/perf_compare.py`) and fails when the
head's median or 95th percentile at either size is over 1.10 times the base's; `tests/perf/test_timing.py` checks a
developer machine against its own `baseline.json` entry. Neither is the product's speed (`tests/perf/README.md`).

Scale (REQ-SET-020): `tests/test_performance_budgets.py` times the start (`tests/startup_worker.py` runs `main.main()`
in a process of its own, timed from before it starts to the window painted) and every page switch, as the Admin, to the
page painted, on a workspace `tools/seed_workspace.py` writes with 50 board models and 100,000 records, and asserts 5 s
and 300 ms on any machine. The 8-hour soak (REQ-INSP-011): `tools/soak.py` presses Next Board in the app's window
every 3 s and judges the run by the medians of the first and last tenth after a warm-up; `tests/test_soak.py` runs it
for 72 s.

Public datasets (S30, REQ-INSP-014): `tools/dataset_check.py` runs the golden-board comparison with the AI check off on
DeepPCB and PKU-Market-PCB, laid out as their authors publish them, and with `--ai` the AI model alone on DeepPCB's test
split, with `--min-area` as a what-if on the Minimum defect area; it hashes every file it reads before and after its
checks, and writes counts, times, peak memory and the machine's threads and library versions outside the repository and
the datasets. Both are research-use datasets, used for internal checks only with Jay's written approval of 2026-10-08:
no image, box or model trained on them enters the repository or ships, and their counts are never an accuracy claim. The
runs are recorded in `docs/tests/2026-10-08-public-dataset-check.md` (DeepPCB in the cloud, then DeepPCB and
PKU-Market-PCB on Jay's laptop), and ADR 0008 (proposed) keeps the default Minimum defect area of 40 px until the customer's size is agreed.

Training the comparison (REQ-TRN-018): `aoi/core/tuning.py` counts, for each pair of Pixel difference and Minimum defect
area it tries, the boxed defects a labelled board's difference map finds and its defect-free 512 px windows that a
region falls in, and chooses the pair with the fewest false calls among those that miss at most 1 % of the boxed
defects. `tools/dataset_check.py --tune` runs it on PKU-Market-PCB with 30 % of each board's photos of each type held
out (`docs/tests/2026-10-09-comparison-training.md`); the app's defaults do not change, and no AppContext method or
screen runs it on a board model's samples yet.

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
* No signed Windows installer yet: stations run from source, and CI builds an unsigned one-folder test build and an
  unsigned installer of it on main and on every `v*` tag, both for internal tests only, and inspects one synthetic
  board with the build and with the installed app (ADR 0007).
