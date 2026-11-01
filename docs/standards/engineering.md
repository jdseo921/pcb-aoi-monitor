# AOI Standards – Engineering

> **Copy.** Exported whole from [AOI Standards – Engineering](https://claude.ai/code/artifact/346f0966-33e4-4134-9fa6-c0ddad0758db) (Claude Docs, revision 11) on 2026-11-01. The source stays where Jay edits it; a change there is re-exported here in a pull request; if the two differ, the source wins until it is. What the export changed: [README](README.md#what-the-export-changed).

Oct 1, 2026 · @Jay Dongha Seo

**Mandatory.** Every implementation and code change made by Claude Code follows this standard, and other top-tier AI models review its responses and work. The review rules and the checklist for every change are in [AOI Standards – Charter](charter.md).

The app is one Python engine behind one service API, with thin PySide6 screens on top; every rule below can be checked in code, in tests or on screen.

## Architecture and code

The UI, tests, the robot cycle and a future site server all reach the engine through `AppContext`, and calls only go down.

*The source shows this as a drawing; its text is transcribed here, see [README](README.md#what-the-export-changed).*

**Everything reaches the engine through one front door, and calls only go down.** Layers of the current build; the
callers marked *later* arrive in later stages (dashed in the drawing).

| Layer | Parts |
| --- | --- |
| Callers | Desktop UI (PySide6 pages); Tests and CLI (headless runs); Robot cycle (Stage 3, *later*); Site server API (multi-station, *later*) |
| **AppContext: the one service API** | import samples, train, inspect, batch test, export, recipes, model versions |
| Inspection engine (no Qt imports) | Imaging (I/O, alignment); Anomaly model (self-training); Compare (golden board); Inspector (checks, verdict); Recipe (ROIs, thresholds) |
| Data and hardware | Data store: SQLite + workspace folder (images, models); Hardware adapters: camera, lighting, robot, MES + simulators |

*The arrows, in words: each caller calls AppContext, AppContext calls the engine, and the engine calls the data store
and the hardware adapters.*

Arrows are the only allowed calls; nothing below calls upward.

- **Layers (MUST).** UI, then `AppContext`, then the engine, then data and hardware adapters. `aoi/core` and `aoi/data` never import PySide6, and a test fails the build if they do.
- **One service API (MUST).** `AppContext` methods are typed and documented. A breaking change bumps the minor version before 1.0 and the major version after.
- **Results are data (MUST).** `InspectionResult`, `Check` and `Defect` serialise to JSON unchanged for logs, reports and MES.
- **Hardware is a plug-in (MUST).** Cameras, lighting, the robot and MES implement the `aoi/hal` interfaces, and each ships with a simulator for demos and CI.
- **One codebase (MUST).** Editions and customer needs are settings, license flags or plug-ins, never forks or customer branches. Thresholds, paths and devices live in settings or recipes, never as constants in pages.
- **Code style (MUST).** Python 3.11, type hints on every public function, `ruff` for lint and format, strict `mypy` on `aoi/core` and `aoi/data`, and a lock file that pins exact versions.
- **Built for scale (SHOULD).** Plan for 3 views per board, about 3,000 boards per 8-hour shift and 50 or more board models per station. More stations share models and results through a site server that calls the same API; no inspection logic moves into it.

## Screens

Each screen serves one role and one job; for the operator, that job is a correct verdict read within 3 seconds.

- **Role first (MUST).** Operator screens show run controls, the verdict and the defects only. Thresholds, ROIs and models live on Engineer pages, gated by role.
- **Verdict first (MUST).** The verdict banner leads, then the defect on the image, the defect list and the metrics. Every NG and WARN opens Compare on that board in one click, with the failing checks highlighted.
- **One frame (MUST).** Every page shares the header (board model, user and role, and station state once hardware is connected), the sidebar groups Production, Engineering, Data and System, and one blue primary button. Destructive buttons are red and never focused by default.
- **Short paths (SHOULD).** Any function is at most 2 clicks from Home, no dialog opens on top of another, and advanced settings sit one level down. Ask for confirmation only before deleting data, overwriting a recipe or exporting; make everything else undoable.
- **No dead ends (MUST).** Every empty state says what to do next and links there. Errors say what happened, why and what to do, with a code such as `AOI-CAM-003`; stack traces go to the log only.
- **Look (MUST).** Colours, sizes and fonts come only from the `theme.py` tokens: OK green #43A047, NG red #E53935, WARN amber #FDD835, accent blue #1E88E5. Every verdict and severity pairs its colour with a word and a shape. A dark production theme and a light presenter theme ship by release 1.0.
- **Sizes (MUST).** Text at least 14 pt and the verdict at 40 pt, buttons at least 120×40 px (GUI §7), operator touch targets at least 48 px tall, and text contrast at least 4.5:1. Layouts work at 1920×1080 and are checked at 1366×768 and at 4K with 150–200% scaling.
- **Input (MUST).** Every operator action works by touch and by keyboard: F5 Start, F6 Stop, F8 Next Board, F9 Save Result, and from Stage 3 the robot trigger. From Stage 2 a barcode scanner fills the lot or serial number without the user first selecting a field (SHOULD).
- **Language (MUST).** Every visible string goes through `self.tr()`, with no sentence glued together from pieces, and translations live in `aoi/i18n/aoi_ko.ts`. Dates are ISO (2026-10-01) with 24-hour time and metric units, and a bundled Noto Sans KR font renders Korean the same on every PC. When the Korean UI ships is open in the Charter.
- **Screen code (MUST).** One file per page in `aoi/ui/pages/`, with no SQL, file paths or image maths inside a page. Slow work runs through `Worker` on the thread pool, and widgets change only on the UI thread. Every page renders offscreen at 1920×1080 in CI and is compared with an approved screenshot. Reuse `ImageView` and `make_table` before writing a new widget (SHOULD).
- **Live results (SHOULD).** Batch runs show each board as it finishes, and from Stage 2 camera previews stay at 10 fps or more without delaying a verdict.

## Data and storage

SQLite plus one workspace folder per station is the system of record, and anything that can change a verdict leaves an audit entry with who, when, and the values before and after.

- **Migrations (MUST before the first customer install).** Numbered files in `aoi/data/migrations/`, applied at start-up and recorded in a `schema_version` table. A shipped migration is never edited.
- **IDs and time (MUST).** Every record that can leave the station (inspection, model, recipe, dataset) carries a UUID beside its local number. Times are stored in UTC as ISO 8601 with an offset and shown in local time.
- **Images (MUST).** Originals are never modified; overlays and heatmaps can be regenerated. Paths are stored relative to the workspace, so the workspace can move.
- **Crash-safe writes (MUST).** Write to a temporary file, then rename, and run SQLite in WAL mode, so a power cut never corrupts a finished inspection.
- **Disk and retention (MUST).** Alarm at 80% disk use; at 95%, stop saving OK images and keep only NG evidence. Logs archive after 30 days (GUI §4.4), image retention is set per customer, and nothing is deleted without an Admin action.
- **Stations stand alone (MUST).** A station keeps inspecting when a server or the network is down; results queue locally and sync later. A future site server runs PostgreSQL (SHOULD), and the UUIDs keep merged records unique.
- **Audit trail (MUST).** Recipe saves, threshold edits, model activations, user changes and exports are stored with user, time, before and after, and the UI cannot edit them.
- **Logs and errors (MUST).** JSON-lines logs with time, level, module, event and IDs, rotated daily in `workspace/logs`, with no images and no personal data. One catalogue of `AOI-<AREA>-<NNN>` codes serves screens, logs and the manual. An unhandled error is logged with the build version and shown as a plain message, and the app reopens on the last page.
- **Support bundle (MUST by release 1.0).** One Admin button zips logs, settings, versions, the schema version and recent metrics; images go in only if ticked.

## AI models and data

A model goes live only with its data, settings and scores on record, and any station can return to the previous model in one click.

- **Capture (MUST).** One fixed set-up per board model: same camera, lens, distance and angle, a jig, enclosed diffuse lighting, and locked manual exposure, white balance and focus. The smallest defect to catch spans at least 4 pixels. Images are PNG (customer JPEG at quality 95 or more, never re-saved), named `<board model>_<revision>_<serial>_<view>_<UTC time>.png`, with a JSON record of the session set-up beside them. A new PCB revision gets its own golden board and model.
- **Labels (MUST).** Each image is OK, NG or UNSURE; UNSURE images stay out of training and go to the customer's quality engineer. Each defect gets a tight box and one of the 33 types in the defect classification table, with its severity. A second person checks every NG label and 10% of OK labels, and before a customer validation two labelers agree on OK or NG for at least 98% of a 100-image calibration set and on defect type for at least 90% (proposed).
- **Datasets (MUST).** Frozen versions such as `DS-TBOXA1-R3-TOP-v4`, each with a manifest of SHA-256 file hashes; a relabel creates a new version and the old label stays in history. Train on at least 20 OK images per board model and view, 50 or more recommended. The validation set is locked before training, holds at least 50 OK images and 30% of the NG samples, and is never trained on.
- **Lineage (MUST).** The `.pt` file records seed, code commit, settings and dataset version, and retraining the same inputs reproduces the validation metrics within ±1 percentage point. Every inspection records the model version it used.
- **Model card (MUST).** Generated for every version from the training and test records: identity, intended set-up, missed-defect and false call rates with counts and 95% upper bounds, recall per defect type, time per image, thresholds, known limits, and sign-off by the AI and quality leads. A model without a card cannot be activated.
- **Go-live gate (MUST).** A new or retrained version goes live only if, on the locked validation set, it misses no Critical defect the live model catches and its false call rate rises by at most 1 percentage point. It installs inactive, the customer's engineer activates it, and rollback stays one click.
- **On the line (MUST).** Each shift starts by inspecting master samples, a known-OK board and a known-NG board for each Critical type the recipe checks where samples exist, and production stays blocked until every verdict is right. Overridden verdicts are saved with the image and the reason, and a defect found later, at functional test or as a return, becomes a regression case.
- **Watch and retrain (SHOULD).** Each station tracks NG rate, WARN rate, the score spread of OK boards and alignment quality per board model, and alarms on drift. Retrain when the board revision, a key part's supplier, the lighting or the camera changes, or after any missed defect.
- **Customer data (MUST).** One encrypted dataset store per customer, and a training run reads from exactly one. Each dataset records what the customer allowed, their own models only by default, and the pipeline refuses any other use. Models shipped to every customer learn only from synthetic boards, our own boards or data whose owner agreed in writing.
- **Next models (SHOULD).** A defect-type classifier once a board model has about 30 labelled examples per type, and per-view models in Stage 2.

## Performance budgets

Budgets are pass or fail numbers, measured on the reference PC before every release, and the UI never waits on work.

| Measure | Budget | Source |
| --- | --- | --- |
| Click, key or touch | Visible response within 100 ms | Proposed |
| Image in to verdict on screen | 95th percentile ≤ 1 s | GUI §11 |
| Page switch | ≤ 300 ms | Proposed |
| Start-up to usable | ≤ 5 s | Proposed |
| Work over 1 s | A busy indicator where the result will appear; over 10 s, progress, time left and Cancel, and training keeps running if the user leaves the page | Proposed |
| Continuous run | 8 h with no crash; slowdown and memory growth ≤ 10% | GUI §11; limits proposed |
| Training on 50 OK images | ≤ 10 min on CPU, ≤ 2 min on GPU | Proposed |
| Finished inspections lost in a power cut | 0 | Proposed |

- **No freezes (MUST).** Inspection, training, file and database work never run on the UI thread. A window frozen for more than 2 s is a P1 bug, whatever the cause.
- **Measured in CI (MUST).** CI times the synthetic test set on every merge, and a slowdown over 10% fails the build. The reference PC (CPU, RAM, GPU and Windows edition) is written down once and changed only by decision; it is still open in the Charter.
- **Faster inference when needed (SHOULD).** When the 1 s budget is at risk, export models to ONNX and run them with TensorRT on NVIDIA GPUs or OpenVINO on Intel CPUs.
- **Baseline.** v0.1 took about 0.4–0.6 s per 640×480 synthetic image on a CPU-only cloud machine.

## Security and privacy

Customer images and results never leave the station unless an Admin exports them, and every release ships with a reviewed threat model, clean scans and a software bill of materials.

- **Offline and least privilege (MUST).** No network call happens until a feature that needs one (updates, MES, telemetry) is switched on in Settings, which lists every such feature, and nothing listens on a port by default; the installation guide lists every port, protocol and direction. The app runs as a standard Windows user, and only the installer needs admin rights. The service layer checks the role on every write, because hiding a page is not access control.
- **Untrusted inputs (MUST).** Images, recipes and model files from outside are size-limited and type-checked. PyTorch files can run code when loaded, so stations need PyTorch 2.6 or later, load models with `torch.load(weights_only=True)`, and take model files only from our signed packages; storing weights as safetensors removes the risk (SHOULD).
- **Secrets (MUST).** Secret scanning blocks any commit that contains a key, and a leaked secret is revoked within 24 hours, then removed from history. MES tokens and license keys sit in Windows Credential Manager, never in `settings.json` or logs; local passwords, when added, are hashed with Argon2 or bcrypt; CI tokens have least privilege and rotate every 90 days (proposed).
- **Signing (MUST).** Release builds come only from CI on a tagged commit after two people approve, and every installer and executable is signed with a trusted timestamp. The code-signing key lives in a hardware token or cloud signing service, and the license-signing key on an offline machine or hardware module with a backup in a safe. Code-signing certificates issued since 1 March 2026 last at most 460 days, so renewal is booked two months before expiry (proposed).
- **Scans and SBOM (MUST).** Bandit, pip-audit and secret scanning run on every pull request, and a High finding blocks the merge. Each release publishes a CycloneDX SBOM listing every library and model file with its version, and a one-page threat model per product area is reviewed against STRIDE at every minor release.
- **Vulnerabilities and incidents (MUST).** Fixes ship within 14 days for Critical (CVSS 9.0–10.0), 30 days for High (7.0–8.9) and in the next release for Medium (proposed). By general availability, `SECURITY.md` publishes a contact and every report is acknowledged within 2 business days. An incident is contained with its logs kept, affected customers are told within 72 hours of confirming it (proposed), and a review is written within 10 business days. EU reporting duties are in [AOI Standards – Legal & Compliance](legal-and-compliance.md).
- **Customer data (MUST).** Customer datasets are kept per customer, encrypted on our laptops with BitLocker, and returned or deleted when the engagement ends. Telemetry is off by default and anonymous.
- **Customer sites (MUST).** The station works beside Microsoft Defender and common endpoint tools with few, documented exclusions, and under AppLocker or App Control allow-listing. Updates follow the customer's schedule and never force a restart mid-shift, and remote help starts only when the customer opens the session and watches.
- **Hardening extras (SHOULD).** Kiosk mode on operator stations, USB import limited to Engineers and Admins and logged, one-click backup with restore tested every release, an outside penetration test before general availability, and a yearly secure-coding refresher for every developer.

## Testing and release

The main branch is always releasable, and a release ships only when every box in the release gate below is ticked on the reference PC; one open P1 bug stops it.

- **Tests (MUST).** Unit tests for engine functions, a golden-image regression set with expected verdicts and metric tolerances, offscreen screenshots of every page, and the performance budgets above. Line coverage of `aoi/core` and `aoi/data` is at least 80% (SHOULD).
- **CI (MUST once the code is on GitHub).** GitHub Actions runs lint, type checks and every test on Windows and Linux for each pull request.
- **Versions (MUST).** Semantic versioning, 0.x until release 1.0 in 1Q 2027, with model versions and recipe revisions tracked apart from the app version. A release ships every 4 weeks during the PoC stages, with hotfixes as needed (SHOULD).
- **Build (MUST).** PyInstaller one-folder packaging inside a Windows installer (Inno Setup or MSIX), code-signed, with a GPU option that bundles the CUDA runtime. A build moves from a developer machine to the reference test station, then a pilot customer's station, then general release.
- **Upgrade and rollback (MUST).** Upgrades keep the workspace, back up the database before migrating, and roll back in one step.
- **Docs as code (MUST).** Manuals, the installation guide and release notes are Markdown files in the repository's `docs/` folder, change in the same pull request as the feature, and ship with the release they describe.
- **Release notes (MUST).** One template, published in Korean and English together, with a requirement or bug ID on every item. The first section, "Changes that can alter verdicts", is never skipped and says "None" when empty; New, Improved, Fixed, Security, Known issues and Upgrade notes follow.
- **Release 1.0 polish (MUST).** An installer and uninstaller with no console window; a first-run wizard for language, workspace, Admin account and first board model; an About dialog with versions, license, station ID and third-party notices; a published error-code catalogue; documented CSV, PNG and PDF exports; and one product name with one set of terms everywhere.

Release gate:

- [ ] All CI checks green: lint, type checks, unit tests, golden-image regression and page screenshots
- [ ] Performance budgets hold on the reference PC
- [ ] 8-hour soak run with no crash, slowdown ≤ 10% and memory growth ≤ 10%
- [ ] Upgrade tested on a copy of real customer data, and rollback tested
- [ ] Security: threat model reviewed, scans clean or each finding accepted in writing, SBOM stored, every executable signed and timestamped, models load as weights only, the default install opens no port, and every open vulnerability is inside its fix deadline
- [ ] The current stage's demo scripts pass on the release build
- [ ] English and Korean screenshots of every page reviewed
- [ ] Release notes complete with known issues, and no open P1 bugs

## Workflow

Every requirement has an ID, a source and a test, and short-lived branches with small pull requests keep the main branch releasable every day.

- **Requirements (MUST).** IDs are `REQ-<AREA>-<NNN>` and never reused. Each has a one-sentence "shall" statement, a source (spec section, roadmap item, customer request or field issue), testable acceptance criteria with numbers and units, a MUST, SHOULD or MAY priority for a named release, and a stage. Area codes, shared with the error codes: INSP inspection, CMP compare, TRN training, TST AI model test, RCP recipe, LOG logs and export, P3D 3D profile, USR users and roles, SET settings, CAM cameras and lighting, ROB robot, MES MES and ERP.
- **Ready before work (MUST).** Work starts only when the ID, source, acceptance criteria and priority are filled in, a screen change has a sketch, and the data, schema, model, license, demo and documentation impacts are noted or marked "none".
- **Traceability (MUST).** CI builds the trace matrix on every merge from the IDs in pull request titles and test names, and publishes it with each release. A requirement with no test, or code with no requirement or bug ID, fails the release gate. The first IDs come from the v0.1 map of GUI spec sections to pages (SHOULD).
- **Branches (MUST).** Trunk-based: work branches live 3 days at most (proposed) and are named like `feat/REQ-CMP-004-short-name`, `fix/…` or `chore/…`, and release branches such as `release/1.2` exist only for maintained versions. Unfinished work merges behind a feature flag that is off in release builds, and commits follow Conventional Commits (SHOULD).
- **Pull requests (MUST).** At most 400 changed lines (proposed), not counting generated files, with the REQ or bug ID in the title and a description of what changed, how it was tested, UI screenshots, and migration and demo impact. Every change needs one approval, and whoever built a release, model or threshold change is never its only approver; until a second engineer joins, Jay signs off.
- **Design records (MUST for big changes).** A one-page record in `docs/adr/` (context, decision, consequences) for any change to the service API, the data schema or the model architecture, a new dependency, or anything hard to undo. `CONTRIBUTING.md` takes a new developer from a clean Windows PC to a passing test run in one day (SHOULD).
- **Planning (MUST).** GitHub Issues once the code moves there, labelled by type, area code, priority (P1–P3) and customer. One ordered backlog: P1 field issues and missed-defect risks first, then contract commitments, the next stage gate, demo and pilot blockers, and the rest by value. Each 4-week release train keeps 20% for quality and debt (proposed), and anything added mid-train pushes out a named item.
- **Change control (MUST).** A change that can alter a verdict (a new model version, a threshold or algorithm change, a check added or removed) is announced to customers in writing at least 30 days ahead (proposed), with before and after results on their validation set, and they re-validate before it goes live on their line. Every other change goes in the release notes, and the regression set proves no verdict changed. A security fix that changes no verdict may ship on shorter notice, with the reason stated (MAY).

## Known v0.1 gaps

v0.1 was checked against this standard on 1 October 2026. These are the first fixes, in this order, and each one closes with a test.

- [ ] **Model loading, a security fix.** `aoi/core/anomaly.py` loads models with `torch.load(weights_only=False)`, and `requirements.txt` allows `torch>=2.2`. Require PyTorch 2.6 or later, store the NumPy arrays in the checkpoint metadata as tensors or plain lists, and load weights only.
- [ ] **Data layer.** `aoi/data/db.py` stores local time without an offset, absolute image and model paths, and integer IDs only; it creates tables without migrations and does not run in WAL mode.
- [ ] **Screens.** Tables, headers and muted labels use 12 pt in `aoi/ui/theme.py` and `model_test.py`; pages such as `main_window.py` hard-code colours; and no visible string goes through `self.tr()` yet.
- [ ] **Logs and errors.** No JSON-lines log, no audit trail beyond recipe revisions, and no `AOI-<AREA>-<NNN>` codes.
- [ ] **Tooling.** No `ruff` or `mypy` configuration, lock file or CI, and one end-to-end test.
- [ ] **Batch results (SHOULD).** Results appear only at the end of a run, not board by board.

## Sources

The outside facts in this standard were checked against these pages on 1 October 2026; numbers marked GUI § come from the GUI specification.

- [PyTorch 2.6.0 release notes](https://github.com/pytorch/pytorch/releases/tag/v2.6.0), on the weights-only default and CVE-2025-32434
- [Code Signing Baseline Requirements](https://cabforum.org/working-groups/code-signing/requirements/), CA/Browser Forum
