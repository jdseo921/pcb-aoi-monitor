# Claude Code prompts: the handover plan, prompt by prompt

Paste one at a time, each in a **fresh session** after you have reviewed and merged the previous prompt's PRs. Each prompt is self-contained: it tells Claude Code which files to read first, so it survives a new session or a context compaction. Between prompts you merge, pull `main`, and answer whatever the report asked.

**The files Claude Code reads** (committed by Prompt 0):

| File | What it is |
|---|---|
| `docs/plans/2026-11-handover-plan.md` | The plan of record: gates G0 to G6, the handover boxes (section 2a), decisions D1 to D19, register changes |
| `docs/plans/2026-11-production-plan.md` | The PR-level engineering detail for Stages 1 to 3 that the handover plan reorders |
| `docs/reviews/2026-11-01-production-readiness-review.md` | The diagnosis baseline: every finding with file and line at `b5bf413`, to be re-verified |
| `docs/plans/2026-11-handover-progress.md` | One line per PR; the first thing a new session reads after the plan |
| `docs/plans/claude-code-prompts-handover.md` | This file |

**Install the pack (you, once):** unzip `claude-code-pack.zip` at the repository root so the files land at the paths above, then open Claude Code in the repo on an up-to-date `main` and paste Prompt 0. Prompt 0 commits them.

---

## Prompt 0 — Diagnosis and plan of record (docs-only PR; nothing else changes)

```
I am Jay, the product owner. Four new files are in the working tree, not yet committed: docs/plans/2026-11-handover-plan.md, docs/plans/2026-11-production-plan.md, docs/reviews/2026-11-01-production-readiness-review.md and docs/plans/claude-code-prompts-handover.md. Read all four in full, then CLAUDE.md, docs/ARCHITECTURE.md, docs/requirements/stage1.md and the four AOI Standards CLAUDE.md links. If you cannot open the Standards' links, stop and tell me; I will paste them.

The handover plan is the plan of record from now on. Its decisions D1 to D19 are mine to take; where it names a recommended default, treat the default as my provisional answer and mark it "provisional" until I confirm.

Do these, on a branch docs/handover-plan-of-record, as ONE docs-only PR:

1. Commit the four files as they are. Create docs/plans/2026-11-handover-progress.md with the working rules from the handover plan's section 1 of the production plan at the top (one PR train a day, 400 changed lines, feature freeze, every stage on a tag, fresh-eyes subagent review, regression set byte-identical, plan of record in the repo) and one line per planned PR of G1, Stage 2, Stage 3 and G3 with state "planned".

2. DIAGNOSIS. Re-verify every finding in the review (sections 2 and 4 to 8) against the current head: every count, every file and line. Write docs/reviews/2026-11-diagnosis.md with, for each layer, a verdict and its evidence:
   - Frontend (aoi/ui), Backend engine (aoi/core minus services), Service layer and API (services.py and the UI-engine contract), Database and data layer (aoi/data, migrations, files on disk), Monitoring and operations (logging, heartbeat, alarms, support, retention, disk), Deployment (build, install, upgrade, rollback, signing, version identity), Tests and CI, Documentation and process.
   - For each: KEEP (sound, leave alone) / REFACTOR IN PLACE (sound foundation, structure or policy to change, named items) / OVERHAUL (rebuild), with the measured evidence at head, what the review said, and whether the review's claim still holds, moved, or was wrong.
   - Then answer the question I actually have, in one table: "If this build were handed to the company today and run in a factory for six months unchanged, what breaks, when, and how badly?" One row per failure mode (disk, version identity, silent I/O failure, accounts, key loss, workspace on a synced folder, native crash, anything you find), with the day or event it happens on and the evidence. Be exact about the disk estimate: measure the actual bytes of an overlay and the two maps for a 5 MP synthetic board on this machine and redo the arithmetic.
   - Close with one paragraph: do you confirm "refactor in place, do not restart", or not, and why. If you disagree with the review anywhere, say so plainly; do not soften it.

3. Draft docs/adr/0024-handover-plan-decisions.md with D1 to D19, each with its recommended default, marked provisional, and the requirement rows it touches.

4. Register: add the rows the handover plan's section 5 and the production plan's section 4 name, and make the priority moves. First read tools/trace_matrix.py and docs/requirements/README.md and tell me how a new MUST G1 row that has no test yet can be added without turning the trace gate red (a status word, a priority the gate accepts, or whatever the register's own convention is); use that mechanism and say which you used. Run python tools/trace_matrix.py and confirm it passes.

5. Change nothing under aoi/, tests/ or tools/ in this PR. Run ruff, format, mypy and the test suite anyway to record the baseline time of a full local run in the diagnosis.

Open the PR and stop. Report: the layer verdict table, the six-months table, your position on restart versus refactor, the register mechanism you used, any decision you think I should change and why, and the questions you need answered before G1 can start.
```

