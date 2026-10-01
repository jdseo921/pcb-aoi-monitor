# Threat model (build 0.2.0)

One page per product area, reviewed against STRIDE at every minor release (Engineering standard, "Scans and SBOM",
MUST). This draft was written for the internal build 0.2.0 (stage S22c) from the code as it stands; it names what is
in place with the file that does it, what is a gap with the stage or issue that closes it, and what needs Jay's
decision. Jay's merge of this file is the review of record for 0.2.0; the next review is due with 0.3.0, the build
for Stage 1 testing. **Status vocabulary:** *In place* (with the file or test), *Gap* (with the plan), *Decision*
(Jay chooses), *n/a* (with the reason).

## The system in one paragraph

A Windows PC on the line runs the app as a standard user. Everything lives in one workspace folder
(`~/AOI_Workspace` by default; `docs/ARCHITECTURE.md`, "Workspace on disk"): the SQLite database, the JSON-lines log,
sample and inspection images, trained models (`.pt` plus a golden PNG) and exports; `settings.json` sits in the default
workspace folder (`~/AOI_Workspace`, or `$AOI_WORKSPACE`) even when it points the app at another workspace. Images come
from a folder (a camera in Stage 2), results stay on the station, and nothing talks to a network: `aoi/` imports no
HTTP, socket or subprocess module, and no setting enables such a feature yet ("Offline and least privilege", MUST).
Operators inspect; Engineers import, train, tune and export; Admins manage users. Every Engineer and Admin write
goes through `AppContext` (`aoi/core/services.py`), which checks the role with `@requires` and appends an audit
entry; an Operator's inspection record, an alarm and the start-up retention sweep are written without a role check
or an audit entry, by design (`tests/test_roles_and_audit.py` lists them); screens never reach the database or build
an engine (`tests/test_layers.py`). **Trust boundaries:** (1) the person at the keyboard and the role they hold;
(2) files brought in from outside: images and folders on USB or a share, and a model file dropped into `models/`
(there is no recipe or model import feature yet); (3) files going out: exports, model deliverables; (4) the
workspace folder on disk, which the OS protects and the app does not defend against a Windows administrator
(proposed in ADR 0002, decision 6; PR #14 is open); (5) the build and install chain.

---

## Page 1: Inspection

**What it does.** The Operator picks images (a folder today, a camera in Stage 2), the engine aligns each board to
the golden template, scores it, decides OK / WARN / NG with the recipe's thresholds, saves the overlay and the
result, raises an alarm on NG or on an error, and Compare shows the test board beside the golden one.
**Assets:** verdicts and their evidence (inspection rows, overlays), the station's availability during a shift,
customer board images. **Entry points:** image files, the recipe and active model (page 2 and 3), the Operator view.

| STRIDE | Threat | Status |
|---|---|---|
| Spoofing | A result is recorded under another Operator's name: anyone picks any user from the list, with no password | **Gap.** Proposed in ADR 0002 (`docs/adr/0002-local-sign-in.md`, PR #14, open; the sign-in stages follow in the plan): Operators pick a name, a station setting adds a 4–6 digit PIN, Engineers and Admins sign in with Argon2id-hashed passwords. Until it lands, the operator name on a result is a label, not an identity |
| Tampering | A verdict or overlay is edited after the fact in the database or on disk | **In place for the app:** the audit table refuses UPDATE and DELETE by trigger (`aoi/data/migrations/0003_audit.sql`, REQ-LOG-004). **Gap for the app:** no trigger protects `inspections` or `defects`; the start-up retention sweep updates the archived flag of old rows (`archive_old`), and `defects` rows go with their inspection (`ON DELETE CASCADE`), so only code discipline keeps a verdict row from being changed. **Gap for the disk:** a Windows user with access to the workspace can edit `aoi.sqlite` directly; the installer (page 4) should give the workspace an ACL that only the app's account writes. **Decision 4:** a trigger that refuses UPDATE of result, score and overlay_path and any DELETE on `inspections` (the archived flag stays writable), a hash chain over the rows for customer evidence, or both |
| Repudiation | "I never inspected that board" | **In place:** every inspection row carries time (UTC), operator, model version and recipe revision; alarms and errors are stored with codes (REQ-INSP-006, REQ-LOG-005). The inspection row itself is the record: it is not audited, and nothing but code discipline protects it (Tampering above). Weak until spoofing above is closed |
| Information disclosure | Customer board images leave the station | **In place:** images stay in the workspace; no image reaches the log and keys that look like secrets are dropped, while exception text and traces are logged verbatim (`aoi/logging_setup.py`, `SECRET_KEYS`); exports need the Engineer role and write an audit entry with the destination and counts (`export_overlays`, `export_csv`). **Gap:** USB import and export are not limited or logged as such ("Hardening extras", SHOULD). **Decision 8:** the Engineering standard's Security intro says images leave the station only when an Admin exports them, while the code makes exports an Engineer write; either the role or the standard changes |
| Denial of service | A huge or malformed image stalls or crashes the station mid-shift | **In place:** decoding failures raise `AOI-INSP-001` and the app keeps running; inspection runs on the pool thread, so the window stays responsive (`tests/test_no_freeze.py`). **Gap:** the Inspection page has no busy indicator or Cancel (Stop acts between boards only; REQ-SET-021 covers it), and no size or pixel cap before `cv2.imdecode` (`aoi/core/imaging.py`), while the standard asks that images from outside be size-limited ("Untrusted inputs", MUST). **Decision 1:** the caps, proposed 64 MB per file and 50 MP per image, refused with an AOI-INSP code |
| Elevation of privilege | An Operator changes a threshold or activates a model from the Operator view | **In place:** `@requires("Engineer", …)` on every write in `aoi/core/services.py`; hidden pages are a convenience only (REQ-USR-001, `tests/test_roles_and_audit.py`). Reads and inspections need no role by design: an Operator inspects boards |

---

## Page 2: Training and datasets

**What it does.** An Engineer imports OK and NG boards (files or a folder with `ok/` and `ng/`), labels and
reviews them, sets the reference board, trains a model version, tests it on a labelled folder and activates it;
recipes hold the regions and thresholds. **Assets:** the dataset's labels (a wrong label trains a model that misses
defects), model versions and which one is active, the recipe, test results used as evidence. **Entry points:**
imported files and folders, the Training, AI Model Test and Recipe Editor pages.

