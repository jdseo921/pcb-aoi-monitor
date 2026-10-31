# Production plan: from a well-tested Stage 1 tool to a system one person can run and hand over

**Owner:** Jay, working alone, with Claude Code as the implementer. **Baseline:** `b5bf413` (2026-10-14). **Source:** the production-readiness review of 2026-11-01 (Claude Docs, "AOI PoC Inspector: Production-Readiness Review"). **Spec of record:** `docs/requirements/stage1.md`, 101 rows. **Governing documents:** `CLAUDE.md` and the four AOI Standards, which Stage 0 copies into `docs/standards/`.

Commit this file as `docs/plans/2026-11-production-plan.md` in the first PR of Stage 0, and keep `docs/plans/2026-11-production-progress.md` beside it, one line per PR. Every Claude Code session starts by reading both.

---

## 1. How one person runs this

The review's conclusion was: refactor in place, do not restart; the constraint from here is review time, not typing. These rules follow from that.

| Rule | Why |
|---|---|
| **One pull-request train per working day, at most.** Each PR ≤ 400 changed lines excluding generated files (`aoi_ko.ts`, `docs/error-codes.md`, screenshots) and one concern. | You must be able to read every PR in under 30 minutes. 879 commits in 14 days is what made the codebase un-reviewable. |
| **Feature freeze until Stage 3 is tagged.** No new register row of kind "feature"; only rows this plan names. | Every feature added widens what Stages 2 and 3 must carry. The last three weeks added five unplanned features. |
| **Every stage ends on a tag** (`v0.4.0`, `v0.4.1`, `v0.5.0`, …) with all CI green, the register's status column updated, the release note cut, the release-gate record written honestly. | A solo maintainer needs known-good points to roll back to. |
| **Fresh-eyes review is a subagent, not you.** Claude Code spawns a reviewer that has not seen the diff for every PR, against the CLAUDE.md checklist; you read the diff and the review, and merge. | The Charter's "a person approves" stands; the second engineer the Charter assumed is replaced by an agent that cannot be anchored on its own work. |
| **The regression set stays byte-identical through Stages 0 to 3.** `tests/regression/expected.json` unchanged; any PR that would alter it stops and asks. | Nothing in these stages is meant to change a verdict. |
| **Plan of record lives in the repo.** This file, the progress file, the Standards. Chat is for instructions, not for the record. | The previous brief was never committed; the work landed anyway, the acceptance lines did not. |
| **Decisions are written before code.** The decisions in section 3 go into ADR 0024 in Stage 0; a new MUST conflict later becomes a numbered decision in the same ADR before the PR that needs it. | The register and the trace gate will refuse otherwise, correctly. |

## 2. The stages at a glance

| Stage | Name | Outcome | Tag | Effort (engineer-days of review + typing) |
|---|---|---|---|---|
| 0 | Repository of record | Plan, standards, decisions and version discipline are in the repo; the freeze is declared | none | 2 to 3 |
| 1 | Safe to run | A station runs unattended for a month without filling its disk, losing its identity or failing silently; a support engineer gets a bundle in one click | `v0.4.0` | 10 to 12 |
| 2 | Human-sized | A newcomer lands a one-line change the same day; CI answers in about 12 minutes; the rules are tooling, not ceremony | `v0.4.1` | 12 to 15 |
| 3 | Service boundary, in process | The engine has a typed API and a cycle object a camera could drive; the service splits into parts one person can hold; upgrade and rollback are one step | `v0.5.0` | 18 to 25 |
| 4 | Engine out of process | A native crash or a camera hang cannot take the screen down; a cycle runs with no screen | `v0.6.0` | 15 to 20, **only when Stage 2 hardware is scheduled** |
| 5 | Fleet | 50 stations configured, updated, inventoried and observed from one place | separate product | scope in 2027 |

Stages 0 to 3 total 42 to 55 engineer-days. At four focused hours a day of your review time, plan on roughly three to four calendar months; Claude Code's typing is not the bound.

## 3. Decisions to take before Stage 1 (they go into ADR 0024 in Stage 0)