---

## Prompt 1 — Stage 0: Standards in the repo, version discipline, the freeze

**Before you paste:** read the diagnosis; answer its questions; merge the Prompt 0 PR; pull `main`. Confirm or change the provisional decisions in the PR comments and paste your answers where marked.

```
Read docs/plans/2026-11-handover-plan.md, docs/plans/2026-11-handover-progress.md and docs/reviews/2026-11-diagnosis.md, then CLAUDE.md. The working rules in the progress file apply.

My answers to the diagnosis questions and the provisional decisions: <PASTE, NUMBERED>. Update docs/adr/0024-handover-plan-decisions.md: each decision I confirmed loses "provisional"; each I changed is rewritten with my reason.

Do production plan PRs 0.2, 0.4 and 0.5 as three stacked PRs:

0.2 Standards into the repo: export the four Standards to docs/standards/charter.md, engineering.md, customers-and-launch.md and legal-and-compliance.md, faithfully and whole; re-point CLAUDE.md and the ADRs' and register's citations to the files, keeping the artifact links as "source"; a test or lint that fails when CLAUDE.md cites a Standard that is not in docs/standards/.

0.4 Version discipline (REQ-SET-023): APP_VERSION to 0.4.0.dev0; a CI job that fails when aoi/data/migrations/ gains a file, or the register's status column changes, without APP_VERSION moving since the last tag; a build number from CI in BUILD-INFO.txt and in the log's app_version; a VERSIONINFO resource on the exe in installer/aoi.spec; a pilot-signed build named without "unsigned" and the installer's welcome text saying "Pilot build, signed with the <company> pilot certificate"; the "never go to a customer" sentence only on unsigned builds.

0.5 The freeze and the solo rules: a "Working rules until v0.5.0" section in CLAUDE.md summarising the progress file's rules; .github/pull_request_template.md carrying the change-note checklist so individual commits no longer need it (the trace gate's scope changes in Stage 2; do not touch tools/trace_matrix.py here).

Each PR: ruff, format, mypy, pytest green; a fresh-eyes subagent review with every finding fixed or answered; the progress file updated. Stop after the third PR and report.
```

---

## Prompt 2 — G1 train A: disk guard, evidence policy, retention

**Before you paste:** merge Stage 0 in order; pull `main`. D1 (evidence policy) must be confirmed.

```
Read docs/plans/2026-11-handover-plan.md (G1 and D1), docs/plans/2026-11-production-plan.md (Stage 1, PRs 1.1 to 1.3), docs/plans/2026-11-handover-progress.md, docs/reviews/2026-11-diagnosis.md (the disk row), then CLAUDE.md. Working rules apply.

Do PRs 1.1, 1.2 and 1.3 as three stacked PRs.

1.1 Disk guard (REQ-LOG-006): free space measured at start and before each save; an alarm with a code at 80 %; at 95 % the record and NG and WARN evidence are saved and OK overlays and maps are skipped with a note in the record and the CSV; a status-bar indicator with the free space; the start-up archive step can no longer refuse the workspace on SQLITE_FULL (it degrades to an alarm and the app opens). Tests fill a bounded temporary filesystem to each threshold.

1.2 Evidence policy (D1, REQ-INSP-012, ADR 0024): the overlay writer honours the policy from settings (NG and WARN full-resolution overlay and maps; OK a JPEG overlay at quality 90 plus a preview at PREVIEW_PX, maps 7 days); Compare, Logs & Export, AI Model Test and every export read whichever file exists; the CSV gains an evidence column naming what was kept; the policy is shown on Settings and in About. The regression set must stay byte-identical: the policy changes what is stored, never what is judged. Measure and report the bytes per OK and per NG 5 MP board before and after.

1.3 Retention on a timer (REQ-LOG-010): one Retention service in aoi/core (no Qt), run by a timer the context owns, at start and every hour: OK maps past their days, log files (90 days, gzip after 7), migration backups (keep the last 3), test-run overlays past their days, orphan files whose record is gone; every sweep audited with counts; a settings page line showing the last sweep. Test on a synthetic 30-day workspace.

Each PR: checks green, fresh-eyes review, progress file, release-note line, register status column. Stop after the third PR and report, with the before-and-after bytes and the new disk arithmetic for one board every 10 seconds.
```

---

## Prompt 3 — G1 train B: heartbeat and self-check, crash record, support bundle and About

**Before you paste:** merge train A; pull `main`.