| STRIDE | Threat | Status |
|---|---|---|
| Spoofing | A dataset change or model activation is made under another Engineer's name | **Gap**, as page 1: the passwords for Engineers and Admins proposed in ADR 0002 |
| Tampering (poisoning) | NG boards slipped into the OK folder, or labels flipped, so the next model learns the defect as normal | **In place:** import, relabel, remove, set reference and activation need the Engineer role and are audited with counts and the object (`sample.import`, `board_model.reference`, …); the dataset table shows every label; a model version's file, path and metrics never change once written; only its active flag does, audited. **Gap:** no model card and no go-live gate yet (Engineering, "AI models"; plan stages S30s); a new active model is a verdict-changing change and needs the customer's re-validation ("Change control", MUST) |
| Repudiation | "That model was not trained on those images" | **In place:** `models` rows carry board model, version, path and metrics JSON; training writes an audit entry; `test_runs` keep folder, metrics and per-image results. **Gap:** the row records neither the dataset's content hash (see page 3) nor the seed, code commit, settings and dataset version the Lineage rule (MUST) wants in the `.pt` |
| Information disclosure | The dataset and the golden template are the customer's boards | **In place:** they stay in the workspace; `Export AI Model` is an Engineer write with an audit entry (`export.model`, destination). **Decision 7:** whether a model deliverable may leave the site without the customer's written note (Legal, customer data) |
| Denial of service | A folder with thousands of images, or one giant image, ties up the station | **In place:** import runs on the pool with progress, time left and Cancel, and a stall over 2 s fails a test (`tests/test_no_freeze.py`); training runs on the pool with a progress bar and the epoch log and honours Stop (REQ-SET-021), with no stall test yet. **Gap:** the same size and pixel caps as page 1, plus a cap on images per import (proposed 10,000) |
| Elevation of privilege | An Operator imports samples, changes a recipe or activates a model | **In place:** role checks in the service layer, as page 1; the Recipe Editor and Training pages are hidden from Operators as a convenience |

---

## Page 3: Files and models

**What it does.** Stores everything under the workspace: `aoi.sqlite`, `settings.json`, `logs/`, `images/`,
`models/<board>/<board>_<version>.pt` with its `_golden.png`, `exports/`. Paths are stored relative to the workspace and
resolved by `aoi/data/paths.py`; every file but the append-only log is written through `aoi/data/atomic.py`; the schema changes only by
numbered migration. **Assets:** the integrity of model files (they decide verdicts), the database, the log as
evidence, the customer's images. **Entry points:** the files themselves, model files from outside, the
`AOI_WORKSPACE` environment variable and `settings.json`.