| # | Decision | Recommended default | What it unblocks |
|---|---|---|---|
| D1 | **Evidence policy.** What is kept per inspected board | NG and WARN: the full-resolution overlay and both maps, forever. OK: a JPEG overlay at quality 90 plus a 640 px preview; maps for 7 days as today. A customer may name a different policy in their profile later | Stage 1, PR 1.2. Decides whether the disk problem is a week of work or a purchase order |
| D2 | **Feature freeze** until `v0.5.0` | Yes | Everything |
| D3 | **Sign-in with passwords** (REQ-USR-002 to -005) | Build in Stage 3 if a second customer or any paid deployment is in sight before `v0.6.0`; otherwise defer to Stage 4 | Stage 3, PR 3.9 |
| D4 | **What the dataset-store encryption is for** | Keep it as the vendor-laptop control; state in ADR 0010 that BitLocker is the station's disk control and `results/` is not encrypted by the app | Closes a threat-model gap honestly instead of extending a control that already fails on key loss |
| D5 | **IPC wording** for Stage 4 | Amend REQ-SET-003 to "listens on no TCP or UDP port; a local named pipe between the app's own processes is allowed" | Stage 4 |
| D6 | **Trace gate scope** | Pull-request title must cite a requirement or issue; individual commits need not | Stage 2, PR 2.5 |
| D7 | **Korean** | Translate the demo path once Stage 3 is tagged and the string set has stopped moving; nothing before | Stage 3, PR 3.10 |
| D8 | **Reference PC** | Buy or borrow the ADR 0011 configuration before `v0.4.0` is tagged; the station checks are its exit criterion | Stage 1 exit |

## 4. Register changes this plan needs

The trace gate requires every PR to cite a register row or an issue. Architecture work cites an issue; behaviour work cites a row. Add these rows in Stage 0 (IDs continue the existing sequences; acceptance criteria are proposals for Jay to approve in the same PR):

| New row | The app shall… | Acceptance (proposed) | Priority |
|---|---|---|---|
| REQ-SET-023 | carry a version that changes with every shipped change | `APP_VERSION` differs from the last tag whenever `aoi/data/migrations/` gained a file or the register's status column changed; CI fails otherwise; the exe carries a VERSIONINFO resource; a signed build is named without "unsigned" | MUST G1 |
| REQ-SET-024 | write a heartbeat and run a self-check at start | `heartbeat.json` rewritten atomically every 60 s with pid, uptime, last inspection time, boards and NG in the last hour, mean and p95 verdict time, free bytes; at start `PRAGMA quick_check`, store keys present, orphan counts, free space, each failure an alarm with a code; `app.close` logged on every clean exit | MUST G1 |
| REQ-LOG-010 | keep storage within the evidence policy by retention that runs while the app is open | OK maps, log files (90 days, gzip after 7), migration backups (last 3), test-run overlays and orphan files are swept on a timer and at start; each sweep audited with counts | MUST G1 |
| REQ-SET-025 | refuse a workspace that cannot hold a live SQLite database safely | A remote drive or a folder under a OneDrive root is refused with a code and a plain reason at pick time and at start | MUST G1 |
| REQ-SET-026 | write a crash record when it dies | `faulthandler` to `logs/`; the installer documents the WER LocalDumps key; the next start logs that the last run did not close cleanly | MUST G1 |
| REQ-SET-027 | ship a release kit a station can verify offline | signed installer, `SHA256SUMS.txt`, provenance bundle, `pilot-ca.cer`, release note, `verify.ps1` (signature and hashes), `inventory.ps1` (installed version from the registry) | MUST G1 |

Change these existing rows: REQ-LOG-006 and REQ-LOG-007 move from MUST 1.0 to MUST G1 (Stage 1 builds them). REQ-SET-011 (About) moves to MUST G1. REQ-SET-013 is marked done by REQ-TRN-021's guide, or its acceptance is reworded to match what was built; today the register says "No" while the guide exists. REQ-SET-003 is amended per D5 when Stage 4 starts, not before.