```
Read docs/plans/2026-11-handover-plan.md (G1, section 2a "Production-grade monitoring"), docs/plans/2026-11-production-plan.md (PRs 1.4 to 1.6), docs/plans/2026-11-handover-progress.md, then CLAUDE.md. Working rules apply.

Do PRs 1.4, 1.5 and 1.6 as three stacked PRs.

1.4 Heartbeat, self-check, clean exit (REQ-SET-024): heartbeat.json rewritten atomically every 60 s with pid, app and build version, uptime, last inspection time, boards and NG and reviewed false calls in the last hour, mean and p95 verdict time, free bytes, WAL size, the active AI model and recipe revision; an alerts.jsonl that every alarm is appended to, for the company's tools to tail; app.close logged on every clean exit and "did not close cleanly" logged at the next start after a kill; a start-up self-check (PRAGMA quick_check, every unshredded store's key present, records whose files are missing, .tmp and .bak counts, free space, input and output folders writable once they exist) with one coded alarm per failure; docs/operations/metrics.md naming every field.

1.5 Crash record (REQ-SET-026): faulthandler enabled to logs/ at start; the installer documents the WER LocalDumps key as an opt-in; version, build and commit in every error dialog's Details. A test forces a fault in a subprocess and finds the file.

1.6 Support bundle and About (REQ-LOG-007, REQ-SET-011): one click for an Admin and a --support-bundle command line: a zip with the last 7 days of logs, settings.json scrubbed of anything secret, schema_version, BUILD-INFO, sbom.cdx.json, the heartbeat history, alerts.jsonl, alarms and the audit trail as CSV, free disk, torch, CUDA, driver, OS, CPU and RAM facts; no image unless a box is ticked; nothing REQ-USR-007 forbids; written where the user chooses, audited. About from the header for every role: app, build, commit, AI model and recipe versions of the selected board model, schema version, station ID if any, licence line (empty until G1 train F), third-party notices.

Each PR: checks green, fresh-eyes review, progress file, release-note line, register status. Stop after the third PR and report; include a heartbeat.json and an alerts.jsonl sample from a test run.
```

---

## Prompt 4 — G1 train C: workspace guards, signing hygiene, release kit and runbook

**Before you paste:** merge train B; pull `main`.

```
Read docs/plans/2026-11-handover-plan.md (G1, section 2a "Trusted deployment"), docs/plans/2026-11-production-plan.md (PRs 1.7 to 1.9), docs/plans/2026-11-handover-progress.md, docs/adr/0011-release-gate-decisions.md, .github/workflows/build.yml, then CLAUDE.md. Working rules apply.

Do PRs 1.7, 1.8 and 1.9 as three stacked PRs.

1.7 Workspace guards (REQ-SET-025): a workspace on a remote drive (GetDriveType DRIVE_REMOTE, UNC path) or under a OneDrive root is refused at pick time and at start with a code and a plain reason; the install guide says why.

1.8 Signing hygiene (REQ-SET-012, ADR 0011): the PFX and password visible only to the two signing steps in build.yml, not job-wide; docs/install/pilot-signing.md gains the CA key backup procedure, the leaf renewal date and a reminder mechanism, and the CA-loss recovery steps; the installer's signed and unsigned wording from Stage 0 verified on both variants by tools/check_installer.py.

1.9 Release kit and runbook (REQ-SET-027): CI assembles the kit as an artifact: the signed installer, SHA256SUMS.txt, the provenance bundle downloaded for offline verification, installer/pilot-ca.cer, the release note, verify.ps1 (Get-AuthenticodeSignature on the installer and exe, hash check, provenance check if the bundle is present) and inventory.ps1 (installed version and build from the registry and BUILD-INFO); docs/release/runbook.md as an ordered checklist from version bump to kit handed over, with the station checks as a step; tests run both scripts on Windows CI.

Each PR: checks green, fresh-eyes review, progress file, release-note line, register status. Stop after the third PR and report.
```

---

## Prompt 5 — G1 train D: accounts with passwords

**Before you paste:** merge train C; pull `main`. D3 must be confirmed (it is a MUST move from 1.0 to G1).