| STRIDE | Threat | Status |
|---|---|---|
| Spoofing | A different `.pt` is dropped in place of the active model, so the station scores with a model nobody approved | **Gap.** Loading refuses code (next row) but not a swapped file. **Decision 2 (proposed):** store the SHA-256 of the model file and golden image in the `models` row at training and check it at load, refusing a mismatch with a new AOI-TRN code (`AOI-TRN-001` means a file that needs code to load); the same hash in the SBOM and the model card |
| Tampering | A model file that runs code when loaded (PyTorch files are pickles) | **In place:** `torch.load(path, weights_only=True)` on PyTorch ≥ 2.6, metadata stored as tensors and plain values only, and a file that needs code is refused with `AOI-TRN-001` (`aoi/core/anomaly.py`, REQ-TRN-014); a text scan fails the build on `weights_only=False` anywhere in `aoi/`, `tools/` or `main.py` (`tests/test_security_rules.py`); `pickle` is imported there only for its exception type. Safetensors would remove the class of risk (SHOULD; not planned for Stage 1) |
| Tampering | `settings.json` or a recipe is edited on disk | **In place:** recipes live in the database with a revision and an audit entry on save (`save_recipe`); `settings.json` holds the workspace path, device, image size, training epochs, retention, language and last page, no secret and nothing that changes the current verdict directly. **Gap:** the file lives in the default workspace folder (`~/AOI_Workspace` or `$AOI_WORKSPACE`, `aoi/config.py`), which the standard user writes; its workspace pointer selects which database, users, active model and recipes are live, and image size and epochs feed the next training run, so it is an indirect lever, and the installer's ACL plan (page 4) must cover it |
| Repudiation | Who changed a record, and what it was before | **In place:** `audit` rows with user UUID, role, action, before and after JSON and reason, append-only by trigger; the JSON log carries ids and the app version (REQ-LOG-004) |
| Information disclosure | Secrets or images in logs or settings | **In place:** the log drops keys named password, token, secret and the like and never writes an image (`aoi/logging_setup.py`); there are no secrets in the app today. **Plan (Stage 4):** MES tokens and license keys in Windows Credential Manager, never in `settings.json` ("Secrets", MUST). **Gap (low, #113):** `export_csv` quotes fields but does not neutralise a cell that starts with `=`, `+`, `-` or `@`, which a spreadsheet may run as a formula; user-entered text (a reason, a name) can reach a CSV. **Plan:** prefix such cells with `'` in `aoi/core/services.py` (#113, a fix PR before 0.3.0) |
| Denial of service | A crash or power cut mid-write corrupts the database or a model | **In place:** temp file, fsync, `os.replace` for every file but the append-only log; SQLite in WAL mode with full sync; 20 process kills in `tests/test_power_cut.py` lost nothing (REQ-INSP-008, ADR 0004). **Gap:** a process kill is not a power cut (the OS still flushes what the process handed it); the pulled-power test on the reference PC is S55. Inspection records older than the retention are archived at start-up (`archive_old`) |
| Denial of service | The disk fills: an overlay PNG for every inspected board, a log file per day and an alarms table that are never deleted | **Gap.** The Disk and retention rule (MUST) wants an alarm at 80 % disk use, no OK images saved past 95 % and logs archived after 30 days; today nothing checks free space, `log_retention_days` archives inspection rows and not log files, an overlay is written for every board and `ALARM_LIMIT` caps only what is read. **Plan:** REQ-LOG-006 (the disk alarm) is a 1.0 row of the register, written into the Stage 2 to 1.0 plan; REQ-LOG-003 (archiving, Stage 1) covers records, and log-file archiving goes into that stage |
| Elevation of privilege | A stored path points outside the workspace (`..`) and a read or write lands elsewhere | **Gap (low, #112).** `to_stored` in `aoi/data/paths.py` stores a path inside the workspace relative to it and a path outside (a folder the user chose) as given, and `resolve` joins any stored relative path onto the root without checking that the result stays inside it, so a row edited on disk (`../..`) could point the app at a file elsewhere. **Plan:** refuse an escaping path in `resolve` with an AOI code and add a test (#112, a fix PR before 0.3.0). SQL values are always bound parameters in `aoi/data/db.py`; the one interpolation (`audit_entries`) inserts a column name from a fixed list, so injection does not apply |

---

## Page 4: Installer and build

**What it does.** Nothing yet: 0.2.0 runs from source (`docs/ARCHITECTURE.md`, "Known limits"). The plan is a
PyInstaller single-folder build wrapped in a signed Windows installer, installed with admin rights, run as a
standard user, with no port open and no network feature on. **Assets:** the integrity of what customers run, the
build chain's credentials, the station's Windows configuration. **Entry points:** the dependency set, the CI
pipeline, the installer package, the update path.

| STRIDE | Threat | Status |
|---|---|---|
| Spoofing | A customer installs a package that is not ours | **Gap.** "Signing" (MUST): every installer and executable signed with a trusted timestamp, from CI on a tagged commit after two approvals; the key in a hardware token or cloud signing service. **Action for Jay:** order the code-signing certificate (plan item J6) and check its validity period against the release calendar |
| Tampering (supply chain) | A dependency is replaced or a release is built from an unreviewed commit | **In place:** exact pins in `requirements.lock` and `requirements-dev.lock`, a license gate, and Bandit, `pip-audit` and gitleaks (secrets in any commit) on every pull request in CI (`.github/workflows/ci.yml`, since #7 and S04); a High finding blocks the merge. The lock files pin exact versions but carry no hashes, so pip does not verify what it downloads (**plan:** `--require-hashes` lock files when the release stage sets up the build). **Gap:** no CycloneDX SBOM yet ("Scans and SBOM", MUST; plan: the release stage) and no two-person release approval, which G1 cannot meet with one developer (plan item J8, written exception) |
| Repudiation | Which build a station runs | **In place:** `APP_VERSION` in `aoi/config.py` is shown in the window title and the Settings subtitle and written into every log line (`aoi/logging_setup.py`). **Gap:** no release has been tagged yet (v0.1 was not; `v0.2.0` is the first, after Jay merges S22c), the error dialog carries no version, and the build hash is not shown in the app |
| Information disclosure | The installer or the build logs leak a key | **In place:** secret scanning in CI; no secret in the repository. **Plan:** the signing key never enters CI as a file; a cloud signing service or hardware token signs |
| Denial of service | An update restarts a station mid-shift, or Defender blocks the app | **Gap, plan:** updates follow the customer's schedule and never force a restart mid-shift; the station runs beside Defender and under AppLocker or App Control with few, documented exclusions ("Customer sites", MUST); the installation guide lists every port, protocol and direction, which today is none |
| Elevation of privilege | The app runs with admin rights, or the installer leaves the workspace writable by everyone | **Gap, decision 3:** only the installer needs admin rights; the app runs as a standard user ("Offline and least privilege", MUST); the installer sets the workspace ACL so only the app's account writes it and `settings.json` (closes the disk-tampering gap on pages 1 and 3). Kiosk mode on Operator stations (SHOULD) |

---

## Decisions for Jay

1. Import caps: 64 MB per file, 50 MP per image, 10,000 images per import, each refused with an AOI code (pages 1 and 2).
2. Model file integrity: SHA-256 of the model and golden image recorded at training and checked at load (page 3).
3. Workspace and `settings.json` ACL and kiosk mode in the installer (pages 1, 3 and 4).
4. Verdict rows: a trigger that refuses changes to `inspections`, a hash chain over the rows for customer evidence, or both
   (page 1).
5. Written exception for two-person release approval until a second approver exists (page 4, J8).
6. Order the code-signing certificate (page 4, J6).
7. Whether a model deliverable may leave the site without the customer's written note (page 2).
8. Exports: the standard says an Admin exports customer images, the code lets an Engineer; change the role or the
   standard (page 1).

## Review log

| Date | Build | Reviewer | Result |
|---|---|---|---|
| 2026-10-01 | 0.2.0 (internal) | Claude Code, for Jay | Draft; gaps named with their plan on every page, 8 decisions open, 2 low gaps found while writing (`paths.resolve`, #112; CSV formula cells, #113). Corrected after an independent review of the draft: inspection rows are neither audited nor trigger-protected, the Inspection page has no Cancel, the power-cut evidence is a process-kill test, disk exhaustion was missing |