Open one GitHub issue per architecture item in Stage 3 (cycle extraction, service split, typed results, worker absorption, HAL inversion) so each PR has an ID to cite.

---

## Stage 0: Repository of record (2 to 3 days, no tag)

Entry: now. Exit: `main` holds this plan, the Standards, ADR 0024, the register rows above, and a CI rule for version discipline; the freeze is declared in `README.md` and `CLAUDE.md`.

| PR | Scope | Files | Done when |
|---|---|---|---|
| 0.1 | This plan and an empty progress file | `docs/plans/2026-11-production-plan.md`, `…-progress.md` | Both on `main` |
| 0.2 | The four Standards exported to Markdown, `CLAUDE.md` re-pointed to them, the artifact links kept as "source" | `docs/standards/charter.md`, `engineering.md`, `customers-and-launch.md`, `legal-and-compliance.md`, `CLAUDE.md` | Every ADR and register citation of a Standard resolves to a file in the repo |
| 0.3 | ADR 0024 with decisions D1 to D8; the new register rows and the priority moves of section 4; the status fix for REQ-SET-013 | `docs/adr/0024-production-plan-decisions.md`, `docs/requirements/stage1.md` | `python tools/trace_matrix.py` passes |
| 0.4 | Version discipline (REQ-SET-023): `APP_VERSION` to `0.4.0.dev`, a CI job that fails when a migration lands without a bump, a build number from CI in `BUILD-INFO.txt` and the About line, a VERSIONINFO resource in `installer/aoi.spec`, signed builds named without "unsigned" and the installer's welcome text for a signed build | `aoi/config.py`, `.github/workflows/ci.yml`, `build.yml`, `installer/aoi.spec`, `aoi.iss`, `tests/test_windows_build.py` | A PR that adds `0028_x.sql` without a bump goes red |
| 0.5 | The freeze and the solo rules: section 1 of this plan summarised in `CLAUDE.md` under "Working rules until v0.5.0"; the PR template carrying the checklist so commits do not | `CLAUDE.md`, `.github/pull_request_template.md` | Visible on the next PR |

## Stage 1: Safe to run (10 to 12 days, tag `v0.4.0`)

Entry: Stage 0 merged, D1 and D8 decided. Exit: a synthetic station at one board per 10 s runs 72 hours in CI's nightly (`tools/soak.py`) with disk held under the policy, the heartbeat present every minute, no silent failure; the support bundle opens in one click; `v0.4.0` built from the tag, pilot-signed, verified by `verify.ps1` on a clean Windows VM; the station checks of `docs/tests/station-checks.md` run on the reference PC (D8) and recorded.