```
Read docs/plans/2026-11-handover-plan.md (G1 "Accounts", D3), docs/adr/0002-local-sign-in.md, docs/requirements/stage1.md rows REQ-USR-002 to REQ-USR-007, docs/standards/engineering.md (security), docs/security/threat-model.md rows on users, docs/plans/2026-11-handover-progress.md, then CLAUDE.md. Working rules apply.

Build accounts in three stacked PRs; these change MUST rows, cite ADR 0024 D3 as my approval.

D.1 Passwords and the migration (REQ-USR-002, REQ-USR-007): Argon2id hashes for Engineer and Admin with a pinned, licence-checked dependency added through tools/make_lock.py; a migration that adds the hash, status, failed-attempt count and lock time columns and marks the three seeded accounts as needing set-up; a sign-in dialog replacing the bare Switch User for those roles; no password or hash in logs, exports or the support bundle (a test scans them); the audit names the person.

D.2 Operator shift start, lockout and idle end (REQ-USR-003, REQ-USR-004): an Operator picks their name with an optional PIN; an account locks after the configured failed attempts and an Admin unlocks it; Engineer and Admin sessions end after the configured idle time back to the Operator picker, never mid-inspection.

D.3 First Admin and user administration (REQ-USR-005, REQ-USR-006): the first-run guide creates the first Admin with a one-time recovery code shown once with Save and Print as the store key is; an Admin adds users, changes roles, disables, resets passwords, all audited; the demo workspace keeps a known demo Admin so the demo scripts still run unattended, documented in docs/demo/README.md; tests/test_demo_scripts.py stays green.

Each PR: checks green (the screenshot set will change: approve it), fresh-eyes review with a security reading, progress file, release-note line, register status, threat-model rows updated. Stop after the third PR and report.
```

---

## Prompt 6 — G1 train E: the inspection cycle and the line adapter

**Before you paste:** merge train D; pull `main`. D9 and D10 must be confirmed, including the file-naming contract the factory's imaging station will use.

```
Read docs/plans/2026-11-handover-plan.md (G1 "Line adapter", D9, D10, section 1a), docs/reviews/2026-11-01-production-readiness-review.md section 4 (the cycle finding), docs/plans/2026-11-production-plan.md (PR 3.1), aoi/ui/pages/inspection.py, aoi/core/inspector.py, aoi/hal/__init__.py, aoi/core/jobs.py, docs/plans/2026-11-handover-progress.md, then CLAUDE.md. Working rules apply. Open a GitHub issue for the cycle extraction and cite it.

The file-naming contract I agreed with the factory: <PASTE: pattern, fields, example>. The result file fields beyond the plan's list, if any: <PASTE or "none">.

Three stacked PRs.

E.1 InspectionCycle (issue): move the body of the Inspection page's run loop (engine currency check and build, image load, inspect, log_result, moved-run detection, the four operational alarms) into aoi/core/cycle.py as a Qt-free class that takes a frame source with grab() -> (frame, metadata) | None and yields Outcome dataclasses; the Inspection page becomes a thin driver of it; a headless test runs ten boards through the cycle with FolderCamera and produces the same records as the page did. Regression set byte-identical.

E.2 Watched input folder (REQ-INSP-020): a FolderWatch frame source for the cycle: a complete file in the input folder is inspected within 2 s, moved to done/ or failed/, never inspected twice (by SHA-256 and name); a partial file is waited for; the naming contract is validated with a coded refusal to failed/; the Inspection page shows the line running, the queue depth and lets an Operator pause and resume; input and output folders are settings and are checked by the start-up self-check; docs/schemas/input-file-naming.md.

E.3 Result files (REQ-INSP-021): a result per board written atomically to the output folder within 1 s of the verdict, as JSON and as one CSV line (board ID, view, verdict, time, model version, recipe revision, defects with type, severity and box, evidence kept); an end-of-shift CSV listing every board; docs/schemas/result-file.schema.json and a test that validates every written file against it.

Each PR: checks green, fresh-eyes review, progress file, release-note line, register status, operator manual section. Stop after the third PR and report, with a timing of the 2 s and 1 s criteria measured in the test.
```

---

## Prompt 7 — G1 train F: Korean for the operator, licence and EULA, station hardening

**Before you paste:** merge train E; pull `main`. D7 (operator scope) and D16 must be confirmed.

```
Read docs/plans/2026-11-handover-plan.md (G1 "Korean for the operator", "Licence and EULA", "Station hardening"; D7, D16), docs/standards/charter.md (Words we use), aoi/i18n/aoi_ko.ts, docs/plans/2026-11-handover-progress.md, then CLAUDE.md. Working rules apply.

Three stacked PRs.

F.1 Korean for the operator (REQ-SET-006, operator scope): a QTranslator installed at start, aoi_ko.qm built and shipped (PyInstaller data, installer, CI), the Language setting taking effect at once or on the next start (say which and why in ADR 0024); every string an Operator can see translated with the Charter glossary: header, sidebar, Home, Inspection including the line view, Compare's operator view, the alarm list, the review station, the first-run guide, the sign-in and shift-start dialogs, and every error code those paths can raise; machine-assisted strings marked unfinished with a review table for me at docs/i18n/2026-11-operator-korean-review.md; a Korean screenshot set of those pages; a test that nothing on the operator path falls back to English when Korean is selected. Engineer and Admin pages are not in scope.

F.2 Licence and EULA (REQ-SET-010, REQ-SET-022): an offline licence file signed with a key I hold (Ed25519; tools/issue_license.py for me, never shipped), bound to a station machine ID, with a term and a grace period, checked at start with a plain message in both languages; the installer shows the EULA page from a file I provide (placeholder text until then, marked) and installs only after acceptance; About shows the licence holder, station ID and term.

F.3 Station hardening (REQ-SET-024): installer option to create a logon scheduled task that starts the app and restarts it on failure; a kiosk guidance page in docs/install/install.md (auto-logon, Assigned Access); the start-up self-check alarms when the licence, a store key, or the input folder is missing.

Each PR: checks green, fresh-eyes review, progress file, release-note line, register status. Stop after the third PR and report, with the count of strings translated and the list of operator pages covered.
```

