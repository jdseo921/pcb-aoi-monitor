# 2026-11 handover: progress

Read this file right after `docs/plans/2026-11-handover-plan.md`, the plan of record. One line per planned pull
request; a session updates its line in the same pull request that changes the state. States: **planned**, **in
progress** (branch named), **in review** (PR number), **merged** (date), **dropped** (reason and decision).

## Working rules (production plan, section 1; they hold until `v0.5.0` is tagged)

1. **One pull-request train per working day, at most.** Each PR is at most **400 changed lines**, not counting
   generated files (`aoi/i18n/aoi_ko.ts`, `docs/error-codes.md`, screenshots, and the exported text of
   `docs/standards/`, Jay's decision of 2026-11-01; the lines changed by hand in a copy count), and carries one concern.
2. **Feature freeze until Stage 3 is tagged.** No new register row of kind "feature"; only the rows the handover
   plan (section 5) and the production plan (section 4) name. Decision D2 in ADR 0024 (provisional).
3. **Every stage ends on a tag** (`v0.4.0`, `v0.4.1`, `v0.5.0`, …) with all CI green, the register's status column
   updated, the release note cut and the release-gate record written honestly.
4. **Fresh-eyes review is a subagent.** Every PR gets a review by a subagent that has not seen the diff, against the
   CLAUDE.md checklist; Jay reads the diff and the review, and merges. Claude never approves or merges its own change.
5. **The regression set stays byte-identical** through Stages 0 to 3: `tests/regression/expected.json` unchanged
   since `b5bf413`. Any PR that would alter it stops and asks.
6. **The plan of record lives in the repository**: the handover plan, the production plan, this file, ADR 0024 and
   (from PR 0.2) the Standards in `docs/standards/`. Chat is for instructions, not for the record.
7. **Decisions are written before code.** A new MUST conflict becomes a numbered decision in ADR 0024 before the PR
   that needs it.

## G0: Scope (no tag)

| PR | Scope | Register | State |
|---|---|---|---|
| 0.1 + 0.3 | Plan of record committed, this file, the diagnosis, ADR 0024 (D1 to D19 provisional, D20 to D23 found by the diagnosis), the register rows and priority moves | REQ-SET-023 to -027, REQ-LOG-010, REQ-INSP-020, -021, REQ-TST-009, -010 added | merged 2026-11-01 |
| 0.2 | The four Standards exported to `docs/standards/`, CLAUDE.md and citations re-pointed, a check that every cited Standard is in the repo | — (cite #5) | merged 2026-11-01 (#422) |
| 0.4 | Version discipline: `APP_VERSION` 0.4.0.dev0, CI fails a migration or status change without a bump, build number, VERSIONINFO, signed-build naming | REQ-SET-023 | merged 2026-11-01: 0.4a #423 (the version and its CI check), 0.4b #424 (build number, VERSIONINFO, signed naming) |
| 0.5 | "Working rules until v0.5.0" in CLAUDE.md, the PR template with the change-note checklist | — (cite #5) | merged 2026-11-01 (#425) |
| G0 doc | The scope document signed by Jay, the company and the factory (not software) | — | planned |

## G1: Safe to run (tag `v0.4.0`)

| PR | Scope | Register | State |
|---|---|---|---|
| 1.1 | Disk guard: alarm at 80 %, NG-only evidence at 95 %, start-up no longer refuses the workspace on a full disk | REQ-LOG-006 | merged 2026-11-01: 1.1a #426 (engine), 1.1b #427 (status bar and CSV) |
| 1.2 | Evidence policy (D1) | REQ-INSP-012 | merged 2026-11-01 (#428) |
| 1.3 | Retention on a timer | REQ-LOG-010 | merged 2026-11-01 (#429); its deletions wait for an Admin's in-app confirmation, D20 and D21 still provisional in ADR 0024 |
| 1.4 | Heartbeat, `alerts.jsonl`, start-up self-check, clean-exit marker | REQ-SET-024 | merged 2026-11-02: 1.4a #431 (heartbeat, alerts and clean exit), 1.4b #432 (the self-check) |
| 1.5 | Crash record (`faulthandler`, WER LocalDumps documented) | REQ-SET-026 | merged 2026-11-02 (#433) |
| 1.6 | Support bundle and About | REQ-LOG-007, REQ-SET-011 | merged 2026-11-02: 1.6a #434 (the bundle and its command line), 1.6b #435 (the Admin button, About and the station ID) |
| 1.7 | Workspace guards: remote drive and OneDrive root refused | REQ-SET-025 | merged 2026-11-02 (#436) |
| 1.8 | Signing hygiene and installer wording | REQ-SET-012 | merged 2026-11-02 (#437); the pilot CA key has no offline backup, as Jay chose |
| 1.9 | Release kit, `verify.ps1`, `inventory.ps1`, release runbook | REQ-SET-027 | merged 2026-11-02 (#438) |
| D.1 | Accounts: Argon2id passwords, the users migration, sign-in dialog | REQ-USR-002, REQ-USR-007 | in review: D.1a the hash, its rules and migration 0029 (#439); D.1b sign-in with a password and the dialog (`feat/REQ-USR-002-passwords`) |
| D.2 | Accounts: Operator shift start with optional PIN, lockout, idle end | REQ-USR-003, REQ-USR-004 | in review: D.2a lockout and Unlock User (#441); D.2b the PIN and the idle end (`feat/REQ-USR-003-pin-idle`) |
| D.3 | Accounts: first Admin with a recovery code, user administration | REQ-USR-005, REQ-USR-006 | planned |
| E.1 | `InspectionCycle` in `aoi/core/cycle.py` (production plan 3.1, pulled into G1) | issue (to open) | planned |
| E.2 | Watched input folder (`FolderWatch`) and the file-naming contract | REQ-INSP-020 | planned |
| E.3 | Result file per board, end-of-shift CSV, `docs/schemas/result-file.schema.json` | REQ-INSP-021 | planned |
| F.1 | Korean for the operator: `QTranslator`, `.qm` shipped, operator path translated | REQ-SET-006 (operator scope) | planned |
| F.2 | Offline licence key and the EULA page | REQ-SET-010, REQ-SET-022 | planned |
| F.3 | Station hardening: autostart with restart on failure, kiosk guidance, self-check alarms | REQ-SET-024 | planned |
| R.1 | Nightly 72-hour synthetic line run through the input folder | REQ-INSP-011 | planned |
| R.2 (1.10) | Release 0.4.0: notes in both files, gate record, threat model, register status, tag | — | planned |

G1 exit, besides the plan's criteria: no row in `docs/requirements/stage1.md` still carries a bracketed MUST G1
priority when `v0.4.0` is tagged; each bracket goes with its row's first passing test.

## Stage 2: Human-sized (tag `v0.4.1`, no behaviour change)

| PR | Scope | Register | State |
|---|---|---|---|
| 2.1 | Test layout (`tests/unit`, `service`, `ui`, `policy`, `tools`, `slow`), `tests/support/`, markers | issue | planned |
| 2.2 | Lint extraction: the AST scanners and regenerate-and-compare checks as `tools/lint_*.py` under pre-commit | issue | planned |
| 2.3 | CI speed: caches, `xdist` for UI, timing as artifacts, perf job required, nightly workflow, UI coverage measured | issue | planned |
| 2.4 | Screenshots in Git LFS, one per page per theme, approval from a CI workflow | issue | planned |
| 2.5 | Trace gate on the PR title only (D6) | issue | planned |
| 2.6 | `Makefile`, `tests/README.md`, `CONTRIBUTING.md`, `docs/MAP.md`, architecture document restructured with diagrams | issue | planned |
| 2.7 | Release 0.4.1 | — | planned |

## Stage 3: Service boundary, in process (tag `v0.5.0`)

| PR | Scope | Register | State |
|---|---|---|---|
| 3.2 | Service split into `aoi/core/services/` (eight modules behind the same facade) | issue | planned |
| 3.3a | Typed results, pages `training_versions.py` and `training.py` | issue | planned |
| 3.3b | Typed results, pages `model_test.py` and `logs.py` | issue | planned |
| 3.3c | Typed results, `compare.py`, settings and recipe pages | issue | planned |
| 3.3d | Typed results, the rest; `ANN401` on for the services; `docs/API.md` generated | issue | planned |
| 3.4 | Workers absorbed into `Page.run_named` | issue | planned |
| 3.5 | Inversions: `VIEWS` out of `aoi/hal`, `sqlite3` out of services and errors, `test_layers` extended | issue | planned |
| 3.6 | Settings schema version and machine profile | REQ-SET-014 | planned |
| 3.7 | Upgrade rehearsal from real installers and one-step rollback | REQ-SET-015 | planned |
| 3.8 | Migration matrix with populated fixture databases from each shipped baseline | REQ-SET-016 | planned |
| 3.10 | Korean for the rest of the UI (Engineer and Admin screens), if D7 puts it here | REQ-SET-028 | planned |
| 3.11 | Release 0.5.0, the box-by-box evidence sheet started | — | planned |

Production plan PRs 3.1 (cycle) and 3.9 (sign-in) moved into G1 as E.1 and D.1 to D.3.

## G2: Validated on the factory's boards (no new software)

| Item | Scope | Register | State |
|---|---|---|---|
| G2 prep | `docs/handover/g2-validation-procedure.md`, dry run on a synthetic set of the factory's size | REQ-TST-008, REQ-INSP-014 | planned |
| G2 run | The validation on the factory's locked set, signed by the factory's quality lead and Jay | REQ-TST-008 | planned (waits on the factory's images) |

## G3: Handover package (tag to be decided: the plan says `v0.4.1`, which Stage 2 already uses)

| PR | Scope | Register | State |
|---|---|---|---|
| H.1 | Commissioning checklist per station | — | planned |
| H.2 | Manuals (operator, engineer, administrator) in English and Korean, each section followed by a reviewer agent | — | planned |
| H.3 | Support runbook (symptom or code, meaning, action, what to collect; escalation) | — | planned |
| H.4 | Acceptance protocol the company runs on its own PC, with a sign-off template | — | planned |
| H.5 | Training agenda and the demo kit for the factory's boards | — | planned |
| H.6 | `docs/API.md`, `docs/schemas/`, `docs/operations/metrics.md` checked complete; box-by-box evidence sheet completed | — | planned |
| H.7 | Release of the handover package and its tag | — | planned |

## After G3 (the factory's steps; listed so the rows have a home)

| PR | Scope | Register | State |
|---|---|---|---|
| S.1 | Shadow comparison: human verdict beside the machine's, report per shift and week | REQ-TST-009 | planned |
| S.2 | Sampled audits of OK boards | REQ-TST-010 | planned |

## Log

- 2026-10-31: branch `docs/handover-pack` (e723fd5) holds the four plan files; this file, the diagnosis, ADR 0024 and
  the register changes added in the same docs-only PR.
- 2026-11-01: #421 (dependency advisories, #420) opened against `main` to clear the Security scans job; 0.1 + 0.3 is
  rebased on it once it is green. PR 0.2 on `docs/standards-in-repo`: the four Standards exported (Charter revision 24,
  the others revision 11).
- 2026-11-01: PR 0.2 opened as #422 after its review (8 findings, all fixed or answered in the PR). PR 0.4 on
  `feat/REQ-SET-023-version-discipline` (0.4a): `APP_VERSION` 0.4.0.dev0 and `tools/check_version_bump.py` in CI; the
  seven Settings screenshots, which show the version, re-approved; the regression set unchanged. 0.4 is two PRs, as it
  came to about 550 changed lines in one.
- 2026-11-01: PR 0.4b on `feat/REQ-SET-023-build-identity`: CI's run number in BUILD-INFO.txt, the log's app_version and
  the .exe's VERSIONINFO; one `SIGNED` value for signing and naming. The pilot certificate's owner in the signed
  installer's text is taken from `installer/pilot-ca.cer` ("AOI PoC Inspector"); Jay kept that name on 2026-11-01.
- 2026-11-01: PR 0.5 on `docs/working-rules-and-pr-template`: CLAUDE.md "Working rules until v0.5.0" and
  `.github/pull_request_template.md`, whose checklist a test keeps equal to CLAUDE.md's and the Charter's. On
  2026-11-01 Jay decided the exported Standards' text counts as generated (rule 1), so #422 is about 316 lines.
- 2026-11-01: Jay's decisions on the Stage 0 report: keep "AOI PoC Inspector" on the pilot certificate; count the
  exported Standards' text as generated (rule 1); make "Version moves with what ships" a required check, which is
  added to main's branch protection once #423 has merged (before then no pull request into main runs it).
- 2026-11-01: Jay said "Keep going": Prompt 2 started, stacked on #425; D1 put to Jay for confirmation before PR 1.2.
  PR 1.1 came to about 510 lines, so it is two: 1.1a the engine (`feat/REQ-LOG-006-disk-guard`), 1.1b the status
  bar's free space and the CSV's `evidence` column (`feat/REQ-LOG-006-disk-status`). Tests fill a 128 MB tmpfs where
  they may mount one (root on Linux), else a folder counted against 128 MB, as on CI; all others pin it at 60 %.
- 2026-11-01: Jay confirmed D1 as written. PR 1.2 on `feat/REQ-INSP-012-evidence-policy`: an OK board's overlay as
  JPEG (quality 90) with a `_prev.jpg` preview, `ok_evidence` on Settings (`full` for full resolution on every board).
  Measured on 8 synthetic boards at 5 MP: 7.32 MB written per board before; after, 3.82 MB per OK board at save and
  0.68 MB kept once its maps go, NG unchanged at 7.32 MB.
- 2026-11-01: PR 1.3 (`feat/REQ-LOG-010-retention`): retention at start and hourly; its deletions but OK maps wait for an
  Admin's Confirm Retention Policy (D20 as proposed). D20 and D21 are on a decision card to Jay.
- 2026-11-02: Jay said "Keep going" with #429 to #435 not yet merged: Prompt 4 started, stacked on #435. PR 1.7 on
  `feat/REQ-SET-025-workspace-guards`: AOI-SET-024 at start and on Settings for a UNC path, a remote drive letter or a
  folder under a OneDrive root.
- 2026-11-02: PR 1.8 on `feat/REQ-SET-012-signing-hygiene`: the signing secrets in the two signing steps only; the
  installer check holds each variant to its name, label and signature; the monthly expiry workflow; the CA key has no
  backup by design (not exportable), and keeping an offline exportable copy is put to Jay.
- 2026-11-02: PR 1.9 on `feat/REQ-SET-027-release-kit`; a run of its runbook on a clean VM waits for the release.
- 2026-11-02: Jay merged #429 to #438 in order, chose no offline backup of the pilot CA key, and confirmed D3 (accounts
  with passwords before G1) on a decision card. On his "Go", Prompt 5 (train D) started, the second train today. PR D.1
  came to about 620 lines, so it is two: D.1a the Argon2id hash (argon2-cffi 25.1.0, MIT), its rules and migration
  0029, with no change in behaviour; D.1b sign-in with a password and its dialog, where the seeded Engineer and Admin
  choose their password at their first sign-in until D.3 brings the first-run Admin.
- 2026-11-02: after train D, Jay said "Keep going"; Prompt 6 waits for train D's merge and the factory's file-naming
  contract. `ci/REQ-SET-020-windows-test-time`: the Windows test job may run 120 minutes (Linux keeps 75), as the 75-minute
  limit stopped the Windows jobs of #442 to #445 with no test failed (#444's suite at 91 % after 73 minutes).
