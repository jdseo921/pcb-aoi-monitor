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
│  writes  import_samples · train · save_recipe · set_reference · set_scale    │
│          add_user                                                            │
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
no `Inspector` built by a page (REQ-USR-001, since S15) and no image read outside `AppContext.load_image` (since S23c),
whatever module a name comes through, `Database` and the readers that services imports included, and a second test
fails a screen module that holds one of them once imported (#202). `aoi/times.py`, `aoi/errors.py`, `aoi/config.py` and
`aoi/defects.py` are shared by every layer.

Types (Code style, since S22): mypy runs strict on `aoi/core`, `aoi/data` and `aoi/times.py`, and since S22a on `aoi/ui`
and `aoi/hal` too, with no flag relaxed (`pyproject.toml`). PySide6 enums are written in full
(`Qt.AlignmentFlag.AlignCenter`), pages take `QT_TRANSLATE_NOOP` from `aoi/ui/pages/base.py` (Qt's is typed as returning
object; it is the one of `aoi/errors.py`, which returns a `Phrase`, a `str` subclass, so every page title and role name
is one), and no widget attribute carries a QWidget method's name: `size`, `pos` and `render` hid `QWidget.size()`,
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
will appear (after 1 s the time so far; after 10 s a bar and Cancel, with progress and the time left only for a job
that reports steps: folder import, the + OK and + NG Images copies and the two Logs exports; Compare, the AI Model Test
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
Closing the window stops the background work (#171): while a job runs `MainWindow.closeEvent` asks first (No keeps the
window open), then `AppContext.close` cancels every job, waits for it and closes the database and the log, and the slots
the jobs queued are dropped unrun, and the workers that waited for them let go (`workers.drop_queued`); `main.py` closes
the context again after the event loop (a no-op). A stopped training run saves nothing (REQ-TRN-008), and the Training
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
built from them with `theme.stylesheet()`, so another theme is a set of overrides (REQ-SET-008); a page never writes a
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
states hold a selected defect row on Inspection and a bar at 100 % on Training, so both are measured (#203). Every list
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
on a styled widget is undone when the stylesheet is applied.

### Workspace on disk

```
AOI_Workspace/                 (default ~/AOI_Workspace, set in Settings, used from the next start, or AOI_WORKSPACE)
  aoi.sqlite                   database
  logs/aoi-YYYY-MM-DD.jsonl    JSON-lines log, one file per UTC day (REQ-LOG-004)
  settings.json
  images/<board>/<OK|NG>/      uploaded training samples (copied in, so source folders can move), each named
                               <stem>_<sample UUID>.<ext>; a copy whose path the system refuses as too long stops
                               the import with AOI-TRN-011 (#245)
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
Step 6 sets the new golden board as the reference, registers and activates the version and writes `model.train` in one
transaction: if it fails, the reference and the active version stay and the run's two files are removed. A version
never takes a name whose `.pt` or `_golden.png` is on disk, so a golden board a result names is never written over (#178).
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
`set_scale` refuses a scale outside 0.01 to 100000 px/mm, so that no size in mm overflows in px (AOI-RCP-008). The scale
is a number an Engineer sets, not one read from the images: a Golden board of another size (a new camera) keeps it, so
after a camera change the scale is calibrated again on the new Golden board before boards are judged, and until then
sizes in mm keep their px (nothing compares the Golden board's size with the calibration image yet; open with Jay). The
compare step's 5 × 5 blur, ±2 px shift tolerance and noise clean-up stay in px: on the synthetic regression set at twice
its size, the scale set to twice its own, the size in mm keeps 38 of the 40 verdicts, and two NG boards that the default
recipe misses at 1x by a few px are found (`tests/regression/test_resize_verdicts.py`; with the size left in px, seven
change).

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
* **Roles** (GUI §8). Disabled entries show a tooltip naming the required role.

| Page | Operator | Engineer | Admin |
|---|:-:|:-:|:-:|
| Home, Inspection, Compare, Logs (view) | ✓ | ✓ | ✓ |
| Logs export / archive | | ✓ | ✓ |
| Training, AI Model Test, Recipe Editor, 3D Profile | | ✓ | ✓ |
| Compare → Try other thresholds (thresholds, Re-evaluate, Save to Recipe) | | ✓ | ✓ |
| Settings (users, workspace, device, hardware) | | | ✓ |

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
| `ensure_board_model`, `set_reference`, `import_samples` | Engineer | `board_model.create`, `board_model.reference` (reference path), `sample.import`; object = board model name |
| `set_scale` | Engineer | `board_model.scale` (px per mm before → after, with the length in px, the distance in mm and the Golden board file it was measured on; S29, REQ-RCP-006); object = board model name. A length or distance that is not a number above 0, a scale outside 0.01 to 100000 px/mm, or an unknown board model, is `AOI-RCP-008`, nothing written |
| `update_sample`, `delete_sample` | Engineer | `sample.update` (label, defect type), `sample.delete`; object = sample UUID |
| `train`, `activate_model` | Engineer | `model.train`, `model.activate` (active version; an older one is a rollback; `model.train` also the Golden board before); object = model UUID |
| `save_recipe` | Engineer | `recipe.save` (recipe body); object = recipe UUID. A revision that sets, changes or clears the AI score threshold's override is also audited as `recipe.ai_threshold` (revision, override, the threshold that judges, the active AI model's version and calibrated value); object = board model name (REQ-TRN-015) |
| `batch_test` | Engineer | `test.run` (folder, model version, metrics); object = board model name |
| `export_model`, `export_overlays`, `export_csv` | Engineer | `export.model`, `export.overlays`, `export.csv` (destination, relative to the workspace when inside it, else in full (#196); counts) |
| `export_csv_files` | Engineer | `export.csv` once per file (destination, stored as above, and row count); object type = what the rows are. Logs & Export's records and checks: the files are written all or none (`atomic.write_all`), a file that cannot be written is `AOI-LOG-002` naming it, the entries go in one transaction, and the files are removed when the entries cannot be written (#195) |
| `export_report` | Engineer | `export.report` (destination, stored as for the exports above, board model, run UUID, AI model version, bytes); object = test run UUID. The page renders the PDF in memory and the service writes it through `atomic.py`; an export that cannot be written is `AOI-LOG-002`, as for `export_csv` (#180) |
| `export_board_image` | Operator | `export.image` (destination, stored as for the exports above, board model, the board's file name, verdict); object type `inspection`, object = the record's UUID, none for a result that was not saved. Save Image… (F9) on Inspection, run on the pool as the user who pressed it: the picture with its defect boxes is encoded first (a name with no image format is `AOI-INSP-002`), written beside the destination under a temporary name (`atomic.staged`; a file that cannot be written is `AOI-LOG-002`), and moved into place in the transaction that writes its entry: when the entry cannot be written, the move fails or the commit fails, the destination is left exactly as it was, a file of that name unchanged and a folder made for it removed (#178, #241). The record is read before the write, so a read that fails leaves no picture. The page reads the result, the record and the board model when F9 is pressed, before the file dialog, whose event loop lets a run go on, so the entry always names the record whose picture it saved. Operator is the lowest role, so every role keeps F9 (REQ-INSP-005); the page enables F9 for the role in `REQUIRED_ROLE`, so whether #151 takes it from Operators is one word |
| `archive_old` | Engineer | `inspection.archive` (days, count); the retention run at start-up is a system action: logged, not audited |
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
| **Compare** (optional) | Golden reference and test board **side by side** with **synchronised zoom/pan**; views under Show: Side by side (the Golden board with a dashed box per defect beside the test board with its labelled boxes), Difference heatmap and AI score heatmap (the test board under its map), Defect boxes only (the Golden board pane hidden and the test board with its boxes fitted to the width of both; any other view brings the pane back and fits the board to its half again, and so do "Compare with Golden board ›", Use Last Inspected, Golden Board and Reference…, which ask for a Golden board and switch Defect boxes only to Side by side, while Test Image… and Re-evaluate keep the view; the hidden pane moves no zoom of the shown one, #248); **decision table** (check, source, value, threshold, rule, result) with failing rows highlighted, from the **stored result** when the page opens on a record (row for row the stored checks, never a new inspection: REQ-CMP-003; one click from Inspection, REQ-INSP-009) beside the golden board it was judged against, which inspecting the board again on Compare keeps until Golden Board is pressed (not shown, with the reason and Re-evaluate › as the next step, when that file has changed, cannot be read or is gone, or none was recorded), with a note naming the AI model version active when the board was judged and the recipe revision that judged it (which says whether the AI check ran; the "why" box says so when it was off, #246) and what changed since (for a result judged at another scale than the board model's now, both scales: Re-evaluate applies sizes in mm at the one it was judged at, the form shows them at the board model's, S29); plain-word "why" box, one sentence per failing check, NG first (REQ-CMP-004); **Try other thresholds** (the minimum defect size in mm when the board model has a scale; Save to Recipe keeps one left untouched as the recipe holds it) for Engineer and Admin (hidden for an Operator, whose boards Compare judges by the recipe: when an Operator signs in, on any page (`on_user_changed`), the form goes back to the recipe's thresholds, read once then, and a board inspected with another recipe than that one (`judged_by`, in px at the board model's scale then: the form's thresholds not saved, a revision saved since, or a scale set since that gives a size in mm other px, S29; values that did not judge the board are not counted, `_judging`: the AI score threshold, and an ROI's AI score and name, when its AI check did not run, the AI check off or no AI model active, the Golden board comparison's own thresholds, Minimum defect area aside, which also sizes the AI model's defects, when the comparison did not run, and a disabled ROI and an ROI's Stage 2 heights, volumes and side, which nothing reads yet; a board still worked out is held by the recipe's switches) is cleared, a run of it still going stopped, and inspected again by the recipe once Compare is shown, one cancelled left so) with Re-evaluate (Ctrl+R) and Save to Recipe, the AI score threshold an `AiThresholdField` as on the Recipe Editor, but with its sketch's label, "Override the AI model's value 3.063", in a row of its own under the field, as its note is, as wide as the panel (beside the field it widened the window to 1779 px), that names, on a stored result, the calibrated value of the AI model that judged it, which Re-evaluate applies (AOI-TRN-012 naming the version the result gives when the registry no longer holds that AI model), and else the active AI model's, a stored result judged with the AI check off included (REQ-TRN-015, #246); with no value to name, the tick, "Set my own value", goes back beside the field, so that tick and note never both take a row (Tab reaches the tick in reading order wherever it sits, and a tick with the focus keeps it as it moves): on a stored result Re-evaluate judges it again from its stored maps on the pool thread, without the AI model (`AppContext.re_evaluate`, REQ-CMP-005), under "Re-evaluating…" over the decision table and the "why" box once it takes a second, which goes with the answer or a refusal's dialog, not at the job's end, Re-evaluate off meanwhile and the focus, when it was on it or on another control the run turns off, in the "why" box, one Tab before Cancel once that shows, so a second Space presses nothing, and back on Re-evaluate at the end unless moved to a control other than Cancel, and on it after Cancel, pressed by key or click, and when the run ends or is stopped while Cancel has the focus, as Cancel hides then, or in the "why" box when an Operator's sign-in hides the panel, as is a focus left in the panel then, run or not; Re-evaluate is off too while a stored result's pictures and maps load, another result shown at a run's end or by Inspection's "Compare with Golden board ›" (which shows Compare with the focus it last had there), and a focus on it waits in the "why" box then as well and goes back once they have loaded, never on to Save to Recipe (one rule where Re-evaluate is turned on and off, `_sync_roles`; the window's `focusWidget()` is read, which holds the focus while another window is in front, when no control `hasFocus()`; REQ-SET-021, review, verification), and shows "Would be: <verdict>" beside it (bold, beside a bar of the verdict's colour, `theme.verdict_mark_style`, so it never reads as a third button) while the banner keeps the stored verdict, the decision table and the "why" box showing the checks those thresholds give (the board keeps the stored boxes, which the "why" box says when defects make the WARN) until a threshold or the recipe changes, another run or result shows, the board model changes or an Operator signs in on any page (a re-evaluation still running is then stopped); on any other board it inspects again; the thresholds are loaded again from the recipe once another revision is saved or the scale changed, so Save to Recipe never reverts one; Save to Recipe (Ctrl+S, the page's one blue primary, on only for a role `save_recipe`'s @requires allows, `REQUIRED_ROLE` #241, while a threshold of the form differs from the recipe as the engine reads them, an AI score threshold of 0 being none, one that did not judge the board shown included, such as the AI score threshold with the AI check off, which an Operator's sign-in does not count, `_judging`, and off while a re-evaluation runs, so no key opens the sheet over it) opens an inline sheet in place of the panel, never a dialog, that lists each threshold that changes, before → after (no override as "the AI model's calibrated value" while `calibrated_threshold` reads one for the board model's active AI model as the sheet opens, else "none", as the save's audit entry then names no threshold; never the AI model the panel names, which may be a stored result's), names the revision the save makes and asks for a reason, without which Save Revision (a plain button) is off; Save Revision, or Enter in the reason, stores the next revision through `AppContext.save_recipe(recipe, reason)`, audited as `recipe.save` with the recipe before and after, the user, the time and the reason, and the stored result keeps its verdict, while Inspection (at its next board) and the Recipe Editor (when shown again) take the revision up as they do one it saves; Cancel, Esc, any sign-in, any board opened, the one shown included (`show_stored`, once the record is read, so one that cannot be read leaves the page as it was, and `set_test`), a board model change and a revision saved elsewhere meanwhile (AOI-RCP-004, logged and alarmed, once Compare shows again or at Save Revision, which checks the latest revision first: `_take_up_revision`) close the sheet with nothing stored, the focus going back to the panel only from inside the sheet, as at a run's end, or to the "why" box while Save to Recipe and Re-evaluate are both off, a stored result still loading, and on to Re-evaluate when the load ends if it is still there (`_refocus`, `_sync_roles`; S28d); a record's board is judged again only under its own board model (Re-evaluate under another is refused with AOI-CMP-005, and a board model change drops it); Cancel on the busy overlay leaves no verdict under the name of the board cancelled (#172); pick any reference image instead of the golden template; the file names over the two pictures, in the note (AOI-CMP-001 included) and in the messages on a picture's pane, and the board model Save to Recipe's sheet names, may break after each _ and - (`breakable`, a zero width space; `breakable_names` for the file an error names in the note or on a pane), so a long name, such as a sample's ending in its UUID, wraps there instead of widening the window past the screen or running past a pane's edge; a part of a name with no _ or - in it stays whole, as do the folders of a Windows path between two _ or - (Qt never breaks after a `\`) (#245) | Jay's request |
| **Training** | **+OK / +NG upload** (NG labelled with DCT category, type and view), import folder with `ok/` `ng/` sub-folders; dataset table with relabel / set reference / remove, under a line with the sample counts and the reference image's name, cut at its end to the line's width with the whole line as its tooltip, so a long file name never widens the window past the screen, and under 20 OK samples the tip to import 20 or more on a line of its own (#245); preview; epochs, input size, device; Start/Stop with progress and log; **model version registry** with activate and export `.pt`, each version's Threshold its calibrated AI score threshold as `AppContext.calibrated_threshold` reads it, through `AppContext.calibration_of` over the one registry read of the table (AOI-TRN-012, with the error's text as the row's tooltip and in a muted line under the table, when its registry row holds none usable, REQ-TRN-015), and its OK/NG sample counts, empty where the row's metrics cannot be read | GUI §4.3, Stage 1, §6 model version control |
| **AI Model Test** | Select labelled folder; Run Test / Run Test Again; **Accuracy, Precision, Recall, False Call Rate** tiles; confusion counts; results table **Image, Label, Verdict, AI score, Matches label?** (GUI §4.3's GT, AI Result, Score and Pass/Fail in the Charter's words: Matches label, Differs from label in red, or No label for an image outside `ok/` and `ng/`, #207); preview; **Export CSV / Export Report (PDF)**, the report naming the folder and board model the shown results came from, and saying when the recipe turned the AI check off, so the AI model it names did not judge the images (#246); a run's results are shown only under its board model: changing the header's board model clears them, and a run that ends after such a change is stored, not shown (#180); the results are also tied to the AI model, recipe revision, Golden board and scale that judged them (the scale only while the recipe holds a size in mm, S29; a run judged with the AI check off to its recipe revision, Golden board and scale alone, so an activation leaves its rows previewed, and the note and AOI-TST-001 name "no AI model (the AI check off)" in place of an AI model, #246): once another is in use (a training run ended, a version activated, a recipe saved, a scale or a Golden board set), a selected row is not inspected again but shows AOI-TST-001 in the preview pane with Run Test Again for the run's folder, leaving Use Last Inspected as it was, and a line above the table, refreshed when the page is shown or a row selected, names what judged the run and what is in use now, while on show a row still selected is refused in place of its earlier preview, and previewed again once what judged the run is in use again; a new run drops a preview still being inspected and starts with no row selected; the rows, tiles and exports stay, as they describe the stored run (#250); the file names AOI-TST-001 gives in the preview pane (the row's and the Golden boards') may break after each _ and - (`breakable`, on the pane's copy of the error only; the line above the table keeps them as they are), so a long one wraps there instead of running past the pane's edge (#245); runs stored in DB | GUI §4.3 |
| **Recipe Editor** | Draw ROIs on the golden board (zoom/pan); ROI types **Presence, Polarity, Solder Bridge, Height, Anomaly**; parameters **AI Score** (× the AI score threshold: the recipe's, else the AI model's, #248), **Height Min/Max, Volume Min/Max** (each 0 or more, min not above max, "—" for unset; AOI-RCP-002 otherwise); Apply edits the selected ROI only and is off while none is selected (Delete clears the selection); yellow = selected, green = saved; global thresholds, the AI score threshold an `AiThresholdField` (`aoi/ui/widgets/ai_threshold.py`, REQ-TRN-015): a tick, "Override 3.063", names the active AI model's calibrated value, which the greyed field beside it shows until the tick is set; ticked, the field starts from that value to every decimal, named again as the tick is set (`ticking`), so an AI model trained or activated while the page stays shown gives it, and holds the override, given back as the recipe holds it until it is edited (more decimals than 3, or outside 0 to 10000; 0 is none), and clearing the tick restores the calibrated value; with none to name, the tick reads "Set my own value" and a note under it, a row as wide as the form, says why (no AI model trained, none active, or AOI-TRN-012 with what to do), and ticked, the field starts from 0, no override until a value is typed, never from a value shown for another board model; **mandatory AOI set** checklist (DCT §4) marking checks that need Stage 2 3D/side cameras; Test Run, cancelled with its verdict cleared when the board model changes; Save Recipe → revision with user + timestamp; at the board model's scale (REQ-RCP-006) the ROI table and the minimum defect size are in mm, the size with the px it spans beside it (`aoi/ui/widgets/scale.py`, shared with Compare), and Save Recipe stores them in mm (`Recipe.in_mm`: the same sizes, so a recipe saved untouched judges as before), and until then AOI-RCP-009 in amber under the scale says that the latest revision still holds sizes in px, which keep their px when the scale is set again after a camera change, and that Save Recipe stores them in mm (`held_in_px`; word-wrapped, with what to do in view, as touch and keys reach no tooltip); without one they are in px beside AOI-RCP-005 in amber (Q21). A revision saved after the editor loaded its own (Compare's Save to Recipe) is shown when the editor opens again, after asking when it holds unsaved changes; kept changes cannot be saved over it (AOI-RCP-001) | GUI §4.2, DCT §4 |
| **3D Profile** | Layout placeholder (height map, defect details, Accept/Reject) until Stage 2 3D data exists | GUI §4.5 |
| **Logs & Export** | Filter by date (2000-01-01 to 2100-12-31), model, operator; sortable table; overlay preview of the selected record (the placeholder when it has none, and after Filter); Export CSV (two files, UTF-8 with BOM: the records, with their columns as before and the record, model and recipe UUIDs and `ai_check` appended, and `<name>_checks.csv` with one row per check: region, metric, source, value, threshold, rule, result, the model and recipe UUIDs and `ai_check`, its header written even when no record has checks; REQ-INSP-012; `ai_check` says whether the AI check ran on the record, RAN, OFF or NO_AI_MODEL, empty for a record stored without its result or whose stored result cannot be read, which is logged as `export.result_not_read` and stops no export, #246) / overlay images with confirmation; auto-archive older than the log retention, 30 days by default (on start, and on demand by the day count the button shows) | GUI §4.4 |
| **Settings** | Workspace, AI device (auto/CPU/CUDA), defaults, retention, language (en/ko placeholder for 2H 2027 localisation); users & roles; hardware interface status per stage | GUI §6, §8, RM 2H 2027 |

---

## 6. Database schema (SQLite)

| Table | Key columns |
|---|---|
| `board_models` | name (a new name that differs from an existing one only in case is refused, AOI-TRN-005: Windows would give both the same model and golden board files), reference_image (golden), px_per_mm (the scale its recipe's sizes in mm are applied at, a finite REAL above 0, which a CHECK holds; NULL until an Engineer sets one, and for rows from before migration 0012) |
| `samples` | board_model, path, label OK/NG, defect_type (DCT), side |
| `models` | board_model, version, uuid (also in the `.pt` file's metadata, written there before the file is saved, so an exported file names its record), path (.pt), metrics JSON (thresholds, scores, timing), active (one version per board model, switched in one transaction, so no reader finds none active, #171) |
| `recipes` | board_model, revision (1 is the default recipe, stored when the board model is created, so every result names a stored revision), uuid, body JSON, user, created_at |
| `inspections` | time, board_model, model_version, model_uuid (the AI model version active when the board was judged; whether the AI check ran is the recipe revision's to say, and a result judged with it off carries `AI_OFF_NOTE`, #246), recipe_rev, recipe_uuid, image/overlay paths, diff_map_path and ai_map_path (the difference and AI score maps as PNG files beside the overlay, 8-bit exact, and 16-bit within one step: `_ai2.png` since S28a, 0.001 σ steps to 32.767 σ, then 1/8192 of the value to 1789 σ, or `_ai.png` before, 0.001 σ steps to 65.535 σ; NULL for rows from before migration 0007, and for OK results once the retention sweep deleted them), reference_path and reference_sha256 (the golden board file the result was judged against and the SHA-256 of its bytes; NULL for rows from before migration 0008 and for results judged without a golden board), view (Top, Side or Bottom; NULL for rows from before migration 0005), result, score, metrics JSON, result_json (the whole result as `InspectionResult.to_dict` writes it, read back by `from_dict` without the images, with the scale it was judged at, `px_per_mm`, when there was one; NULL before migration 0006), operator, archived |
| `defects` | inspection_id, no, type, score, side, x, y, w, h |
| `checks` | inspection_id, no, region (Board, or the ROI's name and box), metric, source, value, threshold, rule, result, explain: one row per decision variable of a result (REQ-INSP-012; none for rows from before migration 0006) |
| `test_runs` | uuid, time, board_model, model_version, model_uuid (NULL for runs from before migration 0009), folder, metrics JSON, results JSON (one row per image; its `image` path stored like `folder`, and `ai_check`, RAN, OFF or NO_AI_MODEL, since #246); the AI Model Test CSV and report name the run and the AI model active then by UUID, and say when the recipe turned the AI check off |
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
Records that can leave the station (`users`, `samples`, `models`, `recipes`, `inspections`, and since migration 0009
`test_runs` and `alarms`) carry a `uuid` beside their integer key; `defects` and `checks` are rows of one inspection and
are named by its UUID and their `no`. The dataset record, with its UUID, arrives with frozen dataset versions (stage
S35, REQ-TRN-005). Every stored time is ISO 8601 UTC with an offset and is shown in local time
(`aoi/times.py`); image, overlay, map, golden board, model and validation folder paths inside the workspace are stored
relative to it and resolved by `aoi/data/paths.py`, so a workspace folder can move (REQ-SET-017, REQ-SET-001). A path
outside the workspace (a validation folder on a USB drive) is stored absolute and read as written, as are the paths of
validation runs stored before migration 0009. The Logs filter's local days become UTC bounds in `aoi/times.py`, where
a day the clock cannot convert is no bound on its side, never an error (#174).
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