| PR | Scope | Row | Done when |
|---|---|---|---|
| 1.1 | **Disk guard.** Free space measured at start and before each save; alarm at 80 %; at 95 % the record and NG evidence are saved and OK overlays and maps are skipped with a note in the record; a status-bar indicator; the next-start `archive_old` can no longer refuse the workspace on `SQLITE_FULL` (it degrades to an alarm) | REQ-LOG-006 | Tests fill a tmpfs to each threshold; the 95 % path saves an NG with evidence and an OK without |
| 1.2 | **Evidence policy (D1).** Overlay writer honours the policy; `PREVIEW_PX` used for the OK preview; Compare, Logs and exports read whichever exists; CSV gains an `evidence` column naming what was kept | REQ-INSP-012, ADR 0024 D1 | Regression set unchanged; a 5 MP OK board costs under 1 MB on disk |
| 1.3 | **Retention on a timer.** One `Retention` service in `aoi/core`, run by a timer the context owns (not Qt), at start and every hour: OK maps, logs, `.bak` (keep 3), test-run overlays, orphan files whose row is gone; audited counts | REQ-LOG-010 | A 30-day synthetic workspace shrinks to the policy after one tick; the audit shows what went |
| 1.4 | **Heartbeat, self-check, clean exit** | REQ-SET-024 | `heartbeat.json` every 60 s under test; `app.close` in the log; a start after a kill logs "did not close cleanly" |
| 1.5 | **Crash record** | REQ-SET-026 | A forced access violation in a test subprocess leaves a `faulthandler` file in `logs/` |
| 1.6 | **Support bundle and About** | REQ-LOG-007, REQ-SET-011 | One click produces a zip with the last 7 days of logs, `settings.json` scrubbed, `schema_version`, versions, the heartbeat history, alarms and audit as CSV, free disk, torch/CUDA/OS facts; no image unless ticked; nothing REQ-USR-007 forbids; About shows app, build, commit, AI model and recipe versions, schema, third-party notices |
| 1.7 | **Workspace guards** | REQ-SET-025 | Remote drive and OneDrive root refused at pick and at start with a plain reason |
| 1.8 | **Signing hygiene and installer wording.** Secrets scoped to the two signing steps; CA key backup procedure and expiry date in `docs/install/pilot-signing.md`; signed builds say "Pilot build, signed with the <company> pilot certificate" | REQ-SET-012, ADR 0011 | `build.yml` shows the PFX only in the signing steps; a signed installer's welcome page has no "unsigned" |
| 1.9 | **Release kit and runbook** | REQ-SET-027 | `docs/release/runbook.md` is an ordered checklist from bump to kit; `verify.ps1` and `inventory.ps1` run on a clean VM; CI assembles the kit as an artifact |
| 1.10 | **Release 0.4.0.** `unreleased.md` to `0.4.0.md` split into `0.4.0.md` and `0.4.0.ko.md` (draft), `docs/release-gate/0.4.0.md`, threat model review log, register status column, tag | — | Gate record honest; station checks recorded or named as the open box with D8 |

What Stage 1 does **not** do: touch `services.py`'s structure, the tests' layout, or any verdict.

## Stage 2: Human-sized (12 to 15 days, tag `v0.4.1`, no behaviour change)

Entry: `v0.4.0` tagged. Exit: a pull-request CI run finishes in about 12 minutes per OS; screenshots approve from CI; `make test-fast` runs the unit and service layers in under 5 minutes locally; `tests/README.md`, `CONTRIBUTING.md` and a repository map exist; a reviewer agent given only those three documents lands a one-line label change with green CI in one session.

| PR | Scope | Done when |
|---|---|---|
| 2.1 | **Test layout.** `tests/unit`, `service`, `ui`, `policy`, `tools`, `slow`; markers; `pytest -m` targets; `tests/support/` holding `_window`, `station`, `click`, `records`, the word lists, the helpers today imported from 46 test modules | No test module imports another test module; `pytest tests/unit tests/service` under 5 minutes |
| 2.2 | **Lint extraction.** The six AST scanners (i18n literals, colour literals, 14 pt, attribute shadowing, `torch.load`, Charter words) and the regenerate-and-compare checks (`aoi_ko.ts`, `docs/error-codes.md`) become `tools/lint_*.py` under `pre-commit` and a two-minute CI job; their self-tests and the tests that parse `build.yml` and `aoi.iss` are deleted | About 160 fewer tests, 2,500 fewer lines; the same rules enforced |
| 2.3 | **CI speed.** `actions/cache` for the synthetic dataset, tiny model, demo bundle and screen workspace keyed on their generators' hashes; `xdist` for `tests/ui`; the screens fixture session-scoped; timing budgets written to a `perf.json` artifact and judged only on a nightly self-hosted or reference runner; the base-versus-head perf job made a required check; a nightly workflow for `slow`, screens, the 72-second soak and the three review renders | Pull-request suite ≤ 12 minutes per OS over five runs |
| 2.4 | **Screenshots.** `approved/` moved to Git LFS; one shot per page per theme (role variants covered by the size walk); a `workflow_dispatch` job that renders on Linux and commits the approved set to the PR branch, so approval never needs a local Linux machine | 65 PNGs become about 30; history stops growing by megabytes per commit |
| 2.5 | **Trace gate on the PR title (D6)**; the change-note checklist lives in the PR template only | A typo-fix commit without an ID no longer fails the run |
| 2.6 | **Docs for the next person.** `Makefile` (`i18n`, `errors`, `screens`, `regress`, `lock`, `test-fast`, `test-all`, `bundle`); `tests/README.md` (the layers, the 11 autouse fixtures and why, which fixture to pick); `CONTRIBUTING.md` (set-up, the one-line-change walkthrough, the rules that bite); `docs/MAP.md` (modules, the eight services-to-be, thread rules, the S/Q/B/D ID glossary with a note that they are historical); `docs/ARCHITECTURE.md` restructured: title no longer "v0.1 draft", section 2 broken into headed subsections, a data-model diagram and an inspection sequence diagram (Mermaid), section 9 brought current | A reviewer agent with only these documents lands a label change in one session |
| 2.7 | **Release 0.4.1**: notes, gate record, tag | — |