---

## Prompt 8 — G1 release 0.4.0 and the 72-hour line run

**Before you paste:** merge train F; pull `main`. Review the Korean table and note any rows to change. Have the reference PC (D8) available if you can.

```
Read docs/plans/2026-11-handover-plan.md (G1 exit criteria), docs/plans/2026-11-production-plan.md (PR 1.10), docs/release-gate/0.3.0.md, docs/release-notes/unreleased.md, docs/tests/station-checks.md, docs/plans/2026-11-handover-progress.md, then CLAUDE.md.

Korean review: <"all rows accepted" OR row numbers with corrected Korean>. Apply it, mark those strings finished, rebuild the .qm.

Two stacked PRs.

R.1 The nightly line run: a workflow that builds a synthetic station with a 5 MP board model, feeds one board every 10 s through the input folder for 72 hours (a shorter run on pull requests), and judges: disk held under the evidence policy, heartbeat present every minute, no alarm of the silent-failure kind, result files for every board, memory growth and slowdown within REQ-INSP-011's 10 %; the report as an artifact; tools/soak.py extended rather than duplicated.

R.2 Release 0.4.0: APP_VERSION 0.4.0; docs/release-notes/unreleased.md to 0.4.0.md and 0.4.0.ko.md (the Korean marked draft), a new empty unreleased.md; Known issues brought current; docs/release-gate/0.4.0.md box by box with evidence or the gap and its owner; the threat model's review log and new rows (accounts, line adapter, licence, support bundle, heartbeat); the register status column for every row G1 touched; python tools/trace_matrix.py green; the exact commands I run to tag v0.4.0 and build the kit, and the station-check steps for the reference PC.

Stop and report: the 72-hour run's result (or the longest run CI allowed, with the number), the gate record's open boxes, and what I must do on the reference PC.
```

---

## Prompt 9 — Stage 2, part 1: test layout, shared helpers, lint extraction

**Before you paste:** tag `v0.4.0`; pull `main`.

```
Read docs/plans/2026-11-handover-plan.md (section 2a "Comprehensive testing", "Technical documentation"), docs/plans/2026-11-production-plan.md (Stage 2, PRs 2.1 and 2.2), docs/reviews/2026-11-01-production-readiness-review.md section 6, tests/conftest.py, docs/plans/2026-11-handover-progress.md, then CLAUDE.md. Working rules apply; no behaviour changes in this stage.

Two stacked PRs, each possibly in several commits.

2.1 Test layout: tests/unit, tests/service, tests/ui, tests/policy, tests/tools, tests/slow with pytest markers and a tests/README.md that names every layer, every autouse fixture and why it exists, and which fixture to pick for a new test; tests/support/ holding _window, station, click, records, the word lists and every helper that other test modules import today, so that no test module imports another test module; pytest -m and Makefile targets (test-fast = unit and service in under 5 minutes locally; test-all); the REQ-id names of tests kept.

2.2 Lint extraction: the six AST scanners (i18n literals, colour literals, 14 pt, attribute shadowing, torch.load, Charter words) and the regenerate-and-compare checks (aoi_ko.ts freshness, docs/error-codes.md) become tools/lint_*.py under a .pre-commit-config.yaml and a two-minute CI job that blocks merges; their self-tests and the tests that parse build.yml and aoi.iss are deleted; the same rules enforced. Report the test count and line count before and after.

Each PR: checks green, fresh-eyes review, progress file. Stop after the second PR and report.
```

---

## Prompt 10 — Stage 2, part 2: CI speed, screenshots from CI, trace gate, docs; release 0.4.1

**Before you paste:** merge Stage 2 part 1; pull `main`. D6 (trace gate scope) must be confirmed.