## Stage 3: Service boundary, in process (18 to 25 days, tag `v0.5.0`)

Entry: `v0.4.1` tagged; issues opened for each item. Exit: `InspectionCycle` exists and the Inspection page is a thin driver of it; `aoi/core/services/` is a package of eight modules behind the same facade; the read API is typed and `ANN401` is on; `settings.json` has a schema version and a machine profile; upgrade and rollback are one step each and rehearsed from installers; the regression set is byte-identical to `b5bf413`.

| PR | Scope | Cites | Days | Done when |
|---|---|---|---|---|
| 3.1 | **`InspectionCycle`** in `aoi/core/cycle.py`: engine currency check, build, load, inspect, `log_result`, moved-run detection, the four operational alarms, taking a frame source (`grab() -> (frame, meta)`) and yielding `Outcome` dataclasses; `inspection.py:296-386` becomes a driver | issue | 3 to 4 | The page loses the logic; a headless test runs ten boards through the cycle with a `FolderCamera` and gets the same records as the page did |
| 3.2 | **Service split** by mixins into `aoi/core/services/{context,board_models,samples,datasets,training,inspection,testing,history}.py`, constants and phrases into `messages.py`, `AppContext` assembled from them; no caller changes | issue | 2 to 3 | 234 UI call sites and 129 test call sites unchanged; `REQUIRED_ROLE` registry still complete |
| 3.3a–3.3d | **Typed results.** `TypedDict`s or frozen dataclasses for the fifteen hottest row shapes (sample, model version, inspection, dataset, store, test run, recipe revision, user, alarm, audit entry, label, box, check, defect, board model), returned from `Database` and passed through; `ANN401` on for `aoi/core/services/`; UI subscripts re-pointed one page per PR: `training_versions.py` (101), `training.py` (97), `model_test.py` (89), `logs.py` (75), then the rest; `Outcome`, `Stored`, `Evaluated` tuples replaced | issue | 4 to 6 | Zero `["key"]` subscripts on service results in `aoi/ui`; mypy strict still green with `Any` count under 100 |
| 3.4 | **Workers absorbed.** `Page.run_named(name, …)` allowing N concurrent named workers with the same weakref guards; the eleven hand-rolled copies deleted | issue | 1 to 2 | One worker implementation |
| 3.5 | **Inversions.** `VIEWS` out of `aoi/hal` into `aoi/views.py`; `hal` no longer imports `core`; `sqlite3` out of `services.py` and `errors.py` behind `db.is_busy` and `DbError`; `test_layers` extended to forbid executable engine imports from pages (types and constants allowed) | issue | 0.5 | `test_layers` green with the new rules |
| 3.6 | **Settings schema and machine profile** (REQ-SET-014): `schema_version` in `settings.json` with a migration; `%ProgramData%\AOI PoC Inspector\profile.json` layered under user settings with locked keys; `--check-config`; station policy (caps, retention, device) separated from UI state (`last_page`, theme) | REQ-SET-014 | 3 | Fifty synthetic stations configured from one profile in a test; a locked key cannot be changed on Settings |
| 3.7 | **Upgrade rehearsal and one-step rollback** (REQ-SET-015): a scripted rehearsal on a Windows VM from real installers (`v0.3.0-rc.1` → `v0.4.0` → `v0.5.0-rc`), including app-running and WAL cases; the installer keeps the previous `_internal` as `_previous`; `--rollback` restores the database backup and the folder, audited | REQ-SET-015 | 4 to 5 | Rollback is one command; rehearsal record in `docs/tests/` |
| 3.8 | **Migration matrix.** A committed fixture database from `v0.3.0-rc.1` and from `v0.4.0`, populated; upgrade tests from each shipped baseline to head | REQ-SET-016 | 2 | Every shipped baseline upgrades in CI |
| 3.9 | **Sign-in** (REQ-USR-002 to -005, D3): Argon2id passwords for Engineer and Admin, Operator picker with optional PIN, lockout, idle end, first Admin in the first-run guide with a recovery code | REQ-USR-002…005 | 5 | Only if D3 says Stage 3 |
| 3.10 | **Korean on the demo path** (D7): `QTranslator` installed, `.qm` shipped, the demo-path strings translated with the Charter glossary, a review table for Jay, Korean screenshots | REQ-SET-006 | 3 to 4 | After 3.1 to 3.5 only, when strings have stopped moving |
| 3.11 | **Release 0.5.0**: notes, gate record, register status, tag | — | 1 | |