```
Read docs/plans/2026-11-handover-plan.md (section 2a), docs/plans/2026-11-production-plan.md (PRs 2.3 to 2.7), .github/workflows/ci.yml, tools/render_screens.py, tools/trace_matrix.py, docs/plans/2026-11-handover-progress.md, then CLAUDE.md. Working rules apply; no behaviour changes.

Four stacked PRs.

2.3 CI speed: actions/cache for the synthetic dataset, tiny model, demo bundle and screen workspace keyed on their generators' hashes; pytest-xdist for tests/ui; the screens fixture session-scoped; timing budgets written to a perf.json artifact and judged only on a nightly self-hosted or reference runner; the base-versus-head performance job made a required check in docs/release-gate/branch-protection.json; a nightly workflow for slow, screens, soak, the line run and the review renders; coverage measured for aoi/ui too (reported, not yet gated). Target: pull-request suite at or under 12 minutes per OS over five runs; report the five numbers.

2.4 Screenshots: tests/screens/approved/ moved to Git LFS; one shot per page per theme (role variants covered by the size walk) with the list of removed shots justified; a workflow_dispatch job that renders on Linux and commits the approved set to the PR branch, so approval never needs a local Linux machine; CLAUDE.md's instruction updated.

2.5 Trace gate on the PR title only (D6); the per-commit check removed; the MUST-row check kept on pull requests.

2.6 Docs for the next person: Makefile (i18n, errors, screens, regress, lock, test-fast, test-all, bundle, kit); CONTRIBUTING.md (set-up, the one-line-change walkthrough, the rules that bite, how to approve screenshots from CI); docs/MAP.md (modules, the services and the eight they will become, thread rules, a glossary of the S/Q/B/D/F IDs noting they are historical); docs/ARCHITECTURE.md restructured: no longer "v0.1 draft", section 2 as headed subsections, a Mermaid data-model diagram generated from the migrations and a Mermaid sequence diagram of one inspection through the cycle, section 9 current; README's layout section current. Then release 0.4.1: notes, gate record, tag commands.

Each PR: checks green, fresh-eyes review, progress file. After 2.6, spawn a reviewer agent given only README.md, CONTRIBUTING.md, docs/MAP.md and tests/README.md and ask it to land a one-line label change with green CI; include its account in the report. Stop and report.
```

---

## Prompt 11 — Stage 3, part 1: the service split and the typed API

**Before you paste:** tag `v0.4.1`; pull `main`. Open the GitHub issues for Stage 3's architecture items (or let this prompt open them).

```
Read docs/plans/2026-11-handover-plan.md (section 2a "Clear service boundaries", "Full-stack professionalism"), docs/plans/2026-11-production-plan.md (Stage 3, PRs 3.2 and 3.3), docs/reviews/2026-11-01-production-readiness-review.md section 4, aoi/core/services.py, pyproject.toml, docs/plans/2026-11-handover-progress.md, then CLAUDE.md. Working rules apply; regression set byte-identical; open an issue per item and cite it.

3.2 Service split (one PR): aoi/core/services/ as a package: context.py (lifecycle, actor, requires, transactional, audit, alarms, report_error, load_image), board_models.py, samples.py (import, labels, checks, agreement), datasets.py (versions, stores), training.py (models, cards, export), inspection.py (inspector, cycle glue, log_result, re_evaluate, review, shift check, drift), testing.py, history.py (inspections, exports, archive, delete, settings, users); constants and phrases in messages.py; AppContext assembled from them by mixins so that no caller changes; the REQUIRED_ROLE registry still complete (a test counts it before and after).

3.3 Typed results (one PR per group of pages, 3.3a to 3.3d): TypedDicts or frozen dataclasses for the row shapes sample, model version, inspection, dataset, store, test run, recipe revision, user, alarm, audit entry, label, box, check, defect, board model, returned from Database and passed through; ANN401 switched on for aoi/core/services/; the UI's string-key subscripts re-pointed one page group per PR (training_versions.py and training.py; model_test.py and logs.py; compare.py, settings_*.py, recipe_*.py; the rest); the Outcome, Stored and Evaluated tuples replaced by dataclasses; docs/API.md generated from the service package: every public method, its roles, its typed result, the error codes it raises. A test fails when docs/API.md is stale.

Each PR: checks green (screenshots unchanged: assert it), fresh-eyes review, progress file. Report the Any count, the string-subscript count in aoi/ui and the mypy result before and after. Stop after 3.3d.
```

---

## Prompt 12 — Stage 3, part 2: workers, inversions, settings profile

**Before you paste:** merge Stage 3 part 1; pull `main`.