## Stage 4: Engine out of process (15 to 20 days, tag `v0.6.0`; start only when Stage 2 hardware is scheduled)

Entry: `v0.5.0` tagged; a camera and lighting controller on order; D5 decided. Exit: the engine runs as its own process under a supervisor; the HMI reconnects after an engine restart within 5 s and the operator sees one plain line; a cycle runs headless from a camera adapter; the 8-hour soak, 20 power-offs and offline hour pass on the reference PC with the split in place.

| PR | Scope |
|---|---|
| 4.1 | ADR 0025: IPC over a named pipe (Windows) or Unix socket; REQ-SET-003 amended per D5; the API versioned; errors travel as `code + params`; frames by shared file or shared memory, never by copying through the pipe |
| 4.2 | The typed API from Stage 3 served over IPC; `AppContext` becomes the server side; the HMI gets one client adapter and no other change |
| 4.3 | Supervisor (restart on exit, back-off, crash record), HMI reconnect, an event stream for progress, verdicts and alarms |
| 4.4 | `Inspector.judge` promoted to named pipeline stages when the first Stage 2 check lands; the camera adapter written against `InspectionCycle`; per-view recipes |
| 4.5 | Autostart at logon with restart-on-failure, kiosk guidance, the station checks run and recorded |

## Stage 5: Fleet (2027, past ten stations)

A separate, small, networked product: configuration and update distribution, inventory, licence issue, collection of the heartbeat and counters the stations already write, a web dashboard on PostgreSQL. The station never depends on it. Scope it when the first customer has more than ten stations or a second customer signs.

---

## 5. What is deliberately not in this plan

- Any change to how a verdict is computed, the AI architecture, or the thresholds.
- Stage 2 to 4 hardware adapters before Stage 4.
- A web front end on the station, a database daemon on the station, or a metrics stack on the station.
- Moving from PyInstaller and Inno Setup to MSIX.
- Replacing the single serialised SQLite connection with a pool.
- Rewriting `jobs.py`, `workers.py`, `atomic.py`, `migrate.py`, `imaging.py`'s decoder defences, the error model's shape, the regression set, `perf_compare.py`, or the autouse test invariants.

## 6. Exit checklist for every stage

- [ ] All CI green on the tag; the nightly green the night before.
- [ ] `tests/regression/expected.json` identical to `b5bf413` (Stages 0 to 3).
- [ ] Register status column updated for every row the stage touched; `tools/trace_matrix.py` green.
- [ ] Release note cut; Known issues honest; the Korean file marked draft.
- [ ] Release-gate record written with evidence or the gap and its owner; no box ticked that needs the reference PC, a certificate or a native reader unless it was done.
- [ ] A reviewer agent that did not see the stage's diffs has read the stage's exit criteria and reported each as met or not, with evidence; every "not" is answered in writing.
- [ ] The progress file's last line is the tag.