```
Read docs/plans/2026-11-handover-plan.md (section 2a "Scalable infrastructure"), docs/plans/2026-11-production-plan.md (PRs 3.4 to 3.6), aoi/ui/pages/base.py, aoi/ui/workers.py, aoi/config.py, docs/plans/2026-11-handover-progress.md, then CLAUDE.md. Working rules apply; regression set byte-identical.

Three stacked PRs.

3.4 Workers absorbed (issue): Page.run_named(name, …) allowing N concurrent named workers per page with the same weakref and lifetime guards as run_in_background; the eleven hand-rolled Worker copies deleted; one worker implementation in aoi/ui.

3.5 Inversions (issue): VIEWS out of aoi/hal into aoi/views.py; aoi/hal imports nothing from aoi/core; sqlite3 out of services and errors behind db.is_busy and DbError; tests/test_layers.py extended to forbid pages importing executable engine functions (types and constants allowed), with the current offenders fixed.

3.6 Settings schema and machine profile (REQ-SET-014): schema_version in settings.json with a migration path; a machine-level profile at %ProgramData%\AOI PoC Inspector\profile.json layered under user settings with locked keys; station policy (caps, retention, evidence policy, device, folders) separated from UI state (last page, theme); --check-config; docs/schemas/settings.schema.json and profile.schema.json; a test configures fifty synthetic stations from one profile and shows a locked key cannot be changed on Settings.

Each PR: checks green, fresh-eyes review, progress file, release-note line, register status. Stop after the third PR and report.
```

---

## Prompt 13 — Stage 3, part 3: upgrade rehearsal, one-step rollback, migration matrix; release 0.5.0

**Before you paste:** merge Stage 3 part 2; pull `main`. A Windows VM with the `v0.3.0-rc.1` and `v0.4.0` installers is needed for the rehearsal; say if you do not have one.

```
Read docs/plans/2026-11-handover-plan.md (section 2a "Trusted deployment"), docs/plans/2026-11-production-plan.md (PRs 3.7, 3.8, 3.11), docs/install/install.md, docs/tests/2026-10-11-upgrade-rollback.md, aoi/data/migrate.py, installer/aoi.iss, docs/plans/2026-11-handover-progress.md, then CLAUDE.md. Working rules apply.

Three stacked PRs.

3.7 Upgrade rehearsal and one-step rollback (REQ-SET-015): a scripted rehearsal on a Windows VM from real installers, v0.3.0-rc.1 to v0.4.0 to the current build, including the app-running and WAL-present cases, recorded in docs/tests/; the installer keeps the previous _internal as _previous; --rollback restores the database backup and the previous folder in one command, audited, with a plain confirmation; the install guide's "Going back" rewritten to one step.

3.8 Migration matrix (REQ-SET-016): committed fixture databases from v0.3.0-rc.1 and v0.4.0, populated with records, labels, datasets, a store and a test run; CI upgrades each to head and checks row counts, UUIDs and a sample of verdicts; the migration backup made asynchronously with a progress dialog when the database is large.

3.11 Release 0.5.0: APP_VERSION 0.5.0; notes in both files; docs/release-gate/0.5.0.md; register status; threat model review log; the box-by-box evidence sheet for the handover plan's section 2a started at docs/handover/box-evidence.md, each box with its evidence or its gap; tag commands.

Stop and report, with the rehearsal record and the evidence sheet's gaps.
```

---

## Prompt 14 — G2 preparation: the validation campaign on the factory's boards

**Before you paste:** the factory's photographs are available, or you want the dry run first. D12 and D19 (targets, minimum defect size) must be confirmed.

```
Read docs/plans/2026-11-handover-plan.md (G2, D12, D19), docs/standards/customers-and-launch.md (Validation), docs/manual/engineer.md, docs/requirements/stage1.md rows REQ-TRN-004 to -007, -016, -017, REQ-TST-001 to -008, REQ-INSP-014, docs/plans/2026-11-handover-progress.md, then CLAUDE.md.

The targets agreed at G0: <PASTE D12: per defect type, missed-defect rate, upper bound, false-call rate, N>. The minimum defect size per type: <PASTE D19>. The images are at <PATH> OR "dry run on synthetic boards first".

Do not change the engine. Produce docs/handover/g2-validation-procedure.md: the Validated path step by step as the app enforces it (import, boxes, second-person label check, agreement check on the calibration set, freeze, split and lock, train, validate), who does each step, how long each took in a dry run you perform end to end on a synthetic set of the same size, and the exact clicks; then, if the images are present, perform the import and the labelling preparation only (no second-person check: that must be a person other than me), and report what the "What is missing" checklist says is left. Add tools/validation_dry_run.py if it helps reproduce the dry run. Report the counts, the expected bound at the given N, and whether the targets can be met at all with the NG count the factory supplied; if not, say what count would be needed.
```

---

## Prompt 15 — G3 package: commissioning, manuals, runbook, acceptance protocol, training, evidence sheet

**Before you paste:** tag `v0.5.0`; pull `main`. D15 (binary or source) and D18 (support model) must be confirmed.

```
Read docs/plans/2026-11-handover-plan.md (G3 and section 2a in full), docs/handover/box-evidence.md, docs/manual/*.md, docs/install/*.md, docs/demo/README.md, docs/release/runbook.md, docs/plans/2026-11-handover-progress.md, then CLAUDE.md.

What the company receives (D15): <binaries and kit with source in escrow | source>. The support model (D18): <first line, second line, response times, what the company may change>.

Produce the package in stacked docs PRs, each tested by a reviewer agent that follows it on the build:

1. docs/handover/commissioning-checklist.md per station (PC checks, install from the kit and verify, licence, workspace and disks, input and output folders and permissions, accounts, board model and recipe, master samples, self-check green, first ten boards, sign-off).
2. Manuals: operator (shift start with master samples, the running line, alarms and what to do, NG and WARN handling, the review station), engineer (recipes, thresholds, Compare, a new version, validation, the go-live gate, drift), administrator (users, backup and restore, upgrade and rollback, support bundle, retention and disks, licence); English and Korean; each section tested by an agent following it.
3. docs/handover/support-runbook.md: symptom or code → meaning → action → what to collect; escalation; known issues; what the company may change.
4. docs/handover/acceptance-protocol.md: the script the company runs on its own PC with pass criteria per step (install and verify, accounts, demo, reproduce the G2 report's counts on the validation set, one hour of the line adapter from a replay folder, one power cut mid-run and restart, support bundle, rollback and forward), and a signed-off template.
5. docs/handover/training.md: the one-day agenda and the demo kit adapted to the factory's boards.
6. docs/handover/box-evidence.md completed: every box of section 2a with its evidence link or its honest gap, for the company to sign.

Stop and report the gaps the evidence sheet still shows.
```

---

## Prompt 16 — G4 to G6 software: shadow comparison and sampled audits

**Before you paste:** G3 signed, or the shadow period is being scheduled. D11, D13, D14 confirmed.

```
Read docs/plans/2026-11-handover-plan.md (G4 to G6, D11, D13, D14, the new rows REQ-TST-009 and -010), aoi/ui/pages/review.py, aoi/core/drift.py, aoi/core/report.py, docs/plans/2026-11-handover-progress.md, then CLAUDE.md. Working rules apply.

Two stacked PRs.

S.1 Shadow comparison (REQ-TST-009): the human inspector's verdict recorded beside the machine's for a board, by import of the factory's inspection log by board ID or by two buttons at the review station; a report per shift and per week of agreements, machine-only NG after review (false calls) and human-only NG (escapes), per defect type, with counts and 95 % bounds; exported as CSV and PDF with the usual confirmations; shown on a Shadow tab of AI Model Test for Engineer and Admin.

S.2 Sampled audits (REQ-TST-010): every Nth OK board, N per board model set by an Admin, flagged for a human look at the review station; the audit verdict recorded with who and when; the comparison report continues on the sampled boards; the drift monitor adjusts N within limits the Admin sets.

Both: the engineer manual's procedures for shadow exit, review-only and unattended with audits, and the model-change procedure (new version inactive, go-live gate, re-validation, factory sign-off, activation audited). Each PR: checks green, fresh-eyes review, progress file, register status. Stop and report.
```

---

## Utility prompts

**Resume** (new session or after a compaction):

```
Read docs/plans/2026-11-handover-plan.md, docs/plans/2026-11-handover-progress.md and docs/reviews/2026-11-diagnosis.md, then CLAUDE.md. Tell me in five lines where we stand: the last merged PR, the PR in progress and its branch, what is left in the current gate or stage, and what waits on me. Then continue from the first unfinished item under the working rules, and stop where the current prompt says to stop.
```

**Review findings on a PR:**

```
On PR <NUMBER> (<BRANCH>), my review findings are: <NUMBERED LIST>. Fix each with a test, or answer it in writing with the reason it stands (Charter, "Close every finding"). Do not reopen D1 to D19. Re-run the full local checks, update the change note and the progress file, push, and reply with a table of finding, action, evidence.
```

**A MUST conflict Claude Code raised:**

```
On the MUST conflict you raised (<QUOTE>): my decision is <DECISION>. Record it as D<NEXT> in docs/adr/0024-handover-plan-decisions.md and in the handover plan's section 3 with this reason: <REASON>. Update the affected register row and its test. Continue the current item.
```

**A decision confirmed or changed outside a prompt:**

```
Decision D<N> is now: <TEXT>. Update docs/adr/0024-handover-plan-decisions.md (remove "provisional" or rewrite with my reason), the handover plan's section 3, and any register row it touches. One docs PR. Stop.
```
